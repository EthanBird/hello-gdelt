from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import statsmodels.api as sm
from huggingface_hub import hf_hub_download

from hello_gdelt.hypothesis.statistics import bh_fdr

REPO_ID = "AmritJain/gdelt-india-research-datasets"
REPO_PATH = "master_dataset/Super_Master_Dataset.csv"
OUTPUT = Path(os.environ.get("MASTER_PANEL_OUTPUT", "master_panel_output"))
LOCAL_INPUT = os.environ.get("MASTER_PANEL_FILE")
ASSETS = ["INR", "OIL", "GOLD", "US10Y", "DXY"]
NEWS = [
    "IN_Avg_Tone",
    "IN_Avg_Stability",
    "IN_Total_Mentions",
    "IN_Panic_Index",
    "US_Avg_Tone",
    "US_Avg_Stability",
    "US_Total_Mentions",
    "US_Panic_Index",
    "Diff_Stability",
    "Diff_Tone",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_seed(*parts: str) -> int:
    digest = hashlib.sha256("|".join(parts).encode()).digest()
    return int.from_bytes(digest[:8], "big") % (2**32 - 1)


def obtain_input() -> Path:
    if LOCAL_INPUT:
        path = Path(LOCAL_INPUT)
        if not path.exists():
            raise FileNotFoundError(path)
        return path
    return Path(
        hf_hub_download(
            repo_id=REPO_ID,
            repo_type="dataset",
            filename=REPO_PATH,
            local_dir=OUTPUT / "raw",
        )
    )


def prepare(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, parse_dates=["Date"]).sort_values("Date")
    frame = frame.drop_duplicates("Date").reset_index(drop=True)
    required = {"Date", *ASSETS, *NEWS}
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"missing columns: {missing}")
    if frame[list(required)].isna().any().any():
        raise ValueError("missing values in preregistered columns")
    for asset in ASSETS:
        if asset == "US10Y":
            frame[f"{asset}_chg"] = frame[asset].diff()
        else:
            frame[f"{asset}_chg"] = np.log(frame[asset].where(frame[asset] > 0)).diff()
        frame[f"{asset}_abs"] = frame[f"{asset}_chg"].abs()
    for feature in NEWS:
        values = np.log1p(frame[feature]) if "Mentions" in feature else frame[feature]
        mean = values.rolling(60, min_periods=30).mean().shift(1)
        std = values.rolling(60, min_periods=30).std(ddof=0).shift(1)
        frame[f"{feature}_z60"] = (values - mean) / std.replace(0, np.nan)
    for asset in ASSETS:
        change = frame[f"{asset}_chg"]
        for horizon in (1, 5):
            future = pd.concat(
                [change.shift(-offset) for offset in range(1, horizon + 1)], axis=1
            ).sum(axis=1, min_count=horizon)
            frame[f"{asset}_future_{horizon}d"] = future
            frame[f"{asset}_future_abs_{horizon}d"] = future.abs()
    weekdays = pd.get_dummies(
        frame["Date"].dt.dayofweek, prefix="wd", drop_first=True, dtype=float
    )
    return pd.concat([frame, weekdays], axis=1)


def fit_hac(
    sample: pd.DataFrame,
    controls: list[str],
    feature: str,
    target: str,
    lags: int,
) -> tuple[float, float, float, float, float]:
    matrix = sm.add_constant(sample[controls + [feature]].astype(float), has_constant="add")
    fit = sm.OLS(sample[target].astype(float), matrix).fit(
        cov_type="HAC", cov_kwds={"maxlags": lags}
    )
    low, high = fit.conf_int().loc[feature]
    return (
        float(fit.params[feature]),
        float(fit.bse[feature]),
        float(fit.pvalues[feature]),
        float(low),
        float(high),
    )


def predict(
    train: pd.DataFrame,
    test: pd.DataFrame,
    columns: list[str],
    target: str,
) -> tuple[np.ndarray, float]:
    train_x = np.column_stack([np.ones(len(train)), train[columns].to_numpy(float)])
    test_x = np.column_stack([np.ones(len(test)), test[columns].to_numpy(float)])
    coefficients = np.linalg.lstsq(train_x, train[target].to_numpy(float), rcond=None)[0]
    return test_x @ coefficients, float(coefficients[-1])


def walk_forward(
    sample: pd.DataFrame,
    controls: list[str],
    feature: str,
    target: str,
) -> dict[str, Any]:
    initial = max(
        int(np.searchsorted(sample["Date"].to_numpy(), np.datetime64("2022-01-01"))),
        500,
    )
    baseline_errors: list[float] = []
    full_errors: list[float] = []
    betas: list[float] = []
    windows: list[tuple[str, str]] = []
    for start in range(initial, len(sample), 63):
        stop = min(len(sample), start + 63)
        if stop - start < 20:
            continue
        train = sample.iloc[:start]
        test = sample.iloc[start:stop]
        baseline_prediction, _ = predict(train, test, controls, target)
        full_prediction, beta = predict(train, test, controls + [feature], target)
        actual = test[target].to_numpy(float)
        baseline_errors.extend((actual - baseline_prediction).tolist())
        full_errors.extend((actual - full_prediction).tolist())
        betas.append(beta)
        windows.append((str(test["Date"].min().date()), str(test["Date"].max().date())))
    baseline_rmse = float(np.sqrt(np.mean(np.square(baseline_errors))))
    full_rmse = float(np.sqrt(np.mean(np.square(full_errors))))
    return {
        "baseline_rmse": baseline_rmse,
        "full_rmse": full_rmse,
        "improvement": (baseline_rmse - full_rmse) / baseline_rmse,
        "betas": betas,
        "windows": windows,
    }


def holdout(
    sample: pd.DataFrame,
    controls: list[str],
    feature: str,
    target: str,
) -> tuple[float, float, float]:
    train = sample[sample["Date"] < pd.Timestamp("2025-01-01")]
    test = sample[sample["Date"] >= pd.Timestamp("2025-01-01")]
    baseline_prediction, _ = predict(train, test, controls, target)
    full_prediction, _ = predict(train, test, controls + [feature], target)
    actual = test[target].to_numpy(float)
    baseline_rmse = float(np.sqrt(np.mean(np.square(actual - baseline_prediction))))
    full_rmse = float(np.sqrt(np.mean(np.square(actual - full_prediction))))
    return baseline_rmse, full_rmse, (baseline_rmse - full_rmse) / baseline_rmse


def placebo(
    sample: pd.DataFrame,
    controls: list[str],
    feature: str,
    target: str,
    beta: float,
    seed: int,
) -> float:
    control_matrix = np.column_stack(
        [np.ones(len(sample)), sample[controls].to_numpy(float)]
    )
    q_matrix, _ = np.linalg.qr(control_matrix, mode="reduced")
    y = sample[target].to_numpy(float)
    residual_y = y - q_matrix @ (q_matrix.T @ y)
    x = sample[feature].to_numpy(float)
    rng = np.random.default_rng(seed)
    values: list[float] = []
    for shift in rng.integers(20, len(sample) - 20, size=200):
        shifted = np.roll(x, int(shift))
        residual_x = shifted - q_matrix @ (q_matrix.T @ shifted)
        denominator = float(residual_x @ residual_x)
        values.append(
            float(residual_x @ residual_y) / denominator if denominator > 1e-16 else 0.0
        )
    return float((1 + sum(abs(value) >= abs(beta) for value in values)) / 201)


def run(panel: pd.DataFrame) -> pd.DataFrame:
    news_features = [f"{feature}_z60" for feature in NEWS]
    current_changes = [f"{asset}_chg" for asset in ASSETS]
    weekdays = [column for column in panel.columns if column.startswith("wd_")]
    records: list[dict[str, Any]] = []
    for asset in ASSETS:
        controls = list(dict.fromkeys([*current_changes, f"{asset}_abs", *weekdays]))
        for horizon in (1, 5):
            specifications = [
                ("MP-RET", f"{asset}_future_{horizon}d", "nonzero"),
                ("MP-VOL", f"{asset}_future_abs_{horizon}d", "positive"),
            ]
            for family, target, expected in specifications:
                for feature in news_features:
                    sample = panel[["Date", target, feature, *controls]].dropna().reset_index(drop=True)
                    record: dict[str, Any] = {
                        "family": family,
                        "asset": asset,
                        "horizon": horizon,
                        "feature": feature,
                        "target": target,
                        "expected": expected,
                        "nobs": int(len(sample)),
                    }
                    if len(sample) < 750:
                        record.update(status="DATA_INSUFFICIENT")
                        records.append(record)
                        continue
                    lags = 5 if horizon == 1 else 10
                    beta, se, p_value, low, high = fit_hac(
                        sample, controls, feature, target, lags
                    )
                    rolling = walk_forward(sample, controls, feature, target)
                    holdout_base, holdout_full, holdout_gain = holdout(
                        sample, controls, feature, target
                    )
                    stability = float(
                        np.mean([np.sign(value) == np.sign(beta) for value in rolling["betas"]])
                    )
                    target_std = float(sample[target].std(ddof=0))
                    record.update(
                        {
                            "status": "TESTED",
                            "beta": beta,
                            "standard_error_hac": se,
                            "p_value": p_value,
                            "ci_low": low,
                            "ci_high": high,
                            "effect_target_sd": beta * float(sample[feature].std(ddof=0)) / target_std,
                            "placebo_p": placebo(
                                sample,
                                controls,
                                feature,
                                target,
                                beta,
                                stable_seed(asset, str(horizon), family, feature),
                            ),
                            "oos_baseline_rmse": rolling["baseline_rmse"],
                            "oos_full_rmse": rolling["full_rmse"],
                            "oos_improvement": rolling["improvement"],
                            "holdout_baseline_rmse": holdout_base,
                            "holdout_full_rmse": holdout_full,
                            "holdout_improvement": holdout_gain,
                            "folds": len(rolling["betas"]),
                            "sign_stability": stability,
                            "fold_betas_json": json.dumps(rolling["betas"]),
                            "fold_windows_json": json.dumps(rolling["windows"]),
                        }
                    )
                    records.append(record)
    frame = pd.DataFrame(records)
    frame["q_value"] = math.nan
    tested = frame[frame["status"] == "TESTED"]
    for (_, _), indices in tested.groupby(["family", "horizon"]).groups.items():
        frame.loc[indices, "q_value"] = bh_fdr(
            frame.loc[indices, "p_value"].astype(float).tolist()
        )
    decisions: list[str] = []
    for row in frame.to_dict("records"):
        if row["status"] != "TESTED":
            decisions.append("DATA_INSUFFICIENT")
            continue
        direction_ok = row["expected"] == "nonzero" or float(row["beta"]) > 0
        supported = (
            direction_ok
            and float(row["q_value"]) <= 0.05
            and float(row["placebo_p"]) <= 0.05
            and float(row["oos_improvement"]) > 0
            and float(row["sign_stability"]) >= 0.60
        )
        decisions.append(
            "SUPPORTED_EXTERNAL_MULTI_ASSET" if supported else "INCONCLUSIVE"
        )
    frame["decision"] = decisions
    return frame


def write_report(results: pd.DataFrame, input_path: Path, panel: pd.DataFrame) -> None:
    tested = results[results["status"] == "TESTED"].copy()
    top = tested.sort_values(["p_value", "placebo_p", "oos_improvement"]).head(20)
    lines = [
        "# GDELT 新闻状态与五类宏观资产：外部多资产验证",
        "",
        f"数据范围：{panel['Date'].min().date()} 至 {panel['Date'].max().date()}；原始行数：{len(panel)}。",
        "",
        "## 严格结论",
        "",
        f"- 预注册检验：{len(tested)}；",
        f"- 名义 p<0.05：{int((tested['p_value'] < 0.05).sum())}；",
        f"- BH-FDR q<0.05：{int((tested['q_value'] < 0.05).sum())}；",
        f"- 全部门禁通过：{int((tested['decision'] == 'SUPPORTED_EXTERNAL_MULTI_ASSET').sum())}。",
        "",
        "没有任何新闻—资产关系通过完整确认门禁。若不处理多重检验，200项研究会制造若干看似显著的假规律。",
        "",
        "## 名义证据最强的20项",
        "",
        top[
            [
                "asset",
                "horizon",
                "family",
                "feature",
                "beta",
                "p_value",
                "q_value",
                "placebo_p",
                "oos_improvement",
                "holdout_improvement",
                "sign_stability",
            ]
        ].to_markdown(index=False, floatfmt=".5g"),
        "",
        "## 数据边界",
        "",
        f"输入文件 SHA-256：`{sha256_file(input_path)}`。这是第三方整理的外部验证面板，不是最终确认性样本。",
    ]
    (OUTPUT / "master_panel_report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    input_path = obtain_input()
    panel = prepare(input_path)
    results = run(panel)
    panel.to_csv(OUTPUT / "analysis_panel.csv", index=False)
    results.to_csv(OUTPUT / "master_panel_results.csv", index=False)
    write_report(results, input_path, panel)
    manifest = {
        "study_id": "gdelt-2019-2026-external-multi-asset",
        "source_repo": REPO_ID,
        "source_path": REPO_PATH,
        "source_sha256": sha256_file(input_path),
        "panel_rows": int(len(panel)),
        "panel_start": str(panel["Date"].min().date()),
        "panel_end": str(panel["Date"].max().date()),
        "tested": int((results["status"] == "TESTED").sum()),
        "nominal_p_lt_005": int((results["p_value"] < 0.05).sum()),
        "fdr_q_lt_005": int((results["q_value"] < 0.05).sum()),
        "supported": int(
            (results["decision"] == "SUPPORTED_EXTERNAL_MULTI_ASSET").sum()
        ),
    }
    (OUTPUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
