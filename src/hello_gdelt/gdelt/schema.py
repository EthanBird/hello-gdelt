from __future__ import annotations

import csv
import io
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DatasetContract:
    name: str
    expected_columns: int
    minimum_rows: int = 1


CONTRACTS: dict[str, DatasetContract] = {
    "events": DatasetContract("events", 61),
    "mentions": DatasetContract("mentions", 16),
    "gkg": DatasetContract("gkg", 27),
}


@dataclass(frozen=True, slots=True)
class DelimitedValidation:
    dataset: str
    row_count: int
    minimum_columns: int
    maximum_columns: int
    malformed_rows: int

    @property
    def passed(self) -> bool:
        contract = CONTRACTS[self.dataset]
        return (
            self.row_count >= contract.minimum_rows
            and self.minimum_columns == contract.expected_columns
            and self.maximum_columns == contract.expected_columns
            and self.malformed_rows == 0
        )


def validate_tsv_sample(dataset: str, text: str, *, max_rows: int = 10_000) -> DelimitedValidation:
    if dataset not in CONTRACTS:
        raise KeyError(f"unknown dataset contract: {dataset}")
    if max_rows <= 0:
        raise ValueError("max_rows must be positive")

    expected = CONTRACTS[dataset].expected_columns
    row_count = 0
    malformed = 0
    min_columns = 10**9
    max_columns = 0
    reader = csv.reader(io.StringIO(text), delimiter="\t", quoting=csv.QUOTE_NONE)
    for row in reader:
        if not row:
            continue
        row_count += 1
        width = len(row)
        min_columns = min(min_columns, width)
        max_columns = max(max_columns, width)
        if width != expected:
            malformed += 1
        if row_count >= max_rows:
            break

    if row_count == 0:
        min_columns = 0
    return DelimitedValidation(
        dataset=dataset,
        row_count=row_count,
        minimum_columns=min_columns,
        maximum_columns=max_columns,
        malformed_rows=malformed,
    )
