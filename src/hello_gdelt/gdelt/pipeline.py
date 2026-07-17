from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import httpx

from hello_gdelt.config import Paths, ResourceLimits
from hello_gdelt.control.manifest import ManifestStore
from hello_gdelt.gdelt.bronze import BronzeReceipt, write_bronze_parquet
from hello_gdelt.gdelt.download import (
    DownloadReceipt,
    download_artifact,
    extract_single_member_zip,
)
from hello_gdelt.gdelt.gold import GoldReceipt, build_news_interval_gold
from hello_gdelt.gdelt.lastupdate import GdeltArtifact
from hello_gdelt.gdelt.masterfile import GdeltArtifactTrio
from hello_gdelt.gdelt.schema import DelimitedValidation, validate_tsv_file
from hello_gdelt.gdelt.silver import SilverReceipt, project_bronze_to_silver


class GdeltPipelineError(RuntimeError):
    """Raised when an aligned GDELT trio cannot pass the columnar data pipeline."""


@dataclass(frozen=True, slots=True)
class ProcessedGdeltDataset:
    artifact: GdeltArtifact
    download: DownloadReceipt
    extracted_path: str
    validation: DelimitedValidation
    bronze: BronzeReceipt
    silver: SilverReceipt


@dataclass(frozen=True, slots=True)
class ProcessedGdeltTrio:
    source_timestamp: str
    datasets: tuple[ProcessedGdeltDataset, ...]
    gold: GoldReceipt


def _begin_or_recover_attempt(store: ManifestStore, source_url: str) -> bool:
    record = store.get(source_url)
    if record is None:
        raise GdeltPipelineError(f"artifact was not registered: {source_url}")
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


def _mark_failed(
    store: ManifestStore,
    artifact: GdeltArtifact,
    error: Exception,
) -> None:
    record = store.get(artifact.url)
    if record is None or record.status in {"FAILED", "BRONZE_READY"}:
        return
    store.transition(
        artifact.url,
        "FAILED",
        error=f"{type(error).__name__}: {error}",
    )


def process_gdelt_trio(
    client: httpx.Client,
    trio: GdeltArtifactTrio,
    paths: Paths,
    store: ManifestStore,
    *,
    limits: ResourceLimits,
    sample_rows: int = 10_000,
    allow_insecure_http: bool = False,
) -> ProcessedGdeltTrio:
    """Process one aligned trio through verified raw, Bronze, Silver and Gold.

    The GDELT historical catalogue currently enumerates HTTP artifact URLs. Such
    artifacts are rejected unless the caller explicitly opts in; byte count, MD5,
    SHA-256 and ZIP CRC then remain mandatory but do not authenticate the publisher.
    """

    if sample_rows <= 0:
        raise ValueError("sample_rows must be positive")
    if len(trio.artifacts) != 3:
        raise GdeltPipelineError(
            f"expected exactly three artifacts, got {len(trio.artifacts)}"
        )
    if {artifact.dataset for artifact in trio.artifacts} != {
        "events",
        "mentions",
        "gkg",
    }:
        raise GdeltPipelineError("trio does not contain Events, Mentions and GKG")
    if {artifact.timestamp for artifact in trio.artifacts} != {trio.timestamp}:
        raise GdeltPipelineError("trio artifact timestamps are not aligned")
    for artifact in trio.artifacts:
        if httpx.URL(artifact.url).scheme == "http" and not allow_insecure_http:
            raise GdeltPipelineError(
                "historical artifact uses unauthenticated HTTP; pass explicit opt-in"
            )
    if sum(artifact.size_bytes for artifact in trio.artifacts) > limits.max_download_bytes:
        raise GdeltPipelineError(
            "aligned trio exceeds configured total download byte limit"
        )

    paths.ensure_runtime_dirs()
    raw_root = paths.data / "raw" / "gdelt" / "v2" / trio.timestamp
    archive_dir = raw_root / "archives"
    extracted_dir = raw_root / "extracted"
    store.register(trio.artifacts)
    processed: list[ProcessedGdeltDataset] = []
    silver_receipts: list[SilverReceipt] = []
    for artifact in trio.artifacts:
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
                raise GdeltPipelineError(
                    f"{artifact.dataset} field-width validation failed: {validation}"
                )
            bronze = write_bronze_parquet(
                extracted,
                paths.data,
                artifact,
            )
            silver = project_bronze_to_silver(
                bronze,
                paths.data,
            )
            if not already_ready:
                store.transition(
                    artifact.url,
                    "BRONZE_READY",
                    bronze_path=Path(bronze.parquet_path),
                )
            silver_receipts.append(silver)
            processed.append(
                ProcessedGdeltDataset(
                    artifact=artifact,
                    download=receipt,
                    extracted_path=str(extracted.resolve()),
                    validation=validation,
                    bronze=bronze,
                    silver=silver,
                )
            )
        except Exception as exc:
            _mark_failed(store, artifact, exc)
            raise
    gold = build_news_interval_gold(
        tuple(silver_receipts),
        paths.data,
    )
    return ProcessedGdeltTrio(
        source_timestamp=trio.timestamp,
        datasets=tuple(processed),
        gold=gold,
    )
