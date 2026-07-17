from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import urllib.request
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np

from hello_gdelt.hypothesis.statistics import bh_fdr, fit_ols, r2_score

DATA_URL = (
    "https://raw.githubusercontent.com/lukeslp/us-attention-data/"
    "main/weekly_attention_timeline.json"
)
REGION_ORDER = [
    "africa",
    "asia_pacific",
    "europe",
    "latin_america",
    "middle_east",
    "north_america",
]
REGION_ZH = {
    "africa": "非洲",
    "asia_pacific": "亚太",
    "europe": "欧洲",
    "latin_america": "拉丁美洲",
    "middle_east": "中东",
    "north_america": "北美",
}


@dataclass(frozen=True)
class ModelResult:
    beta: float
    standard_error: float
    t_value: float
    p_value: float
    n: int
    condition_number: float


@dataclass(frozen=True)
class FoldResult:
    train_end_week: str
    test_start_week: str
    test_end_week: str
    n_test: int
    baseline_rmse: float
    augmented_rmse: float
    rmse_improvement: float
    baseline_r2: float
    augmented_r2: float
    beta: float


def download(url: str, destination: Path) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "hello-gdelt-research/0.1"})
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = response.read()
    destination.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def zscore(values: np.ndarray) -> np.ndarray:
    mean = float(np.mean(values))
    std = float(np.std(values, ddof=1))
    if not math.isfinite(std) or std <= 0:
        raise ValueError("series has zero or invalid variance")
    return (values - mean) / std


def region_dummies(region_codes: np.ndarray, region_count: int) -> np.ndarray:
    columns = [np.ones(len(region_codes), dtype=float)]
    for code in range(1, region_count):
        columns.append((region_codes == code).astype(float))
    return np.column_stack(columns)


def build_panel(records: list[dict[str, Any]]) -> dict[str, Any]:
    weeks = [str(record["week_start"]) for record in records]
    gdelt: dict[str, np.ndarray] = {}
    wikipedia: dict[str, np.ndarray] = {}
    for region in REGION_ORDER:
        gdelt_values = np.asarray(
            [float(record["components"][region]["gdelt"]) for record in records], dtype=float
        )
        wiki_values = np.asarray(
            [float(record["components"][region]["wikipedia"]) for record in records], dtype=float
        )
        if not np.isfinite(gdelt_values).all() or not np.isfinite(wiki_values).all():
            raise ValueError(f"non-finite values found for {region}")
        gdelt[region] = zscore(np.log1p(gdelt_values))
        wikipedia[region] = zscore(np.log1p(wiki_values))

    rows: list[dict[str, Any]] = []
    for region_code, region in enumerate(REGION_ORDER):
        for t in range(len(weeks) - 1):
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
    return {"weeks": weeks, "gdelt": gdelt, "wikipedia": wikipedia, "rows": rows}


def matrix_from_rows(
    rows: list[dict[str, Any]], *, target: str, feature: str, include_lag: str
) -> tuple[np.ndarray, np.ndarray, int]:
    region_codes = np.asarray([int(row["region_code"]) for row in rows], dtype=np.int64)
    fixed = region_dummies(region_codes, len(REGION_ORDER))
    lag = np.asarray([float(row[include_lag]) for row in rows], dtype=float)
    feat = np.asarray([float(row[feature]) for row in rows], dtype=float)
    y = np.asarray([float(row[target]) for row in rows], dtype=float)
    x = np.column_stack([fixed, lag, feat])
    return x, y, x.shape[1] - 1


def fit_panel(
    rows: list[dict[str, Any]], *, target: str, feature: str, include_lag: str
) -> ModelResult:
    x, y, feature_index = matrix_from_rows(
        rows, target=target, feature=feature, include_lag=include_lag
    )
    fit = fit_ols(x, y)
    return ModelResult(
        beta=float(fit.coefficients[feature_index]),
        standard_error=float(fit.standard_errors[feature_index]),
        t_value=float(fit.t_values[feature_index]),
        p_value=float(fit.p_values[feature_index]),
        n=len(y),
        condition_number=float(fit.condition_number),
    )


def expanding_walk_forward(rows: list[dict[str, Any]]) -> list[FoldResult]:
    fold_results: list[FoldResult] = []
    max_week = max(int(row["week_index"]) for row in rows)
    test_start = 30
    while test_start <= max_week:
        test_end = min(test_start + 3, max_week)
        train = [row for row in rows if int(row["week_index"]) < test_start]
        test = [row for row in rows if test_start <= int(row["week_index"]) <= test_end]
        if len(train) < 120 or len(test) < 6:
            break

        train_codes = np.asarray([int(row["region_code"]) for row in train], dtype=np.int64)
        test_codes = np.asarray([int(row["region_code"]) for row in test], dtype=np.int64)
        train_fixed = region_dummies(train_codes, len(REGION_ORDER))
        test_fixed = region_dummies(test_codes, len(REGION_ORDER))
        train_lag = np.asarray([float(row["wiki_t"]) for row in train])
        test_lag = np.asarray([float(row["wiki_t"]) for row in test])
        train_feature = np.asarray([float(row["gdelt_t"]) for row in train])
        test_feature = np.asarray([float(row["gdelt_t"]) for row in test])
        y_train = np.asarray([float(row["wiki_t1"]) for row in train])
        y_test = np.asarray([float(row["wiki_t1"]) for row in test])

        x_base_train = np.column_stack([train_fixed, train_lag])
        x_base_test = np.column_stack([test_fixed, test_lag])
        x_aug_train = np.column_stack([train_fixed, train_lag, train_feature])
        x_aug_test = np.column_stack([test_fixed, test_lag, test_feature])
        base = fit_ols(x_base_train, y_train)
        aug = fit_ols(x_aug_train, y_train)
        pred_base = x_base_test @ base.coefficients
        pred_aug = x_aug_test @ aug.coefficients
        rmse_base = float(np.sqrt(np.mean((y_test - pred_base) ** 2)))
        rmse_aug = float(np.sqrt(np.mean((y_test - pred_aug) ** 2)))
        fold_results.append(
            FoldResult(
                train_end_week=str(train[-1]["week"]),
                test_start_week=str(test[0]["week"]),
                test_end_week=str(test[-1]["week"]),
                n_test=len(test),
                baseline_rmse=rmse_base,
                augmented_rmse=rmse_aug,
                rmse_improvement=(rmse_base - rmse_aug) / rmse_base,
                baseline_r2=r2_score(y_test, pred_base),
                augmented_r2=r2_score(y_test, pred_aug),
                beta=float(aug.coefficients[-1]),
            )
        )
        test_start += 4
    return fold_results


def circular_shift_placebo(
    panel: dict[str, Any], *, repetitions: int = 1000, seed: int = 20260717
) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    observed_rows = panel["rows"]
    observed = fit_panel(
        observed_rows, target="wiki_t1", feature="gdelt_t", include_lag="wiki_t"
    )
    placebo_betas: list[float] = []
    weeks_count = len(panel["weeks"])
    for _ in range(repetitions):
        shifted_by_region: dict[str, np.ndarray] = {}
        for region in REGION_ORDER:
            offset = int(rng.integers(2, max(3, weeks_count - 2)))
            shifted_by_region[region] = np.roll(panel["gdelt"][region], offset)
        placebo_rows: list[dict[str, Any]] = []
        for row in observed_rows:
            copied = dict(row)
            copied["gdelt_t"] = float(
                shifted_by_region[str(row["region"])][int(row["week_index"])]
            )
            placebo_rows.append(copied)
        placebo_betas.append(
            fit_panel(
                placebo_rows, target="wiki_t1", feature="gdelt_t", include_lag="wiki_t"
            ).beta
        )
    abs_placebo = np.abs(np.asarray(placebo_betas))
    p_empirical = float((1 + np.sum(abs_placebo >= abs(observed.beta))) / (repetitions + 1))
    return {
        "observed_beta": observed.beta,
        "repetitions": repetitions,
        "empirical_p": p_empirical,
        "abs_beta_p95": float(np.quantile(abs_placebo, 0.95)),
        "placebo_betas": placebo_betas,
    }


def regional_models(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    p_values: list[float] = []
    for region in REGION_ORDER:
        subset = [row for row in rows if row["region"] == region]
        x = np.column_stack(
            [
                np.ones(len(subset)),
                np.asarray([float(row["wiki_t"]) for row in subset]),
                np.asarray([float(row["gdelt_t"]) for row in subset]),
            ]
        )
        y = np.asarray([float(row["wiki_t1"]) for row in subset])
        fit = fit_ols(x, y)
        result = {
            "region": region,
            "region_zh": REGION_ZH[region],
            "beta": float(fit.coefficients[-1]),
            "standard_error": float(fit.standard_errors[-1]),
            "t_value": float(fit.t_values[-1]),
            "p_value": float(fit.p_values[-1]),
            "n": len(subset),
        }
        p_values.append(result["p_value"])
        output.append(result)
    q_values = bh_fdr(p_values)
    for result, q_value in zip(output, q_values, strict=True):
        result["q_value"] = q_value
        result["significant_fdr_005"] = q_value <= 0.05
    return output


def synchronization(panel: dict[str, Any]) -> dict[str, Any]:
    matrix = np.column_stack([panel["gdelt"][region] for region in REGION_ORDER])
    correlation = np.corrcoef(matrix, rowvar=False)
    eigenvalues = np.linalg.eigvalsh(correlation)[::-1]
    first_share = float(eigenvalues[0] / np.sum(eigenvalues))
    off_diagonal = correlation[np.triu_indices_from(correlation, k=1)]
    return {
        "mean_pairwise_correlation": float(np.mean(off_diagonal)),
        "median_pairwise_correlation": float(np.median(off_diagonal)),
        "min_pairwise_correlation": float(np.min(off_diagonal)),
        "max_pairwise_correlation": float(np.max(off_diagonal)),
        "first_pc_variance_share": first_share,
        "correlation_matrix": correlation.tolist(),
    }


def write_panel_csv(rows: list[dict[str, Any]], path: Path) -> None:
    fields = [
        "region", "region_code", "week_index", "week", "target_week",
        "gdelt_t", "wiki_t", "wiki_t1", "gdelt_t1",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def create_charts(
    panel: dict[str, Any],
    folds: list[FoldResult],
    placebo: dict[str, Any],
    regional: list[dict[str, Any]],
    out_dir: Path,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    weeks = np.arange(len(panel["weeks"]))

    fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
    for region in REGION_ORDER:
        axes[0].plot(weeks, panel["gdelt"][region], label=REGION_ZH[region], linewidth=1.4)
        axes[1].plot(weeks, panel["wikipedia"][region], label=REGION_ZH[region], linewidth=1.4)
    axes[0].set_ylabel("GDELT standardized attention")
    axes[1].set_ylabel("Wikipedia standardized views")
    axes[1].set_xlabel("Week index")
    axes[0].axhline(0, linewidth=0.7)
    axes[1].axhline(0, linewidth=0.7)
    axes[0].legend(ncol=3, fontsize=8, frameon=False)
    fig.tight_layout()
    fig.savefig(out_dir / "figure_1_timeseries.png", dpi=220)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 4.6))
    positions = np.arange(len(folds))
    improvements = [fold.rmse_improvement * 100 for fold in folds]
    ax.bar(positions, improvements)
    ax.axhline(0, linewidth=0.8)
    ax.set_xticks(positions, [f"F{i+1}" for i in positions])
    ax.set_ylabel("Relative RMSE improvement (%)")
    ax.set_xlabel("Expanding-window out-of-sample fold")
    ax.set_title("GDELT feature versus AR(1)+region baseline")
    fig.tight_layout()
    fig.savefig(out_dir / "figure_2_walkforward.png", dpi=220)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 4.6))
    betas = np.asarray(placebo["placebo_betas"])
    ax.hist(betas, bins=35, alpha=0.8)
    ax.axvline(placebo["observed_beta"], linewidth=2, label="Observed beta")
    ax.axvline(-placebo["abs_beta_p95"], linestyle="--", linewidth=1)
    ax.axvline(placebo["abs_beta_p95"], linestyle="--", linewidth=1, label="95% placebo |beta|")
    ax.set_xlabel("Circular-shift placebo beta")
    ax.set_ylabel("Frequency")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(out_dir / "figure_3_placebo.png", dpi=220)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 4.8))
    ordered = sorted(regional, key=lambda item: item["beta"])
    y_pos = np.arange(len(ordered))
    beta = np.asarray([item["beta"] for item in ordered])
    se = np.asarray([item["standard_error"] for item in ordered])
    ax.errorbar(beta, y_pos, xerr=1.96 * se, fmt="o", capsize=3)
    ax.axvline(0, linewidth=0.8)
    ax.set_yticks(y_pos, [item["region"] for item in ordered])
    ax.set_xlabel("Regional beta and normal-approximation 95% CI")
    ax.set_title("Regional heterogeneity of GDELT lead effect")
    fig.tight_layout()
    fig.savefig(out_dir / "figure_4_regional_effects.png", dpi=220)
    plt.close(fig)


def main() -> None:
    out_dir = Path(os.environ.get("RESEARCH_OUTPUT", "research_output"))
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_path = out_dir / "weekly_attention_timeline.json"
    sha256 = download(DATA_URL, raw_path)
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    records = raw.get("weekly_timeline")
    if not isinstance(records, list) or len(records) < 50:
        raise ValueError("expected at least 50 weekly observations")
    panel = build_panel(records)
    rows = panel["rows"]

    forward = fit_panel(rows, target="wiki_t1", feature="gdelt_t", include_lag="wiki_t")
    reverse = fit_panel(rows, target="gdelt_t1", feature="wiki_t", include_lag="gdelt_t")
    concurrent = fit_panel(rows, target="wiki_t", feature="gdelt_t", include_lag="wiki_t1")
    q_forward, q_reverse = bh_fdr([forward.p_value, reverse.p_value])
    folds = expanding_walk_forward(rows)
    placebo = circular_shift_placebo(panel)
    regional = regional_models(rows)
    sync = synchronization(panel)

    mean_improvement = float(np.mean([fold.rmse_improvement for fold in folds]))
    median_improvement = float(np.median([fold.rmse_improvement for fold in folds]))
    positive_folds = int(sum(fold.rmse_improvement > 0 for fold in folds))
    sign_stability = float(np.mean([
        math.copysign(1.0, fold.beta) == math.copysign(1.0, forward.beta) for fold in folds
    ]))
    supported = bool(
        q_forward <= 0.05
        and placebo["empirical_p"] <= 0.05
        and mean_improvement > 0
        and sign_stability >= 0.7
    )
    reverse_supported = bool(q_reverse <= 0.05 and abs(reverse.beta) > 0.05)

    result = {
        "study": {
            "title": "GDELT news attention versus subsequent Wikipedia information demand",
            "generated_at": datetime.now(UTC).isoformat(),
            "analysis_protocol": "hello-gdelt Hypothesis Lab v0.1 compatible",
            "source_url": DATA_URL,
            "source_sha256": sha256,
            "source_generated_at": raw.get("metadata", {}).get("generated_at"),
            "source_note": raw.get("metadata", {}).get("note"),
            "weeks": len(panel["weeks"]),
            "regions": len(REGION_ORDER),
            "panel_rows": len(rows),
            "date_start": panel["weeks"][0],
            "date_end": panel["weeks"][-1],
        },
        "hypotheses": {
            "H1_forward": {
                "claim": "Regional GDELT attention predicts next-week Wikipedia demand",
                "model": asdict(forward),
                "q_value_bh": q_forward,
                "walk_forward_mean_rmse_improvement": mean_improvement,
                "walk_forward_median_rmse_improvement": median_improvement,
                "walk_forward_positive_folds": positive_folds,
                "walk_forward_total_folds": len(folds),
                "fold_sign_stability": sign_stability,
                "placebo_empirical_p": placebo["empirical_p"],
                "decision": "supported" if supported else "inconclusive",
            },
            "H2_reverse": {
                "claim": "Regional Wikipedia demand predicts next-week GDELT attention",
                "model": asdict(reverse),
                "q_value_bh": q_reverse,
                "decision": "supported" if reverse_supported else "inconclusive",
            },
            "concurrent_association": asdict(concurrent),
        },
        "synchronization": sync,
        "walk_forward": [asdict(fold) for fold in folds],
        "placebo": {key: value for key, value in placebo.items() if key != "placebo_betas"},
        "regional_models": regional,
        "quality": {
            "missing_values": 0,
            "transform": "region-wise zscore(log1p(value))",
            "primary_multiple_testing": "Benjamini-Hochberg FDR over two directional hypotheses",
            "regional_multiple_testing": "Benjamini-Hochberg FDR over six regions",
            "placebo": "1000 independent within-region circular time shifts",
        },
        "limitations": [
            "The dataset is a secondary static snapshot assembled from public APIs.",
            "GDELT and Wikipedia region aggregations differ in source composition and scale.",
            "Weekly temporal precedence is not proof of causality.",
            "Only 53 weeks and six broad regions are available in this reproducible panel.",
            "OLS p-values use the current Hypothesis Lab normal approximation rather than cluster-robust inference.",
        ],
    }
    (out_dir / "results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_panel_csv(rows, out_dir / "analysis_panel.csv")
    create_charts(panel, folds, placebo, regional, out_dir)
    print(json.dumps(result["hypotheses"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
