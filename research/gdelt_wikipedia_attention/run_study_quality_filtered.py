from __future__ import annotations

import importlib.util
import json
import math
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

MODULE_PATH = Path(__file__).with_name("run_study.py")
spec = importlib.util.spec_from_file_location("attention_study_base", MODULE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("cannot load base study module")
study = importlib.util.module_from_spec(spec)
sys.modules["attention_study_base"] = study
spec.loader.exec_module(study)


def build_quality_filtered_panel(records: list[dict[str, Any]]) -> dict[str, Any]:
    valid_records: list[dict[str, Any]] = []
    excluded_weeks: list[dict[str, Any]] = []
    for record in records:
        missing: list[str] = []
        for region in study.REGION_ORDER:
            component = record.get("components", {}).get(region, {})
            for field in ("gdelt", "wikipedia"):
                value = component.get(field)
                if (
                    value is None
                    or not isinstance(value, (int, float))
                    or not math.isfinite(float(value))
                ):
                    missing.append(f"{region}.{field}")
        if missing:
            excluded_weeks.append(
                {"week_start": str(record.get("week_start")), "missing": missing}
            )
        else:
            valid_records.append(record)

    if len(valid_records) < 40:
        raise ValueError("fewer than 40 complete weekly observations")

    weeks = [str(record["week_start"]) for record in valid_records]
    dates = [datetime.strptime(week, "%Y-%m-%d") for week in weeks]
    gdelt: dict[str, np.ndarray] = {}
    wikipedia: dict[str, np.ndarray] = {}
    for region in study.REGION_ORDER:
        gdelt_values = np.asarray(
            [float(record["components"][region]["gdelt"]) for record in valid_records],
            dtype=float,
        )
        wiki_values = np.asarray(
            [float(record["components"][region]["wikipedia"]) for record in valid_records],
            dtype=float,
        )
        gdelt[region] = study.zscore(np.log1p(gdelt_values))
        wikipedia[region] = study.zscore(np.log1p(wiki_values))

    rows: list[dict[str, Any]] = []
    skipped_nonconsecutive: list[dict[str, str]] = []
    for region_code, region in enumerate(study.REGION_ORDER):
        for t in range(len(weeks) - 1):
            if (dates[t + 1] - dates[t]).days != 7:
                if region_code == 0:
                    skipped_nonconsecutive.append(
                        {"from": weeks[t], "to": weeks[t + 1]}
                    )
                continue
            rows.append(
                {
                    "region": region,
                    "region_code": region_code,
                    "week_index": t,
                    "week": weeks[t],
                    "target_week": weeks[t + 1],
                    "gdelt_t": float(gdelt[region][t]),
                    "wiki_t": float(wikipedia[region][t]),
                    "wiki_t1": float(wikipedia[region][t + 1]),
                    "gdelt_t1": float(gdelt[region][t + 1]),
                }
            )

    return {
        "weeks": weeks,
        "gdelt": gdelt,
        "wikipedia": wikipedia,
        "rows": rows,
        "excluded_weeks": excluded_weeks,
        "skipped_nonconsecutive": skipped_nonconsecutive,
        "raw_week_count": len(records),
    }


def patch_result_metadata(output_dir: Path) -> None:
    result_path = output_dir / "results.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    raw = json.loads(
        (output_dir / "weekly_attention_timeline.json").read_text(encoding="utf-8")
    )
    panel = build_quality_filtered_panel(raw["weekly_timeline"])
    study_info = result.setdefault("study", {})
    study_info.update(
        {
            "raw_weeks": panel["raw_week_count"],
            "complete_weeks": len(panel["weeks"]),
            "panel_rows": len(panel["rows"]),
            "excluded_weeks": panel["excluded_weeks"],
            "skipped_nonconsecutive_transitions": panel["skipped_nonconsecutive"],
        }
    )
    result["quality"] = {
        "excluded_incomplete_weeks": len(panel["excluded_weeks"]),
        "transform": "region-wise zscore(log1p(value))",
        "primary_multiple_testing": "Benjamini-Hochberg FDR over two directional hypotheses",
        "regional_multiple_testing": "Benjamini-Hochberg FDR over six regions",
        "placebo": "1000 independent within-region circular time shifts",
    }
    result["limitations"] = [
        "The dataset is a secondary static snapshot assembled from public APIs.",
        "GDELT and Wikipedia region aggregations differ in source composition and scale.",
        "Weekly temporal precedence is not proof of causality.",
        "Only 49 complete weeks and six broad regions are available.",
        "OLS p-values use a normal approximation rather than cluster-robust inference.",
    ]
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main() -> None:
    study.build_panel = build_quality_filtered_panel
    study.main()
    output_dir = Path(os.environ.get("RESEARCH_OUTPUT", "research_output"))
    patch_result_metadata(output_dir)


if __name__ == "__main__":
    main()
