import math
from pathlib import Path

import pytest

pl = pytest.importorskip("polars")

from hello_gdelt.gdelt.gold import GoldAggregationError, build_news_interval_gold
from hello_gdelt.gdelt.silver import SilverReceipt

TIMESTAMP = "20260717054500"


def receipt(tmp_path: Path, dataset: str, frame: object, *, timestamp: str = TIMESTAMP) -> SilverReceipt:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / f"{dataset}.parquet"
    frame.write_parquet(path)
    return SilverReceipt(
        dataset=dataset,
        source_timestamp=timestamp,
        bronze_path=str(tmp_path / f"{dataset}.bronze.parquet"),
        silver_path=str(path),
        manifest_path=str(tmp_path / f"{dataset}.manifest.json"),
        schema_version="fixture",
        row_count=frame.height,
        column_count=frame.width,
        invalid_casts=(),
        critical_nulls=(),
        projected_at_utc="2026-07-17T00:00:00+00:00",
    )


def aligned_receipts(tmp_path: Path) -> tuple[SilverReceipt, ...]:
    events = pl.DataFrame(
        {
            "_source_timestamp": [TIMESTAMP, TIMESTAMP],
            "global_event_id": [1, 2],
            "is_root_event": [1, 0],
            "num_mentions": [2, 3],
            "num_sources": [1, 2],
            "num_articles": [2, 2],
            "goldstein_scale": [3.0, -4.0],
            "avg_tone": [-1.0, 2.0],
            "quad_class": [1, 4],
        }
    )
    mentions = pl.DataFrame(
        {
            "_source_timestamp": [TIMESTAMP, TIMESTAMP, TIMESTAMP],
            "global_event_id": [1, 1, 2],
            "mention_source_name": ["source-a", "source-b", "source-a"],
            "mention_doc_tone": [-1.0, 1.0, 2.0],
        }
    )
    gkg = pl.DataFrame(
        {
            "_source_timestamp": [TIMESTAMP, TIMESTAMP],
            "v1_5_tone": ["-2.0,1,3,4,5,6,7", "1.0,3,2,1,5,6,7"],
            "v2_source_common_name": ["source-a", "source-b"],
            "v2_document_identifier": ["doc-a", "doc-b"],
        }
    )
    return (
        receipt(tmp_path, "events", events),
        receipt(tmp_path, "mentions", mentions),
        receipt(tmp_path, "gkg", gkg),
    )


def test_build_news_interval_gold(tmp_path: Path) -> None:
    gold = build_news_interval_gold(aligned_receipts(tmp_path), tmp_path / "data")
    frame = pl.read_parquet(gold.gold_path)
    assert gold.row_count == 1
    assert frame["event_count"].item() == 2
    assert frame["mention_count"].item() == 3
    assert frame["gkg_record_count"].item() == 2
    assert frame["gkg_negative_tone_share"].item() == pytest.approx(0.5)
    assert frame["gkg_source_entropy"].item() == pytest.approx(math.log(2))
    assert gold.gkg_invalid_tone_rows == 0


def test_gold_rejects_unaligned_silver_inputs(tmp_path: Path) -> None:
    receipts = list(aligned_receipts(tmp_path))
    gkg_frame = pl.read_parquet(receipts[2].silver_path)
    receipts[2] = receipt(
        tmp_path / "other",
        "gkg",
        gkg_frame,
        timestamp="20260717060000",
    )
    with pytest.raises(GoldAggregationError, match="not aligned"):
        build_news_interval_gold(tuple(receipts), tmp_path / "data")
