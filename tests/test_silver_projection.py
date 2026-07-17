from pathlib import Path

import pytest

pl = pytest.importorskip("polars")

from hello_gdelt.gdelt.bronze import BronzeReceipt, raw_column_names
from hello_gdelt.gdelt.fields import EVENT_COLUMNS
from hello_gdelt.gdelt.silver import SilverProjectionError, project_bronze_to_silver


def event_values(*, invalid_global_id: bool = False) -> dict[str, str | None]:
    values: dict[str, str | None] = {name: None for name in EVENT_COLUMNS}
    values.update(
        {
            "global_event_id": "bad" if invalid_global_id else "123",
            "sql_date": "20260717",
            "month_year": "202607",
            "year": "2026",
            "fraction_date": "2026.54",
            "is_root_event": "1",
            "event_code": "010",
            "event_base_code": "010",
            "event_root_code": "01",
            "quad_class": "1",
            "goldstein_scale": "3.4",
            "num_mentions": "2",
            "num_sources": "2",
            "num_articles": "2",
            "avg_tone": "-1.25",
            "date_added": "20260717054500",
            "source_url": "https://example.org/article",
        }
    )
    return values


def write_bronze_fixture(
    tmp_path: Path,
    *,
    invalid_global_id: bool = False,
) -> BronzeReceipt:
    raw = raw_column_names("events")
    semantic_values = event_values(invalid_global_id=invalid_global_id)
    data = {
        raw_name: [semantic_values[semantic_name]]
        for raw_name, semantic_name in zip(raw, EVENT_COLUMNS, strict=True)
    }
    data.update(
        {
            "_source_url": ["http://data.gdeltproject.org/fixture.zip"],
            "_source_timestamp": ["20260717054500"],
            "_source_md5": ["0" * 32],
            "_schema_version": ["fixture"],
            "_ingested_at_utc": ["2026-07-17T00:00:00+00:00"],
        }
    )
    path = tmp_path / "bronze.parquet"
    pl.DataFrame(data).write_parquet(path)
    return BronzeReceipt(
        dataset="events",
        source_path=str(tmp_path / "events.tsv"),
        parquet_path=str(path),
        manifest_path=str(tmp_path / "bronze.manifest.json"),
        source_url="http://data.gdeltproject.org/fixture.zip",
        source_timestamp="20260717054500",
        source_md5="0" * 32,
        schema_version="fixture",
        row_count=1,
        column_count=61,
        ingested_at_utc="2026-07-17T00:00:00+00:00",
    )


def test_silver_projection_renames_and_casts_event_fields(tmp_path: Path) -> None:
    bronze = write_bronze_fixture(tmp_path)
    receipt = project_bronze_to_silver(bronze, tmp_path / "data")
    frame = pl.read_parquet(receipt.silver_path)
    assert receipt.row_count == 1
    assert frame["global_event_id"].dtype == pl.Int64
    assert frame["goldstein_scale"].dtype == pl.Float64
    assert frame["global_event_id"].item() == 123
    assert frame["source_url"].item() == "https://example.org/article"
    assert dict(receipt.invalid_casts)["global_event_id"] == 0


def test_silver_projection_rejects_numeric_conversion_loss(tmp_path: Path) -> None:
    bronze = write_bronze_fixture(tmp_path, invalid_global_id=True)
    with pytest.raises(SilverProjectionError, match="semantic conversion loss"):
        project_bronze_to_silver(bronze, tmp_path / "data")
