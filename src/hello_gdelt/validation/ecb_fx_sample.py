from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import httpx

from hello_gdelt.config import Paths
from hello_gdelt.markets.ecb_fx import (
    EcbFxReceipt,
    derive_fx_pairs,
    fetch_ecb_exr_csv,
    parse_ecb_exr_csv,
    required_ecb_currencies,
    write_ecb_fx_parquet,
)

Gate = Literal["GO", "NO_GO"]


@dataclass(frozen=True, slots=True)
class LatestFxValue:
    pair: str
    observation_date: str
    quote_per_base: float


@dataclass(frozen=True, slots=True)
class EcbFxSampleReport:
    generated_at_utc: str
    gate: Gate
    requested_start_date: str
    requested_end_date: str
    request_url: str | None
    response_sha256: str | None
    raw_csv_path: str | None
    raw_observation_count: int
    complete_pair_dates: int
    pair_observation_count: int
    parquet_path: str | None
    duckdb_rows: int
    latest_values: tuple[LatestFxValue, ...]
    failure: str | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    def to_markdown(self) -> str:
        lines = [
            "# ECB 外汇参考汇率真实样本报告",
            "",
            f"生成时间（UTC）：`{self.generated_at_utc}`",
            f"请求区间：`{self.requested_start_date}` 至 `{self.requested_end_date}`",
            f"门禁：**{self.gate}**",
            f"请求地址：`{self.request_url or 'UNKNOWN'}`",
            f"响应 SHA-256：`{self.response_sha256 or 'UNKNOWN'}`",
            "",
            "| 指标 | 数值 |",
            "|---|---:|",
            f"| ECB 原始观测 | {self.raw_observation_count} |",
            f"| 完整交易日期 | {self.complete_pair_dates} |",
            f"| 派生货币对观测 | {self.pair_observation_count} |",
            f"| DuckDB 行数 | {self.duckdb_rows} |",
            "",
            "## 最新完整日期",
            "",
            "| 货币对 | 日期 | quote per base |",
            "|---|---|---:|",
        ]
        for item in self.latest_values:
            lines.append(
                f"| {item.pair} | {item.observation_date} | {item.quote_per_base:.10g} |"
            )
        if self.failure:
            lines.extend(["", "## 失败", "", f"`{self.failure}`"])
        lines.extend(
            [
                "",
                "> ECB 数据是每日信息性参考汇率，不是可成交 OTC 报价；该门禁只验证正式日频外汇研究的数据源与代数转换。",
            ]
        )
        return "\n".join(lines) + "\n"


def _load_duckdb() -> Any:
    try:
        import duckdb
    except ImportError as exc:
        raise RuntimeError(
            "DuckDB is required for ECB sample validation; install with pip install -e '.[data]'"
        ) from exc
    return duckdb


def _duckdb_row_count(path: Path) -> int:
    duckdb = _load_duckdb()
    connection = duckdb.connect(database=":memory:")
    try:
        row = connection.execute(
            "SELECT count(*) FROM read_parquet(?)",
            [str(path)],
        ).fetchone()
        if row is None:
            raise RuntimeError(f"DuckDB returned no row count for {path}")
        return int(row[0])
    finally:
        connection.close()


def _persist_raw_csv(
    paths: Paths,
    *,
    text: str,
    response_sha256: str,
    start_date: date,
    end_date: date,
) -> Path:
    target = (
        paths.data
        / "raw"
        / "markets"
        / "ecb_exr"
        / f"exr-{start_date.isoformat()}-{end_date.isoformat()}-{response_sha256[:12]}.csv"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        return target
    part = target.with_name(f".{target.name}.part")
    part.unlink(missing_ok=True)
    try:
        part.write_text(text, encoding="utf-8")
        os.replace(part, target)
        return target
    except Exception:
        part.unlink(missing_ok=True)
        raise


def run_ecb_fx_sample(
    root: Path,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    lookback_days: int = 45,
    user_agent: str = "hello-gdelt/0.1 ECB-EXR-research-validation",
) -> EcbFxSampleReport:
    if lookback_days < 7 or lookback_days > 366:
        raise ValueError("lookback_days must be between 7 and 366")
    requested_end = end_date or (datetime.now(UTC).date() - timedelta(days=1))
    requested_start = start_date or (requested_end - timedelta(days=lookback_days))
    if requested_start > requested_end:
        raise ValueError("start_date must be <= end_date")
    generated_at = datetime.now(UTC).isoformat()
    paths = Paths.from_root(root)
    paths.ensure_runtime_dirs()
    request_url: str | None = None
    response_sha256: str | None = None
    raw_path: Path | None = None
    raw_count = 0
    pair_count = 0
    complete_dates = 0
    parquet_path: str | None = None
    duckdb_rows = 0
    latest_values: tuple[LatestFxValue, ...] = ()
    try:
        currencies = required_ecb_currencies()
        with httpx.Client(headers={"User-Agent": user_agent}) as client:
            text, request_url, response_sha256 = fetch_ecb_exr_csv(
                client,
                currencies=currencies,
                start_date=requested_start,
                end_date=requested_end,
            )
        raw_path = _persist_raw_csv(
            paths,
            text=text,
            response_sha256=response_sha256,
            start_date=requested_start,
            end_date=requested_end,
        )
        observations = parse_ecb_exr_csv(text, expected_currencies=currencies)
        pairs = derive_fx_pairs(observations)
        raw_count = len(observations)
        pair_count = len(pairs)
        pair_names = {item.pair for item in pairs}
        complete_dates = len({item.observation_date for item in pairs})
        if pair_count != complete_dates * len(pair_names):
            raise RuntimeError(
                f"FX panel is not rectangular: rows={pair_count}, "
                f"dates={complete_dates}, pairs={len(pair_names)}"
            )
        receipt: EcbFxReceipt = write_ecb_fx_parquet(
            pairs,
            paths.data,
            request_url=request_url,
            response_sha256=response_sha256,
            currencies=currencies,
            raw_observation_count=raw_count,
        )
        parquet_path = receipt.parquet_path
        duckdb_rows = _duckdb_row_count(Path(receipt.parquet_path))
        if duckdb_rows != pair_count:
            raise RuntimeError(
                f"ECB Parquet/DuckDB row mismatch: pairs={pair_count}, duckdb={duckdb_rows}"
            )
        latest_date = max(item.observation_date for item in pairs)
        latest_values = tuple(
            LatestFxValue(
                pair=item.pair,
                observation_date=item.observation_date.isoformat(),
                quote_per_base=item.quote_per_base,
            )
            for item in pairs
            if item.observation_date == latest_date
        )
        return EcbFxSampleReport(
            generated_at_utc=generated_at,
            gate="GO",
            requested_start_date=requested_start.isoformat(),
            requested_end_date=requested_end.isoformat(),
            request_url=request_url,
            response_sha256=response_sha256,
            raw_csv_path=str(raw_path.resolve()),
            raw_observation_count=raw_count,
            complete_pair_dates=complete_dates,
            pair_observation_count=pair_count,
            parquet_path=parquet_path,
            duckdb_rows=duckdb_rows,
            latest_values=latest_values,
        )
    except Exception as exc:
        return EcbFxSampleReport(
            generated_at_utc=generated_at,
            gate="NO_GO",
            requested_start_date=requested_start.isoformat(),
            requested_end_date=requested_end.isoformat(),
            request_url=request_url,
            response_sha256=response_sha256,
            raw_csv_path=None if raw_path is None else str(raw_path.resolve()),
            raw_observation_count=raw_count,
            complete_pair_dates=complete_dates,
            pair_observation_count=pair_count,
            parquet_path=parquet_path,
            duckdb_rows=duckdb_rows,
            latest_values=latest_values,
            failure=f"{type(exc).__name__}: {exc}",
        )


def write_ecb_fx_sample_report(
    report: EcbFxSampleReport,
    reports_dir: Path,
) -> tuple[Path, Path]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    json_path = reports_dir / "market_ecb_fx_sample_report.json"
    markdown_path = reports_dir / "market_ecb_fx_sample_report.md"
    json_path.write_text(report.to_json() + "\n", encoding="utf-8")
    markdown_path.write_text(report.to_markdown(), encoding="utf-8")
    return json_path, markdown_path
