from __future__ import annotations

import hashlib
import json
import math
import os
import re
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from huggingface_hub import HfApi, hf_hub_download

import run_stage1 as base
from hello_gdelt.hypothesis.statistics import bh_fdr

REPO_ID = "AmritJain/gdelt-india-research-datasets"
OUTPUT = Path(os.environ.get("INDIA_FX_OUTPUT", "india_fx_output"))
RAW = OUTPUT / "raw"
FIGURES = OUTPUT / "figures"
MIN_OBSERVATIONS = 120


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def read_csv_robust(path: Path) -> pd.DataFrame:
    errors: list[str] = []
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            frame = pd.read_csv(path, encoding=encoding, low_memory=False)
            frame.columns = [str(column).strip() for column in frame.columns]
            return frame
        except Exception as exc:
            errors.append(f"{encoding}: {exc}")
    raise RuntimeError(f"cannot read {path}: {' | '.join(errors)}")


def score_column(column: str, positives: tuple[str, ...], negatives: tuple[str, ...]) -> int:
    name = normalize_name(column)
    if any(token in name for token in negatives):
        return -1000
    score = 0
    for token in positives:
        normalized = normalize_name(token)
        if name == normalized:
            score += 100
        elif normalized in name:
            score += 20
    if pd.api.types.is_numeric_dtype:
        score += 0
    return score


def choose_column(
    frame: pd.DataFrame,
    positives: tuple[str, ...],
    negatives: tuple[str, ...] = (),
) -> str | None:
    candidates: list[tuple[int, str]] = []
    for column in frame.columns:
        if not pd.api.types.is_numeric_dtype(frame[column]):
            continue
        score = score_column(str(column), positives, negatives)
        if score > 0:
            candidates.append((score, str(column)))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (-item[0], item[1]))
    return candidates[0][1]


def choose_date_column(frame: pd.DataFrame) -> str:
    ordered = sorted(
        frame.columns,
        key=lambda column: (
            0 if normalize_name(str(column)) in {"date", "day", "event_date"} else 1,
            0 if "date" in normalize_name(str(column)) else 1,
            str(column),
        ),
    )
    for column in ordered:
        parsed = pd.to_datetime(frame[column], errors="coerce", utc=True)
        if parsed.notna().mean() >= 0.75:
            return str(column)
    raise ValueError("no date-like column with at least 75% parseability")


def inspect_file(path: Path, repo_path: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    frame = read_csv_robust(path)
    audit = {
        "repo_path": repo_path,
        "local_name": path.name,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "rows": int(len(frame)),
        "columns": [str(column) for column in frame.columns],
        "duplicate_rows": int(frame.duplicated().sum()),
        "missing_fraction": {
            str(column): float(frame[column].isna().mean()) for column in frame.columns
        },
    }
    return frame, audit


def list_and_download() -> tuple[list[tuple[str, Path]], list[dict[str, Any]]]:
    api = HfApi()
    info = api.dataset_info(REPO_ID, files_metadata=True)
    siblings = list(info.siblings or [])
    metadata = {
        sibling.rfilename: int(sibling.size or 0)
        for sibling in siblings
        if sibling.rfilename
    }
    all_files = sorted(metadata)
    (OUTPUT / "repo_file_index.json").write_text(
        json.dumps(
            [{"path": path, "size": metadata[path]} for path in all_files],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    priority_basenames = [
        "combined_goldstein_exchange_rates.csv",
        "exchange_rate_goldstein_merged.csv",
        "political_news_exchange_merged.csv",
        "india_daily_goldstein_averages.csv",
        "usd_inr_exchange_rates_1year.csv",
        "Super_Master_Dataset.csv",
    ]
    selected: list[str] = []
    for basename in priority_basenames:
        matches = [path for path in all_files if Path(path).name == basename]
        matches.sort(key=lambda path: metadata.get(path, 0))
        for match in matches:
            size = metadata.get(match, 0)
            if size == 0 or size <= 150 * 1024 * 1024:
                selected.append(match)
                break
    if not selected:
        raise RuntimeError("none of the preregistered candidate files were found")
    RAW.mkdir(parents=True, exist_ok=True)
    downloaded: list[tuple[str, Path]] = []
    download_audit: list[dict[str, Any]] = []
    for repo_path in selected:
        local = Path(
            hf_hub_download(
                repo_id=REPO_ID,
                repo_type="dataset",
                filename=repo_path,
                local_dir=RAW,
            )
        )
        downloaded.append((repo_path, local))
        download_audit.append(
            {
                "repo_path": repo_path,
                "declared_size": metadata.get(repo_path, 0),
                "local_size": local.stat().st_size,
                "sha256": sha256_file(local),
            }
        )
        print(f"DOWNLOADED {repo_path}: {local.stat().st_size} bytes")
    return downloaded, download_audit


def identify_fields(frame: pd.DataFrame) -> dict[str, str | None]:
    return {
        "date": choose_date_column(frame),
        "goldstein": choose_column(
            frame,
            ("avg_goldstein", "goldstein_scale", "goldstein"),
            ("correlation", "p_value"),
        ),
        "tone": choose_column(
            frame,
            ("avg_tone", "average_tone", "tone"),
            ("correlation", "p_value"),
        ),
        "intensity": choose_column(
            frame,
            (
                "total_mentions",
                "num_mentions",
                "event_count",
                "article_count",
                "crisis_events",
                "mentions",
            ),
            ("correlation", "p_value"),
        ),
        "return": choose_column(
            frame,
            ("exchange_rate_return", "fx_return", "usd_inr_return", "return"),
            ("goldstein", "tone", "correlation", "forecast", "predicted"),
        ),
        "price": choose_column(
            frame,
            (
                "usd_inr_exchange_rate",
                "exchange_rate",
                "usd_inr",
                "close",
                "price",
                "rate",
            ),
            (
                "goldstein",
                "tone",
                "correlation",
                "return",
                "change",
                "forecast",
                "predicted",
                "interest_rate",
            ),
        ),
    }


def prepare_one(frame: pd.DataFrame, fields: dict[str, str | None]) -> pd.DataFrame:
    date_column = str(fields["date"])
    output = pd.DataFrame(
        {
            "date": pd.to_datetime(frame[date_column], errors="coerce", utc=True)
            .dt.tz_convert(None)
            .dt.normalize()
        }
    )
    for key in ("goldstein", "tone", "intensity"):
        column = fields.get(key)
        if column:
            output[key] = pd.to_numeric(frame[column], errors="coerce")
    return_column = fields.get("return")
    price_column = fields.get("price")
    if return_column:
        output["return"] = pd.to_numeric(frame[return_column], errors="coerce")
    elif price_column:
        output["price"] = pd.to_numeric(frame[price_column], errors="coerce")
    output = output.dropna(subset=["date"]).sort_values("date")
    numeric = [column for column in output.columns if column != "date"]
    aggregations = {column: "mean" for column in numeric}
    return output.groupby("date", as_index=False).agg(aggregations)


def select_or_merge(
    inspected: list[tuple[str, pd.DataFrame, dict[str, Any]]]
) -> tuple[pd.DataFrame, dict[str, Any]]:
    candidates: list[tuple[int, str, pd.DataFrame, dict[str, str | None]]] = []
    for repo_path, frame, _ in inspected:
        fields = identify_fields(frame)
        news_count = sum(fields[key] is not None for key in ("goldstein", "tone", "intensity"))
        market_count = int(fields["return"] is not None or fields["price"] is not None)
        candidates.append((news_count * 10 + market_count * 20, repo_path, frame, fields))
    candidates.sort(key=lambda item: (-item[0], item[1]))
    for score, repo_path, frame, fields in candidates:
        if score >= 30:
            panel = prepare_one(frame, fields)
            return panel, {
                "method": "single_merged_file",
                "source_files": [repo_path],
                "field_mapping": fields,
            }
    news_candidates = [item for item in candidates if item[0] >= 10 and item[0] < 30]
    market_candidates = [item for item in candidates if item[0] >= 20 and item[0] % 10 == 0]
    if not news_candidates or not market_candidates:
        raise RuntimeError(
            "could not find either a merged file or separate news and market files"
        )
    _, news_path, news_frame, news_fields = news_candidates[0]
    _, market_path, market_frame, market_fields = market_candidates[0]
    news = prepare_one(news_frame, news_fields)
    market = prepare_one(market_frame, market_fields)
    panel = market.merge(news, on="date", how="inner", suffixes=("_market", "_news"))
    return panel, {
        "method": "date_merge",
        "source_files": [market_path, news_path],
        "field_mapping": {"market": market_fields, "news": news_fields},
    }


def finalize_panel(panel: pd.DataFrame) -> pd.DataFrame:
    panel = panel.sort_values("date").drop_duplicates("date").copy()
    if "return" not in panel.columns:
        price_candidates = [column for column in panel.columns if column.startswith("price")]
        if not price_candidates:
            raise ValueError("selected panel has neither return nor price")
        price = pd.to_numeric(panel[price_candidates[0]], errors="coerce")
        panel["return"] = np.log(price.where(price > 0)).diff()
    panel["return"] = pd.to_numeric(panel["return"], errors="coerce")
    if panel["return"].abs().quantile(0.99) > 0.25:
        panel["return"] = panel["return"] / 100.0
    panel["abs_return"] = panel["return"].abs()
    panel["next_return"] = panel["return"].shift(-1)
    panel["next_abs_return"] = panel["abs_return"].shift(-1)
    for feature in ("goldstein", "tone", "intensity"):
        candidates = [column for column in panel.columns if column == feature or column.startswith(feature + "_")]
        if candidates:
            selected = candidates[0]
            panel[feature] = pd.to_numeric(panel[selected], errors="coerce")
            mean = panel[feature].rolling(30, min_periods=14).mean()
            std = panel[feature].rolling(30, min_periods=14).std(ddof=0).replace(0, np.nan)
            panel[feature + "_z30"] = (panel[feature] - mean) / std
    return panel


def test_feature(
    panel: pd.DataFrame,
    feature: str,
    target: str,
    expected: str,
) -> dict[str, Any]:
    required = ["return", "abs_return", "next_return", "next_abs_return", feature]
    sample = panel.dropna(subset=required).reset_index(drop=True)
    result: dict[str, Any] = {
        "feature": feature,
        "target": target,
        "expected": expected,
        "nobs": int(len(sample)),
        "status": "DATA_INSUFFICIENT",
        "decision": "DATA_INSUFFICIENT",
    }
    if len(sample) < MIN_OBSERVATIONS:
        return result
    fit = base.fit_hac(sample[["return", "abs_return", feature]], sample[target], 5)
    beta = float(fit.params[feature])
    ci_low, ci_high = [float(value) for value in fit.conf_int().loc[feature]]
    oos = base.walk_forward(sample, target, feature)
    fold_betas = json.loads(str(oos.get("fold_betas_json", "[]")))
    stability = (
        float(np.mean([math.copysign(1, value) == math.copysign(1, beta) for value in fold_betas]))
        if fold_betas and beta != 0
        else math.nan
    )
    placebo = base.placebo_p_value(
        sample,
        target,
        feature,
        beta,
        100,
        base.stable_seed("india_fx", feature, target),
    )
    result.update(
        {
            "status": "TESTED",
            "beta": beta,
            "standard_error_hac": float(fit.bse[feature]),
            "p_value": float(fit.pvalues[feature]),
            "ci_low": ci_low,
            "ci_high": ci_high,
            "placebo_p": placebo,
            "oos_improvement": float(oos["oos_improvement"]),
            "baseline_rmse": float(oos["baseline_rmse"]),
            "full_rmse": float(oos["full_rmse"]),
            "folds": int(oos["folds"]),
            "sign_stability": stability,
            "fold_betas_json": oos.get("fold_betas_json", "[]"),
        }
    )
    return result


def write_report(
    results: pd.DataFrame,
    selection: dict[str, Any],
    file_audits: list[dict[str, Any]],
) -> None:
    tested = results[results["status"] == "TESTED"]
    supported = tested[tested["decision"] == "SUPPORTED_EXTERNAL_REPLICATION"]
    lines = [
        "# GDELT—USD/INR 外部样本复验结果",
        "",
        "## 数据定位",
        "",
        "该分析使用第三方整理的公开 GDELT—印度—USD/INR 数据，仅作为外部真实数据复验。它不替代原始 GDELT 抽取，也不因发布者提供了既有分析结果而采用其结论。",
        "",
        f"- 数据选择方法：`{selection['method']}`；",
        f"- 来源文件：{', '.join(selection['source_files'])}；",
        f"- 下载并审计文件数：{len(file_audits)}；",
        f"- 完成预注册检验数：{len(tested)}；",
        f"- 通过全部门禁数：{len(supported)}。",
        "",
        "## 严格结果",
        "",
        results.to_markdown(index=False, floatfmt=".5g"),
        "",
        "## 解释边界",
        "",
        "任何未同时通过 FDR、循环移位安慰剂、样本外改善和方向稳定性的关系，均不得表述为可复现规律。第三方字段口径和时间戳未被原始数据重新审计，因此即使通过，也只能称为外部复验候选。",
        "",
    ]
    (OUTPUT / "india_fx_replication_report.md").write_text("\n".join(lines), encoding="utf-8")


def save_figures(panel: pd.DataFrame, results: pd.DataFrame) -> None:
    FIGURES.mkdir(parents=True, exist_ok=True)
    available = [feature for feature in ("goldstein_z30", "tone_z30", "intensity_z30") if feature in panel.columns]
    if available:
        fig, axes = plt.subplots(len(available) + 1, 1, figsize=(12, 3 * (len(available) + 1)), sharex=True)
        axes_array = np.atleast_1d(axes)
        axes_array[0].plot(panel["date"], panel["return"])
        axes_array[0].set_title("USD/INR daily return")
        for axis, feature in zip(axes_array[1:], available, strict=False):
            axis.plot(panel["date"], panel[feature])
            axis.set_title(feature)
        fig.tight_layout()
        fig.savefig(FIGURES / "01_panel_timeseries.png", dpi=180)
        plt.close(fig)
    tested = results[results["status"] == "TESTED"].copy()
    if not tested.empty:
        labels = tested["feature"] + " → " + tested["target"]
        fig, ax = plt.subplots(figsize=(10, max(4, len(tested) * 0.65)))
        ax.errorbar(
            tested["beta"],
            np.arange(len(tested)),
            xerr=[tested["beta"] - tested["ci_low"], tested["ci_high"] - tested["beta"]],
            fmt="o",
        )
        ax.axvline(0, linewidth=1)
        ax.set_yticks(np.arange(len(tested)), labels)
        ax.set_title("HAC coefficients and 95% confidence intervals")
        fig.tight_layout()
        fig.savefig(FIGURES / "02_coefficients.png", dpi=180)
        plt.close(fig)


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    downloaded, download_audit = list_and_download()
    inspected: list[tuple[str, pd.DataFrame, dict[str, Any]]] = []
    file_audits: list[dict[str, Any]] = []
    for repo_path, local in downloaded:
        frame, audit = inspect_file(local, repo_path)
        fields = identify_fields(frame)
        audit["detected_fields"] = fields
        inspected.append((repo_path, frame, audit))
        file_audits.append(audit)
    (OUTPUT / "file_audit.json").write_text(
        json.dumps(file_audits, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    panel, selection = select_or_merge(inspected)
    panel = finalize_panel(panel)
    panel.to_csv(OUTPUT / "analysis_panel.csv", index=False)
    specs = []
    if "goldstein_z30" in panel.columns:
        specs.append(("goldstein_z30", "next_return", "nonzero"))
    if "tone_z30" in panel.columns:
        specs.append(("tone_z30", "next_return", "nonzero"))
    if "intensity_z30" in panel.columns:
        specs.append(("intensity_z30", "next_abs_return", "positive"))
    if not specs:
        raise RuntimeError("selected panel contains no preregistered GDELT features")
    results = pd.DataFrame([test_feature(panel, *spec) for spec in specs])
    results["q_value"] = math.nan
    tested_indices = results.index[results["status"] == "TESTED"].tolist()
    if tested_indices:
        results.loc[tested_indices, "q_value"] = bh_fdr(
            results.loc[tested_indices, "p_value"].astype(float).tolist()
        )
    decisions: list[str] = []
    for row in results.to_dict("records"):
        if row["status"] != "TESTED":
            decisions.append("DATA_INSUFFICIENT")
            continue
        direction_ok = row["expected"] == "nonzero" or float(row["beta"]) > 0
        supported = (
            direction_ok
            and float(row["q_value"]) <= 0.10
            and float(row["placebo_p"]) <= 0.10
            and float(row["oos_improvement"]) > 0
            and float(row["sign_stability"]) >= 0.60
        )
        decisions.append("SUPPORTED_EXTERNAL_REPLICATION" if supported else "INCONCLUSIVE")
    results["decision"] = decisions
    results.to_csv(OUTPUT / "india_fx_results.csv", index=False)
    (OUTPUT / "selection.json").write_text(
        json.dumps(selection, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    save_figures(panel, results)
    write_report(results, selection, file_audits)
    manifest = {
        "study_id": "gdelt-india-usdinr-external-replication",
        "repo_id": REPO_ID,
        "selection": selection,
        "download_audit": download_audit,
        "panel_rows": int(len(panel)),
        "panel_start": str(panel["date"].min().date()),
        "panel_end": str(panel["date"].max().date()),
        "decisions": results["decision"].value_counts().to_dict(),
        "files": {},
    }
    for path in sorted(OUTPUT.rglob("*")):
        if path.is_file() and path.name != "manifest.json":
            manifest["files"][str(path.relative_to(OUTPUT))] = {
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
    (OUTPUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest["decisions"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
