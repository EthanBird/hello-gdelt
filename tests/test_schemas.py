from __future__ import annotations

from pathlib import Path

from conftest import make_events_row, write_tsv_zip

from gdelt_world.schemas import inspect_zip


def test_inspect_valid_events(events_zip: Path) -> None:
    result = inspect_zip(events_zip, "events")

    assert result.valid
    assert result.rows == 1
    assert result.field_count_histogram == {61: 1}


def test_inspect_records_malformed_rows(tmp_path: Path) -> None:
    malformed = make_events_row()[:-1]
    archive = write_tsv_zip(
        tmp_path / "bad.export.CSV.zip",
        "bad.export.CSV",
        [malformed],
    )

    result = inspect_zip(archive, "events")

    assert not result.valid
    assert result.malformed_rows == (1,)
    assert result.field_count_histogram == {60: 1}
