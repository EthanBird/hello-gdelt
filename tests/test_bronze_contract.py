from pathlib import Path

import pytest

from hello_gdelt.gdelt.bronze import bronze_partition_path, raw_column_names
from hello_gdelt.gdelt.lastupdate import GdeltArtifact


@pytest.mark.parametrize(
    ("dataset", "width"),
    [("events", 61), ("mentions", 16), ("gkg", 27)],
)
def test_raw_column_names_follow_frozen_width(dataset: str, width: int) -> None:
    names = raw_column_names(dataset)
    assert len(names) == width
    assert names[0].endswith("001")
    assert names[-1].endswith(f"{width:03d}")
    assert len(set(names)) == width


def test_bronze_partition_is_time_and_dataset_prunable(tmp_path: Path) -> None:
    artifact = GdeltArtifact(
        size_bytes=1,
        md5="0" * 32,
        url="https://data.gdeltproject.org/gdeltv2/20260716121500.export.CSV.zip",
        dataset="events",
        timestamp="20260716121500",
    )
    path = bronze_partition_path(tmp_path, artifact)
    assert path.relative_to(tmp_path).as_posix() == (
        "bronze/gdelt/events/year=2026/month=07/day=16/hour=12/"
        "part-20260716121500.parquet"
    )


def test_bronze_partition_rejects_invalid_timestamp(tmp_path: Path) -> None:
    artifact = GdeltArtifact(1, "0" * 32, "https://example.invalid/x", "events", "bad")
    with pytest.raises(ValueError, match="invalid GDELT timestamp"):
        bronze_partition_path(tmp_path, artifact)
