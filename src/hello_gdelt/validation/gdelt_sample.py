from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import httpx

from hello_gdelt.config import Paths, ResourceLimits
from hello_gdelt.control.manifest import ManifestStore
from hello_gdelt.gdelt.bronze import BronzeReceipt, write_bronze_parquet
from hello_gdelt.gdelt.download import (
    download_artifact,
    extract_single_member_zip,
    fetch_latest_manifest,
)
from hello_gdelt.gdelt.schema import DelimitedValidation, validate_tsv_file

Gate = Literal["GO", "NO_GO"]


@dataclass(frozen=True, slots=True)
class DatasetSampleResult:
    dataset: str
    source_timestamp: str
    archive_path: str
    extracted_path: str
    downloaded_bytes: int
    archive_md5: str
    archive_sha256: str
    archive_reused: bool
    sampled_rows: int
    minimum_columns: int
    maximum_columns: int
    malformed_rows: int
    parquet_path: str
    parquet_rows: int
    duckdb_rows: int


@dataclass(frozen=True, slots=True)
class GdeltSampleReport:
    generated_at_utc: str
    gate: Gate
    source_timestamp: str
    datasets: tuple[DatasetSampleResult, ...]
    manifest_url: str | None = None
    transport_security: Literal["HTTPS", "HTTP_FALLBACK", "UNKNOWN"] = "UNKNOWN"
    failure: str | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    def to_markdown(self) -> str:
        lines = [
            "# M1 GDELT 真实样本闭环报告",
            "",
            f"生成时间（UTC）：`{self.generated_at_utc}`",
            f"源时间戳：`{self.source_timestamp}`",
            f"清单地址：`{self.manifest_url or 'UNKNOWN'}`",
            f"传输安全：**{self.transport_security}**",
            f"门禁：**{self.gate}**",
            "",
            "| 数据集 | 下载字节 | 抽样行 | 字段范围 | 坏行 | Parquet 行 | DuckDB 行 |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
        for item in self.datasets:
            lines.append(
                f"| {item.dataset} | {item.downloaded_bytes} | {item.sampled_rows} | "
                f"{item.minimum_columns}–{item.maximum_columns} | {item.malformed_rows} | "
                f"{item.parquet_rows} | {item.duckdb_rows} |"
            )
        if self.failure:
            lines.extend(["", "## 失败", "", f"`{self.failure}`"])
        lines.extend(
            [
                "",
                "> GO 只表示一个最新 15 分钟三表样本完成下载、校验、Parquet 与 DuckDB 闭环；不表示历史回填、市场数据或研究假设已经完成。",
            ]
        )
        return "\n".join(lines) + "\n"


def _load_duckdb() -> Any:
    try:
        import duckdb
    except ImportError as exc:
        raise RuntimeError(
            "DuckDB is required for M1 sample validation; install with pip install -e '.[data]'"
        ) from exc
    return duckdb


def _duckdb_row_count(parquet_path: Path) -> int:
    duckdb = _load_duckdb()
    connection = duckdb.connect(database=":memory:")
    try:
        row = connection.execute(
            "SELECT count(*) FROM read_parquet(?)",
            [str(parquet_path)],
        ).fetchone()
        if row is None:
            raise RuntimeError(f"DuckDB returned no count for {parquet_path}")
        return int(row[0])
    finally:
        connection.close()


def _dataset_result(
    dataset: str,
    validation: DelimitedValidation,
    bronze: BronzeReceipt,
    archive_path: Path,
    extracted_path: Path,
    downloaded_bytes: int,
    archive_md5: str,
    archive_sha256: str,
    archive_reused: bool,
) -> DatasetSampleResult:
    duckdb_rows = _duckdb_row_count(Path(bronze.parquet_path))
    if duckdb_rows != bronze.row_count:
        raise RuntimeError(
            f"DuckDB/Parquet row mismatch for {dataset}: "
            f"duckdb={duckdb_rows}, bronze={bronze.row_count}"
        )
    return DatasetSampleResult(
        dataset=dataset,
        source_timestamp=bronze.source_timestamp,
        archive_path=str(archive_path.resolve()),
        extracted_path=str(extracted_path.resolve()),
        downloaded_bytes=downloaded_bytes,
        archive_md5=archive_md5,
        archive_sha256=archive_sha256,
        archive_reused=archive_reused,
        sampled_rows=validation.row_count,
        minimum_columns=validation.minimum_columns,
        maximum_columns=validation.maximum_columns,
        malformed_rows=validation.malformed_rows,
        parquet_path=bronze.parquet_path,
        parquet_rows=bronze.row_count,
        duckdb_rows=duckdb_rows,
    )


def _begin_or_recover_attempt(store: ManifestStore, source_url: str) -> bool:
    record = store.get(source_url)
    if record is None:
        raise RuntimeError(f"artifact was not registered: {source_url}")
    if record.status == "BRONZE_READY":
        return True
    if record.status not in {"DISCOVERED", "FAILED"}:
        store.transition(
            source_url,
            "FAILED",
            error=f"recovering incomplete prior state: {record.status}",
        )
    store.transition(source_url, "DOWNLOADING")
    return False


def run_gdelt_latest_sample(
    root: Path,
    *,
    limits: ResourceLimits | None = None,
    sample_rows: int = 10_000,
    user_agent: str = "hello-gdelt/0.1 research-validation",
    allow_insecure_http: bool = False,
) -> GdeltSampleReport:
    limits = limits or ResourceLimits()
    paths = Paths.from_root(root)
    paths.ensure_runtime_dirs()
    generated_at = datetime.now(UTC).isoformat()
    source_timestamp = "UNKNOWN"
    manifest_url: str | None = None
    transport_security: Literal["HTTPS", "HTTP_FALLBACK", "UNKNOWN"] = "UNKNOWN"
    results: list[DatasetSampleResult] = []
    try:
        with httpx.Client(headers={"User-Agent": user_agent}) as client:
            try:
                artifacts = fetch_latest_manifest(client, limits=limits)
                manifest_url = "https://data.gdeltproject.org/gdeltv2/lastupdate.txt"
                transport_security = "HTTPS"
            except httpx.TransportError:
                if not allow_insecure_http:
                    raise
                manifest_url = "http://data.gdeltproject.org/gdeltv2/lastupdate.txt"
                artifacts = fetch_latest_manifest(
                    client,
                    limits=limits,
                    url=manifest_url,
                )
                transport_security = "HTTP_FALLBACK"
            total_download_bytes = sum(artifact.size_bytes for artifact in artifacts)
            if total_download_bytes > limits.max_download_bytes:
                raise RuntimeError(
                    "aligned GDELT trio exceeds configured total download limit: "
                    f"total={total_download_bytes}, limit={limits.max_download_bytes}"
                )
            free_bytes = shutil.disk_usage(paths.root).free
            if free_bytes < limits.min_free_disk_bytes:
                raise RuntimeError(
                    f"free disk below gate: free={free_bytes}, "
                    f"required={limits.min_free_disk_bytes}"
                )
            source_timestamp = artifacts[0].timestamp
            raw_root = paths.data / "raw" / "gdelt" / "v2" / source_timestamp
            archive_dir = raw_root / "archives"
            extracted_dir = raw_root / "extracted"
            control_path = paths.data / "control" / "hello_gdelt.sqlite3"
            with ManifestStore(control_path) as store:
                store.register(artifacts)
                for artifact in artifacts:
                    already_ready = _begin_or_recover_attempt(store, artifact.url)
                    try:
                        receipt = download_artifact(
                            client,
                            artifact,
                            archive_dir,
                            limits=limits,
                        )
                        if not already_ready:
                            store.transition(
                                artifact.url,
                                "VERIFIED",
                                local_archive_path=receipt.path,
                                actual_sha256=receipt.sha256,
                            )
                        extracted = extract_single_member_zip(
                            receipt.path,
                            extracted_dir,
                            max_uncompressed_bytes=min(
                                max(limits.max_download_bytes * 20, 1),
                                10_000_000_000,
                            ),
                        )
                        if not already_ready:
                            store.transition(
                                artifact.url,
                                "EXTRACTED",
                                local_extracted_path=extracted,
                            )
                        validation = validate_tsv_file(
                            artifact.dataset,
                            extracted,
                            max_rows=sample_rows,
                        )
                        if not validation.passed:
                            raise RuntimeError(
                                f"GDELT {artifact.dataset} schema sample failed: {validation}"
                            )
                        bronze = write_bronze_parquet(
                            extracted,
                            paths.data,
                            artifact,
                        )
                        if not already_ready:
                            store.transition(
                                artifact.url,
                                "BRONZE_READY",
                                bronze_path=Path(bronze.parquet_path),
                            )
                        results.append(
                            _dataset_result(
                                artifact.dataset,
                                validation,
                                bronze,
                                receipt.path,
                                extracted,
                                receipt.size_bytes,
                                receipt.md5,
                                receipt.sha256,
                                receipt.reused,
                            )
                        )
                    except Exception as artifact_error:
                        record = store.get(artifact.url)
                        if record is not None and record.status not in {"FAILED", "BRONZE_READY"}:
                            store.transition(
                                artifact.url,
                                "FAILED",
                                error=f"{type(artifact_error).__name__}: {artifact_error}",
                            )
                        raise
        return GdeltSampleReport(
            generated_at_utc=generated_at,
            gate="GO",
            source_timestamp=source_timestamp,
            datasets=tuple(results),
            manifest_url=manifest_url,
            transport_security=transport_security,
        )
    except Exception as exc:
        return GdeltSampleReport(
            generated_at_utc=generated_at,
            gate="NO_GO",
            source_timestamp=source_timestamp,
            datasets=tuple(results),
            manifest_url=manifest_url,
            transport_security=transport_security,
            failure=f"{type(exc).__name__}: {exc}",
        )


def write_gdelt_sample_report(
    report: GdeltSampleReport,
    reports_dir: Path,
) -> tuple[Path, Path]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    json_path = reports_dir / "m1_gdelt_sample_report.json"
    markdown_path = reports_dir / "m1_gdelt_sample_report.md"
    json_path.write_text(report.to_json() + "\n", encoding="utf-8")
    markdown_path.write_text(report.to_markdown(), encoding="utf-8")
    return json_path, markdown_path
