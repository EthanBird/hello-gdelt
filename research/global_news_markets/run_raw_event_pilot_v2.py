from __future__ import annotations

import re
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

import run_raw_event_pilot as pilot


def parse_md5sums_robust(payload: str) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for line in payload.splitlines():
        stripped = line.strip()
        standard = re.match(r"^([0-9a-fA-F]{32})\s+\*?(.+)$", stripped)
        bsd = re.match(r"^MD5\s*\((.+)\)\s*=\s*([0-9a-fA-F]{32})$", stripped)
        if standard:
            mapping[Path(standard.group(2)).name] = standard.group(1).lower()
        elif bsd:
            mapping[Path(bsd.group(1)).name] = bsd.group(2).lower()
    if not mapping:
        raise ValueError("official md5sums file contained no parseable entries")
    return mapping


def read_zip_strict(path: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    with zipfile.ZipFile(path) as archive:
        bad_member = archive.testzip()
        if bad_member is not None:
            raise ValueError(f"corrupt member: {bad_member}")
        members = [member for member in archive.namelist() if not member.endswith("/")]
        if len(members) != 1:
            raise ValueError(f"expected one member, found {members}")
        member = members[0]
        distribution: Counter[int] = Counter()
        total_lines = 0
        with archive.open(member) as handle:
            for line in handle:
                total_lines += 1
                distribution[line.count(b"\t") + 1] += 1
        if total_lines == 0:
            raise ValueError("empty event file")
        valid_lines = distribution[len(pilot.EVENT_COLUMNS)]
        valid_fraction = valid_lines / total_lines
        if valid_fraction < 0.999:
            raise ValueError(
                f"58-column fraction {valid_fraction:.8f} < 0.999; "
                f"distribution={dict(sorted(distribution.items()))}"
            )
        with archive.open(member) as handle:
            raw = pd.read_csv(
                handle,
                sep="\t",
                header=None,
                names=pilot.EVENT_COLUMNS,
                dtype=str,
                on_bad_lines="error",
                low_memory=False,
            )
    for column in pilot.NUMERIC_COLUMNS:
        raw[column] = pd.to_numeric(raw[column], errors="coerce")
    raw["source_domain"] = raw["SOURCEURL"].map(pilot.source_domain)
    raw["event_date"] = pd.to_datetime(
        raw["SQLDATE"].astype("Int64").astype(str), format="%Y%m%d", errors="coerce"
    )
    audit = {
        "zip_member": member,
        "physical_line_count": total_lines,
        "field_count_distribution": {
            str(key): value for key, value in sorted(distribution.items())
        },
        "valid_58_column_fraction": valid_fraction,
        "rows": int(len(raw)),
        "duplicate_event_ids": int(raw["GLOBALEVENTID"].duplicated().sum()),
        "missing_fraction": {
            column: float(raw[column].isna().mean())
            for column in [
                "GLOBALEVENTID",
                "SQLDATE",
                "EventRootCode",
                "QuadClass",
                "GoldsteinScale",
                "NumMentions",
                "AvgTone",
                "SOURCEURL",
            ]
        },
    }
    return raw, audit


def main() -> None:
    pilot.parse_md5sums = parse_md5sums_robust
    pilot.read_zip = read_zip_strict
    pilot.main()


if __name__ == "__main__":
    main()
