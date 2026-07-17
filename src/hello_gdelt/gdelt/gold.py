from __future__ import annotations

import json
import math
import os
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hello_gdelt.gdelt.bronze import ColumnarDependencyError
from hello_gdelt.gdelt.silver import SilverReceipt

_REQUIRED_DATASETS = frozenset({"events", "mentions", "gkg"})


class GoldAggregationError(RuntimeError):
    """Raised when aligned Silver inputs cannot form a trustworthy Gold interval."""


@dataclass(frozen=True, slots=True)
class GoldReceipt:
    source_timestamp: str
    input_silver_paths: tuple[str, ...]
    gold_path: str
    manifest_path: str
    schema_version: str
    row_count: int
    gkg_invalid_tone_rows: int
    gkg_missing_source_rows: int
    aggregated_at_utc: str


def _load_polars() -> Any:
    try:
        import polars as pl
    except ImportError as exc:
        raise ColumnarDependencyError(
            "Polars is required for Gold aggregation; install with pip install -e '.[data]'"
        ) from exc
    return pl


def gold_interval_path(root: Path, timestamp: str) -> Path:
    if len(timestamp) != 14 or not timestamp.isdigit():
        raise ValueError(f"invalid GDELT timestamp: {timestamp!r}")
    year, month, day, hour = timestamp[:4], timestamp[4:6], timestamp[6:8], timestamp[8:10]
    return (
        root
        / "gold"
        / "gdelt"
        / "news_interval"
        / f"year={year}"
        / f"month={month}"
        / f"day={day}"
        / f"hour={hour}"
        / f"part-{timestamp}.parquet"
    )


def _scalar(frame: Any, expression: Any) -> Any:
    return frame.select(expression.alias("value")).item()


def _float_or_none(value: Any) -> float | None:
    return None if value is None else float(value)


def _source_entropy(frame: Any, source_column: str) -> tuple[float | None, int, int]:
    total_rows = frame.height
    if total_rows == 0:
        return None, 0, 0
    raw_values = frame[source_column].to_list()
    missing_rows = sum(value is None for value in raw_values)
    counts = Counter(
        "__MISSING_SOURCE__" if value is None else str(value)
        for value in raw_values
    )
    entropy = -sum(
        (count / total_rows) * math.log(count / total_rows)
        for count in counts.values()
        if count > 0
    )
    return entropy, len(counts), missing_rows


def build_news_interval_gold(
    silver_receipts: tuple[SilverReceipt, ...],
    root: Path,
    *,
    schema_version: str = "gdelt-news-interval-v1",
    overwrite: bool = False,
) -> GoldReceipt:
    """Build one aligned 15-minute news feature row from Events, Mentions and GKG."""

    if len(silver_receipts) != 3:
        raise GoldAggregationError(
            f"expected exactly 3 Silver receipts, got {len(silver_receipts)}"
        )
    by_dataset = {receipt.dataset: receipt for receipt in silver_receipts}
    if set(by_dataset) != _REQUIRED_DATASETS:
        raise GoldAggregationError(
            f"Silver dataset set mismatch: actual={sorted(by_dataset)}, "
            f"expected={sorted(_REQUIRED_DATASETS)}"
        )
    timestamps = {receipt.source_timestamp for receipt in silver_receipts}
    if len(timestamps) != 1:
        raise GoldAggregationError(f"Silver inputs are not aligned: {sorted(timestamps)}")
    timestamp = next(iter(timestamps))
    target = gold_interval_path(root, timestamp)
    manifest = target.with_suffix(".manifest.json")
    if target.exists() and not overwrite:
        if manifest.exists():
            stored = GoldReceipt(**json.loads(manifest.read_text(encoding="utf-8")))
            if stored.source_timestamp == timestamp and Path(stored.gold_path).is_file():
                return stored
        raise FileExistsError(target)

    pl = _load_polars()
    events = pl.read_parquet(by_dataset["events"].silver_path)
    mentions = pl.read_parquet(by_dataset["mentions"].silver_path)
    gkg = pl.read_parquet(by_dataset["gkg"].silver_path)
    for dataset, frame in (("events", events), ("mentions", mentions), ("gkg", gkg)):
        receipt = by_dataset[dataset]
        if frame.height != receipt.row_count:
            raise GoldAggregationError(
                f"Silver row drift for {dataset}: file={frame.height}, receipt={receipt.row_count}"
            )
        observed_timestamps = frame["_source_timestamp"].drop_nulls().unique().to_list()
        if observed_timestamps != [timestamp]:
            raise GoldAggregationError(
                f"Silver lineage timestamp drift for {dataset}: {observed_timestamps}"
            )

    tone_text = pl.col("v1_5_tone")
    gkg_tone = (
        tone_text.str.split(",")
        .list.get(0, null_on_oob=True)
        .cast(pl.Float64, strict=False)
    )
    gkg = gkg.with_columns(gkg_tone.alias("_document_tone"))
    gkg_invalid_tone_rows = int(
        _scalar(
            gkg,
            (pl.col("v1_5_tone").is_not_null() & pl.col("_document_tone").is_null()).sum(),
        )
    )
    if gkg.height > 0 and gkg_invalid_tone_rows / gkg.height > 0.01:
        raise GoldAggregationError(
            f"GKG tone parse failure exceeds 1%: {gkg_invalid_tone_rows}/{gkg.height}"
        )

    source_entropy, source_categories, gkg_missing_source_rows = _source_entropy(
        gkg,
        "v2_source_common_name",
    )
    interval_start_utc = datetime.strptime(timestamp, "%Y%m%d%H%M%S").replace(
        tzinfo=UTC
    ).isoformat()
    aggregated_at = datetime.now(UTC).isoformat()
    row = {
        "source_timestamp": timestamp,
        "interval_start_utc": interval_start_utc,
        "event_count": events.height,
        "root_event_count": int(_scalar(events, pl.col("is_root_event").eq(1).sum())),
        "event_unique_ids": int(_scalar(events, pl.col("global_event_id").n_unique())),
        "event_num_mentions_sum": int(
            _scalar(events, pl.col("num_mentions").fill_null(0).sum())
        ),
        "event_num_sources_sum": int(
            _scalar(events, pl.col("num_sources").fill_null(0).sum())
        ),
        "event_num_articles_sum": int(
            _scalar(events, pl.col("num_articles").fill_null(0).sum())
        ),
        "event_goldstein_mean": _float_or_none(
            _scalar(events, pl.col("goldstein_scale").mean())
        ),
        "event_avg_tone_mean": _float_or_none(_scalar(events, pl.col("avg_tone").mean())),
        "event_quad4_share": _float_or_none(
            _scalar(events, pl.col("quad_class").eq(4).mean())
        ),
        "mention_count": mentions.height,
        "mention_unique_events": int(
            _scalar(mentions, pl.col("global_event_id").n_unique())
        ),
        "mention_unique_sources": int(
            _scalar(mentions, pl.col("mention_source_name").drop_nulls().n_unique())
        ),
        "mention_doc_tone_mean": _float_or_none(
            _scalar(mentions, pl.col("mention_doc_tone").mean())
        ),
        "gkg_record_count": gkg.height,
        "gkg_unique_documents": int(
            _scalar(gkg, pl.col("v2_document_identifier").n_unique())
        ),
        "gkg_source_categories": source_categories,
        "gkg_source_entropy": source_entropy,
        "gkg_missing_source_rows": gkg_missing_source_rows,
        "gkg_tone_valid_rows": int(
            _scalar(gkg, pl.col("_document_tone").is_not_null().sum())
        ),
        "gkg_invalid_tone_rows": gkg_invalid_tone_rows,
        "gkg_tone_mean": _float_or_none(_scalar(gkg, pl.col("_document_tone").mean())),
        "gkg_tone_std": _float_or_none(_scalar(gkg, pl.col("_document_tone").std())),
        "gkg_negative_tone_share": _float_or_none(
            _scalar(gkg, pl.col("_document_tone").lt(0).mean())
        ),
        "gkg_positive_tone_share": _float_or_none(
            _scalar(gkg, pl.col("_document_tone").gt(0).mean())
        ),
        "_gold_schema_version": schema_version,
        "_aggregated_at_utc": aggregated_at,
    }
    output = pl.DataFrame([row])
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(f".{target.name}.part")
    manifest_part = manifest.with_name(f".{manifest.name}.part")
    part.unlink(missing_ok=True)
    manifest_part.unlink(missing_ok=True)
    try:
        output.write_parquet(
            part,
            compression="zstd",
            compression_level=6,
            statistics=True,
        )
        receipt = GoldReceipt(
            source_timestamp=timestamp,
            input_silver_paths=tuple(
                by_dataset[dataset].silver_path for dataset in sorted(by_dataset)
            ),
            gold_path=str(target.resolve()),
            manifest_path=str(manifest.resolve()),
            schema_version=schema_version,
            row_count=output.height,
            gkg_invalid_tone_rows=gkg_invalid_tone_rows,
            gkg_missing_source_rows=gkg_missing_source_rows,
            aggregated_at_utc=aggregated_at,
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
