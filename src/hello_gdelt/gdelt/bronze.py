from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hello_gdelt.gdelt.lastupdate import GdeltArtifact
from hello_gdelt.gdelt.schema import CONTRACTS


class ColumnarDependencyError(RuntimeError):
    """Raised when the optional columnar stack is unavailable."""


@dataclass(frozen=True, slots=True)
class BronzeReceipt:
    dataset: str
    source_path: str
    parquet_path: str
    manifest_path: str
    source_url: str
    source_timestamp: str
    source_md5: str
    schema_version: str
    row_count: int
    column_count: int
    ingested_at_utc: str


def raw_column_names(dataset: str) -> tuple[str, ...]:
    contract = CONTRACTS.get(dataset)
    if contract is None:
        raise KeyError(f"unknown dataset contract: {dataset}")
    return tuple(
        f"gdelt_{dataset}_raw_{index:03d}"
        for index in range(1, contract.expected_columns + 1)
    )


def bronze_partition_path(root: Path, artifact: GdeltArtifact) -> Path:
    timestamp = artifact.timestamp
    if len(timestamp) != 14 or not timestamp.isdigit():
        raise ValueError(f"invalid GDELT timestamp: {timestamp!r}")
    year, month, day, hour = timestamp[:4], timestamp[4:6], timestamp[6:8], timestamp[8:10]
    return (
        root
        / "bronze"
        / "gdelt"
        / artifact.dataset
        / f"year={year}"
        / f"month={month}"
        / f"day={day}"
        / f"hour={hour}"
        / f"part-{timestamp}.parquet"
    )


def _load_polars() -> Any:
    try:
        import polars as pl
    except ImportError as exc:
        raise ColumnarDependencyError(
            "Polars is required for Bronze conversion; install with pip install -e '.[data]'"
        ) from exc
    return pl


def write_bronze_parquet(
    raw_tsv_path: Path,
    root: Path,
    artifact: GdeltArtifact,
    *,
    schema_version: str = "gdelt-v2-raw-width-v1",
    overwrite: bool = False,
) -> BronzeReceipt:
    """Convert one verified, extracted GDELT TSV to an atomic all-string Bronze Parquet."""

    if not raw_tsv_path.is_file():
        raise FileNotFoundError(raw_tsv_path)
    pl = _load_polars()
    names = raw_column_names(artifact.dataset)
    target = bronze_partition_path(root, artifact)
    manifest = target.with_suffix(".manifest.json")
    if target.exists() and not overwrite:
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(f".{target.name}.part")
    manifest_part = manifest.with_name(f".{manifest.name}.part")
    part.unlink(missing_ok=True)
    manifest_part.unlink(missing_ok=True)

    ingested_at = datetime.now(UTC).isoformat()
    schema_overrides = {name: pl.String for name in names}
    try:
        frame = pl.read_csv(
            raw_tsv_path,
            separator="\t",
            has_header=False,
            new_columns=list(names),
            schema_overrides=schema_overrides,
            quote_char=None,
            null_values="",
            encoding="utf8-lossy",
            infer_schema=False,
            ignore_errors=False,
            truncate_ragged_lines=False,
        )
        if frame.height <= 0:
            raise ValueError(f"Bronze source contains no rows: {raw_tsv_path}")
        if frame.width != len(names):
            raise ValueError(
                f"Bronze width mismatch: actual={frame.width}, expected={len(names)}"
            )
        frame = frame.with_columns(
            pl.lit(artifact.url).alias("_source_url"),
            pl.lit(artifact.timestamp).alias("_source_timestamp"),
            pl.lit(artifact.md5).alias("_source_md5"),
            pl.lit(schema_version).alias("_schema_version"),
            pl.lit(ingested_at).alias("_ingested_at_utc"),
        )
        frame.write_parquet(
            part,
            compression="zstd",
            compression_level=6,
            statistics=True,
        )
        receipt = BronzeReceipt(
            dataset=artifact.dataset,
            source_path=str(raw_tsv_path.resolve()),
            parquet_path=str(target.resolve()),
            manifest_path=str(manifest.resolve()),
            source_url=artifact.url,
            source_timestamp=artifact.timestamp,
            source_md5=artifact.md5,
            schema_version=schema_version,
            row_count=frame.height,
            column_count=frame.width,
            ingested_at_utc=ingested_at,
        )
        manifest_part.write_text(
            json.dumps(asdict(receipt), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(part, target)
        os.replace(manifest_part, manifest)
        return receipt
    except Exception:
        part.unlink(missing_ok=True)
        manifest_part.unlink(missing_ok=True)
        raise
