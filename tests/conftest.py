from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path

import pytest

from gdelt_world.schemas import EVENT_FIELDS


def make_events_row() -> list[str]:
    row = [""] * len(EVENT_FIELDS)
    values = {
        0: "900000001",
        1: "20260716",
        2: "202607",
        3: "2026",
        4: "2026.5397",
        5: "USA",
        6: "UNITED STATES",
        7: "USA",
        15: "IRN",
        16: "IRAN",
        17: "IRN",
        25: "1",
        26: "190",
        27: "190",
        28: "19",
        29: "4",
        30: "-10.0",
        31: "5",
        32: "2",
        33: "3",
        34: "-4.25",
        51: "1",
        52: "United States",
        53: "US",
        56: "38.0",
        57: "-97.0",
        59: "20260716071500",
        60: "https://example.test/article",
    }
    for index, value in values.items():
        row[index] = value
    return row


def write_tsv_zip(path: Path, member: str, rows: list[list[str]]) -> Path:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, delimiter="\t", lineterminator="\n", quoting=csv.QUOTE_NONE)
    writer.writerows(rows)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member, buffer.getvalue().encode())
    return path


@pytest.fixture
def events_zip(tmp_path: Path) -> Path:
    return write_tsv_zip(
        tmp_path / "20260716071500.export.CSV.zip",
        "20260716071500.export.CSV",
        [make_events_row()],
    )
