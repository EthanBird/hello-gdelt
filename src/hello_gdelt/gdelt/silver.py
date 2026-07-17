from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hello_gdelt.gdelt.bronze import BronzeReceipt, ColumnarDependencyError, raw_column_names
from hello_gdelt.gdelt.fields import semantic_column_names

_CAST_SPECS: dict[str, dict[str, str]] = {
    "events": {
        "global_event_id": "Int64",
        "sql_date": "Int32",
        "month_year": "Int32",
        "year": "Int16",
        "fraction_date": "Float64",
        "is_root_event": "Int8",
        "quad_class": "Int8",
        "goldstein_scale": "Float64",
        "num_mentions": "Int32",
        "num_sources": "Int32",
        "num_articles": "Int32",
        "avg_tone": "Float64",
        "actor1_geo_type": "Int8",
        "actor1_geo_lat": "Float64",
        "actor1_geo_long": "Float64",
        "actor2_geo_type": "Int8",
        "actor2_geo_lat": "Float64",
        "actor2_geo_long": "Float64",
        "action_geo_type": "Int8",
        "action_geo_lat": "Float64",
        "action_geo_long": "Float64",
        "date_added": "Int64",
    },
    "mentions": {
        "global_event_id": "Int64",
        "event_time_date": "Int64",
        "mention_time_date": "Int64",
        "mention_type": "Int16",
        "sentence_id": "Int32",
        "actor1_char_offset": "Int32",
        "actor2_char_offset": "Int32",
        "action_char_offset": "Int32",
        "in_raw_text": "Int8",
        "confidence": "Int16",
        "mention_doc_len": "Int32",
        "mention_doc_tone": "Float64",
    },
    "gkg": {
        "v2_1_date": "Int64",
        "v2_source_collection_identifier": "Int16",
    },
}

_CRITICAL_FIELDS: dict[str, tuple[str, ...]] = {
    "events": ("global_event_id", "sql_date", "date_added", "source_url"),
    "mentions": ("global_event_id", "mention_time_date", "mention_identifier"),
    "gkg": ("gkg_record_id", "v2_1_date", "v2_document_identifier"),
}

_METADATA_COLUMNS = (
    "_source_url",
    "_source_timestamp",
    "_source_md5",
    "_schema_version",
    "_ingested_at_utc",
)


class SilverProjectionError(RuntimeError):
    """Raised when semantic projection or typed conversion violates the contract."""


@dataclass(frozen=True, slots=True)
class SilverReceipt:
    dataset: str
    source_timestamp: str
    bronze_path: str
    silver_path: str
    manifest_path: str
    schema_version: str
    row_count: int
    column_count: int
    invalid_casts: tuple[tuple[str, int], ...]
    critical_nulls: tuple[tuple[str, int], ...]
    projected_at_utc: str


def _load_polars() -> Any:
    try:
        import polars as pl
    except ImportError as exc:
        raise ColumnarDependencyError(
            "Polars is required for Silver projection; install with pip install -e '.[data]'"
        ) from exc
    return pl


def silver_partition_path(root: Path, dataset: str, timestamp: str) -> Path:
    if len(timestamp) != 14 or not timestamp.isdigit():
        raise ValueError(f"invalid GDELT timestamp: {timestamp!r}")
    if dataset not in _CAST_SPECS:
        raise KeyError(f"unknown GDELT dataset: {dataset}")
    year, month, day, hour = timestamp[:4], timestamp[4:6], timestamp[6:8], timestamp[8:10]
    return (
        root
        / "silver"
        / "gdelt"
        / dataset
        / f"year={year}"
        / f"month={month}"
        / f"day={day}"
        / f"hour={hour}"
        / f"part-{timestamp}.parquet"
    )


def _dtype(pl: Any, name: str) -> Any:
    try:
        return getattr(pl, name)
    except AttributeError as exc:
        raise SilverProjectionError(f"unsupported Polars dtype in schema: {name}") from exc


def project_bronze_to_silver(
    bronze: BronzeReceipt,
    root: Path,
    *,
    schema_version: str = "gdelt-v2-semantic-v1",
    overwrite: bool = False,
) -> SilverReceipt:
    """Rename validated raw positions, cast typed fields, audit loss, and write Silver."""

    pl = _load_polars()
    bronze_path = Path(bronze.parquet_path)
    if not bronze_path.is_file():
        raise FileNotFoundError(bronze_path)
    semantic = semantic_column_names(bronze.dataset)
    raw = raw_column_names(bronze.dataset)
    target = silver_partition_path(root, bronze.dataset, bronze.source_timestamp)
    manifest = target.with_suffix(".manifest.json")
    if target.exists() and not overwrite:
        if manifest.exists():
            stored = SilverReceipt(**json.loads(manifest.read_text(encoding="utf-8")))
            if (
                stored.dataset == bronze.dataset
                and stored.source_timestamp == bronze.source_timestamp
                and Path(stored.silver_path).is_file()
            ):
                return stored
        raise FileExistsError(target)

    frame = pl.read_parquet(bronze_path)
    expected_columns = set(raw) | set(_METADATA_COLUMNS)
    actual_columns = set(frame.columns)
    missing = expected_columns - actual_columns
    unexpected = actual_columns - expected_columns
    if missing or unexpected:
        raise SilverProjectionError(
            f"Bronze column contract drift: missing={sorted(missing)}, "
            f"unexpected={sorted(unexpected)}"
        )
    if frame.height != bronze.row_count:
        raise SilverProjectionError(
            f"Bronze receipt row mismatch: file={frame.height}, receipt={bronze.row_count}"
        )

    rename_map = dict(zip(raw, semantic, strict=True))
    frame = frame.rename(rename_map)
    cast_specs = _CAST_SPECS[bronze.dataset]
    invalid_casts: list[tuple[str, int]] = []
    cast_expressions = []
    for column, dtype_name in cast_specs.items():
        dtype = _dtype(pl, dtype_name)
        converted = pl.col(column).cast(dtype, strict=False)
        invalid = frame.select(
            (pl.col(column).is_not_null() & converted.is_null()).sum().alias("invalid")
        ).item()
        invalid_casts.append((column, int(invalid)))
        cast_expressions.append(converted.alias(column))
    frame = frame.with_columns(cast_expressions)

    critical_nulls: list[tuple[str, int]] = []
    for column in _CRITICAL_FIELDS[bronze.dataset]:
        count = int(frame.select(pl.col(column).is_null().sum()).item())
        critical_nulls.append((column, count))
    failed_casts = [(name, count) for name, count in invalid_casts if count > 0]
    failed_critical = [(name, count) for name, count in critical_nulls if count > 0]
    if failed_casts or failed_critical:
        raise SilverProjectionError(
            f"semantic conversion loss: invalid_casts={failed_casts}, "
            f"critical_nulls={failed_critical}"
        )

    projected_at = datetime.now(UTC).isoformat()
    frame = frame.with_columns(
        pl.lit(schema_version).alias("_silver_schema_version"),
        pl.lit(projected_at).alias("_projected_at_utc"),
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(f".{target.name}.part")
    manifest_part = manifest.with_name(f".{manifest.name}.part")
    part.unlink(missing_ok=True)
    manifest_part.unlink(missing_ok=True)
    try:
        frame.write_parquet(
            part,
            compression="zstd",
            compression_level=6,
            statistics=True,
        )
        receipt = SilverReceipt(
            dataset=bronze.dataset,
            source_timestamp=bronze.source_timestamp,
            bronze_path=str(bronze_path.resolve()),
            silver_path=str(target.resolve()),
            manifest_path=str(manifest.resolve()),
            schema_version=schema_version,
            row_count=frame.height,
            column_count=frame.width,
            invalid_casts=tuple(invalid_casts),
            critical_nulls=tuple(critical_nulls),
            projected_at_utc=projected_at,
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
