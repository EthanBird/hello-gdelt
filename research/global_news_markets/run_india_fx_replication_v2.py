from __future__ import annotations

import pandas as pd

import run_india_fx_replication as study

_original_identify_fields = study.identify_fields


def identify_fields_with_usdinr(frame: pd.DataFrame) -> dict[str, str | None]:
    fields = _original_identify_fields(frame)
    if fields.get("price") is None:
        exact_candidates = {
            "usd_to_inr",
            "usd_inr",
            "inr",
            "usd_inr_rate",
            "usd_inr_exchange_rate",
        }
        for column in frame.columns:
            if (
                study.normalize_name(str(column)) in exact_candidates
                and pd.api.types.is_numeric_dtype(frame[column])
            ):
                fields["price"] = str(column)
                break
    return fields


def main() -> None:
    study.identify_fields = identify_fields_with_usdinr
    study.main()


if __name__ == "__main__":
    main()
