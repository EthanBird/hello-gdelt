from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from gdelt_world.source import (
    ManifestEntry,
    download_entry,
    file_md5,
    group_complete_batches,
    parse_manifest,
)


def test_parse_manifest_and_group_complete_batches() -> None:
    text = "\n".join(
        [
            "10 11111111111111111111111111111111 http://data.gdeltproject.org/gdeltv2/20260716071500.export.CSV.zip",
            "20 22222222222222222222222222222222 http://data.gdeltproject.org/gdeltv2/20260716071500.mentions.CSV.zip",
            "30 33333333333333333333333333333333 http://data.gdeltproject.org/gdeltv2/20260716071500.gkg.csv.zip",
            "11 44444444444444444444444444444444 http://data.gdeltproject.org/gdeltv2/20260716073000.export.CSV.zip",
        ]
    )
    entries = parse_manifest(text)
    batches = group_complete_batches(entries)

    assert len(entries) == 4
    assert batches[0][0] == "20260716071500"
    assert [entry.kind for entry in batches[0][1]] == ["events", "mentions", "gkg"]


def test_manifest_rejects_unknown_filename() -> None:
    with pytest.raises(ValueError, match="unsupported GDELT URL"):
        parse_manifest(
            "10 11111111111111111111111111111111 "
            "http://data.gdeltproject.org/gdeltv2/20260716071500.unknown.zip"
        )


def test_download_entry_validates_and_records_strong_hash(events_zip: Path, tmp_path: Path) -> None:
    entry = ManifestEntry(
        size_bytes=events_zip.stat().st_size,
        md5=file_md5(events_zip),
        url=events_zip.as_uri(),
        batch_id="20260716071500",
        kind="events",
    )

    result = download_entry(entry, tmp_path / "downloads", retries=0)

    expected_sha256 = hashlib.sha256(events_zip.read_bytes()).hexdigest()
    assert result.inspection["valid"]
    assert result.sha256 == expected_sha256
    assert not result.reused
