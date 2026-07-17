from __future__ import annotations

import hashlib
import json
import math
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
import statsmodels.api as sm
import yfinance as yf

from hello_gdelt.hypothesis.statistics import bh_fdr

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "configs" / "research"
OUTPUT = Path(os.environ.get("RESEARCH_OUTPUT", ROOT / "research_output_global_market"))
OUTPUT.mkdir(parents=True, exist_ok=True)

ASSET_CONFIG = CONFIG_DIR / "asset_universe_v1.json"
FACTOR_CONFIG = CONFIG_DIR / "news_factor_registry_v1.json"
HYPOTHESIS_CONFIG = CONFIG_DIR / "hypothesis_registry_pilot_v1.json"
SOURCE_CONFIG = CONFIG_DIR / "data_source_registry_v1.json"

RANDOM_SEED = 20260717
MIN_OBSERVATIONS = 120
ROLLING_WINDOW = 30
PLACEBO_REPEATS = 30
HORIZONS = (1, 5)
PRIMARY_FEATURES = ("count_shock_z", "tone_shock_z")
TARGET_TYPES = ("return", "abs_return")


@dataclass(frozen=True, slots=True)
class SourceRecord:
    source_id: str
    item_id: str
    status: str
    rows: int
    start: str | None
    end: str | None
    sha256: str | None
    note: str | None = None


@dataclass(frozen=True, slots=True)
class TestResult:
    asset_id: str
    symbol: str
    market: str
    factor_id: str
    feature: str
    target_type: str
    horizon: int
    n: int
    beta: float
    standard_error: float
    t_value: float
    p_value: float
    ci_low: float
    ci_high: float
    condition_number: float
    fold_count: int
    fold_sign_agreement: float
    mean_oos_rmse_improvement: float
    median_oos_rmse_improvement: float
    placebo_p_value: float
    q_family: float = math.nan
    q_global: float = math.nan
    decision: str = "INCONCLUSIVE"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def safe_float(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return math.nan
    return result if math.isfinite(result) else math.nan


def download_market_series(
    asset: dict[str, Any], start: str, end: str
) -> tuple[pd.DataFrame, SourceRecord]:
    symbols = [asset["symbol"]]
    if asset.get("fallback_symbol"):
        symbols.append(asset["fallback_symbol"])
    last_error: str | None = None
    for symbol in symbols:
        try:
            frame = yf.download(
                symbol,
                start=start,
                end=(pd.Timestamp(end) + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
                auto_adjust=True,
                progress=False,
                threads=False,
                timeout=45,
            )
            if isinstance(frame.columns, pd.MultiIndex):
                frame.columns = frame.columns.get_level_values(0)
            if frame.empty or "Close" not in frame:
                raise ValueError("empty response or missing Close")
            out = frame.reset_index()[[frame.index.name or "Date", "Close"]].copy()
            out.columns = ["date", "close"]
            out["date"] = pd.to_datetime(out["date"], utc=True).dt.tz_localize(None).dt.normalize()
            out["close"] = pd.to_numeric(out["close"], errors="coerce")
            out = out.dropna().drop_duplicates("date").sort_values("date")
            if len(out) < MIN_OBSERVATIONS:
                raise ValueError(f"only {len(out)} valid rows")
            csv_payload = out.to_csv(index=False).encode()
            return out, SourceRecord(
                source_id="yahoo_finance_pilot",
                item_id=asset["asset_id"],
                status="AVAILABLE" if symbol == asset["symbol"] else "PROXY_FALLBACK",
                rows=len(out),
                start=out["date"].min().date().isoformat(),
                end=out["date"].max().date().isoformat(),
                sha256=sha256_bytes(csv_payload),
                note=None if symbol == asset["symbol"] else f"fallback symbol {symbol}",
            )
        except Exception as exc:  # noqa: BLE001
            last_error = f"{type(exc).__name__}: {exc}"
            time.sleep(1)
    return pd.DataFrame(columns=["date", "close"]), SourceRecord(
        source_id="yahoo_finance_pilot",
        item_id=asset["asset_id"],
        status="SOURCE_FAILED",
        rows=0,
        start=None,
        end=None,
        sha256=None,
        note=last_error,
    )


def gdelt_request(query: str, mode: str, start: str, end: str) -> tuple[dict[str, Any], bytes]:
    params = {
        "query": query,
        "mode": mode,
        "format": "json",
        "startdatetime": pd.Timestamp(start).strftime("%Y%m%d000000"),
        "enddatetime": pd.Timestamp(end).strftime("%Y%m%d235959"),
        "timelinesmooth": "0",
    }
    headers = {"User-Agent": "hello-gdelt-global-market-research/0.1"}
    last_error: Exception | None = None
    for attempt in range(5):
        try:
            response = requests.get(
                "https://api.gdeltproject.org/api/v2/doc/doc",
                params=params,
                headers=headers,
                timeout=120,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise TypeError("GDELT response is not an object")
            return payload, response.content
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(2**attempt)
    raise RuntimeError(f"GDELT request failed: {last_error}")


def parse_timeline(payload: dict[str, Any], *, include_norm: bool) -> pd.DataFrame:
    timeline = payload.get("timeline")
    if not isinstance(timeline, list) or not timeline:
        return pd.DataFrame(columns=["date", "value", "norm"])
    first = timeline[0]
    data = first.get("data", []) if isinstance(first, dict) else []
    rows: list[dict[str, Any]] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        parsed = pd.to_datetime(entry.get("date"), errors="coerce", utc=True)
        if pd.isna(parsed):
            continue
        rows.append(
            {
                "date": parsed.tz_localize(None).normalize(),
                "value": safe_float(entry.get("value")),
                "norm": safe_float(entry.get("norm")) if include_norm else math.nan,
            }
        )
    frame = pd.DataFrame(rows)
    if frame.empty:
        return pd.DataFrame(columns=["date", "value", "norm"])
    return frame.dropna(subset=["date", "value"]).drop_duplicates("date").sort_values("date")


def rolling_z_no_lookahead(series: pd.Series, window: int = ROLLING_WINDOW) -> pd.Series:
    prior = series.shift(1)
    mean = prior.rolling(window, min_periods=max(10, window // 2)).mean()
    std = prior.rolling(window, min_periods=max(10, window // 2)).std(ddof=1)
    return (series - mean) / std.replace(0.0, np.nan)


def download_gdelt_factor(
    factor: dict[str, Any], start: str, end: str
) -> tuple[pd.DataFrame, SourceRecord]:
    try:
        volume_json, volume_raw = gdelt_request(
            factor["query"], "timelinevolraw", start, end
        )
        tone_json, tone_raw = gdelt_request(factor["query"], "timelinetone", start, end)
        volume = parse_timeline(volume_json, include_norm=True).rename(
            columns={"value": "article_count", "norm": "all_articles"}
        )
        tone = parse_timeline(tone_json, include_norm=False)[["date", "value"]].rename(
            columns={"value": "average_tone"}
        )
        frame = volume.merge(tone, on="date", how="outer").sort_values("date")
        frame["article_count"] = pd.to_numeric(frame["article_count"], errors="coerce")
        frame["all_articles"] = pd.to_numeric(frame["all_articles"], errors="coerce")
        frame["average_tone"] = pd.to_numeric(frame["average_tone"], errors="coerce")
        frame["article_share"] = frame["article_count"] / frame["all_articles"].replace(
            0, np.nan
        )
        frame["count_shock_z"] = rolling_z_no_lookahead(np.log1p(frame["article_count"]))
        frame["tone_shock_z"] = rolling_z_no_lookahead(frame["average_tone"])
        frame["factor_id"] = factor["factor_id"]
        frame = frame.dropna(subset=["date"]).drop_duplicates("date")
        if len(frame) < 100:
            raise ValueError(f"only {len(frame)} daily rows")
        digest = hashlib.sha256(volume_raw + b"\n" + tone_raw).hexdigest()
        return frame, SourceRecord(
            source_id="gdelt_doc_v2",
            item_id=factor["factor_id"],
            status="AVAILABLE",
            rows=len(frame),
            start=frame["date"].min().date().isoformat(),
            end=frame["date"].max().date().isoformat(),
            sha256=digest,
        )
    except Exception as exc:  # noqa: BLE001
        return pd.DataFrame(), SourceRecord(
            source_id="gdelt_doc_v2",
            item_id=factor["factor_id"],
            status="SOURCE_FAILED",
            rows=0,
            start=None,
            end=None,
            sha256=None,
            note=f"{type(exc).__name__}: {exc}",
        )


def prepare_asset_frame(frame: pd.DataFrame, asset: dict[str, Any]) -> pd.DataFrame:
    out = frame.copy().sort_values("date")
    out["return_1d"] = np.log(out["close"] / out["close"].shift(1))
    out["lag_return"] = out["return_1d"].shift(1)
    out["lag_abs_return"] = out["return_1d"].abs().shift(1)
    for horizon in HORIZONS:
        forward = np.log(out["close"].shift(-horizon) / out["close"])
        out[f"forward_return_{horizon}d"] = forward
        out[f"forward_abs_return_{horizon}d"] = forward.abs()
    out["asset_id"] = asset["asset_id"]
    out["symbol"] = asset["symbol"]
    out["market"] = asset["market"]
    return out


def align_news(asset_frame: pd.DataFrame, factor_frame: pd.DataFrame) -> pd.DataFrame:
    market = asset_frame.sort_values("date")
    news = factor_frame.sort_values("date")
    return pd.merge_asof(
        market,
        news,
        on="date",
        direction="backward",
        allow_exact_matches=False,
        tolerance=pd.Timedelta(days=4),
    )


def fit_hac(y: np.ndarray, news: np.ndarray, controls: np.ndarray) -> tuple[Any, np.ndarray]:
    x = np.column_stack([news, controls])
    x = sm.add_constant(x, has_constant="add")
    model = sm.OLS(y, x).fit(cov_type="HAC", cov_kwds={"maxlags": 5})
    return model, x


def rmse(actual: np.ndarray, predicted: np.ndarray) -> float:
    return float(np.sqrt(np.mean((actual - predicted) ** 2)))


def walk_forward(
    data: pd.DataFrame, target_col: str, feature_col: str
) -> tuple[int, float, float, list[float]]:
    ordered = data.sort_values("date").reset_index(drop=True)
    n = len(ordered)
    min_train = max(80, int(n * 0.5))
    test_size = max(15, int(n * 0.1))
    improvements: list[float] = []
    fold_betas: list[float] = []
    for train_end in range(min_train, n - test_size + 1, test_size):
        train = ordered.iloc[:train_end]
        test = ordered.iloc[train_end : train_end + test_size]
        controls_train = train[["lag_return", "lag_abs_return"]].to_numpy(float)
        controls_test = test[["lag_return", "lag_abs_return"]].to_numpy(float)
        baseline_x_train = sm.add_constant(controls_train, has_constant="add")
        baseline = sm.OLS(train[target_col].to_numpy(float), baseline_x_train).fit()
        baseline_x_test = sm.add_constant(controls_test, has_constant="add")
        baseline_pred = baseline.predict(baseline_x_test)
        augmented_x_train = sm.add_constant(
            np.column_stack([train[feature_col].to_numpy(float), controls_train]),
            has_constant="add",
        )
        augmented = sm.OLS(train[target_col].to_numpy(float), augmented_x_train).fit()
        augmented_x_test = sm.add_constant(
            np.column_stack([test[feature_col].to_numpy(float), controls_test]),
            has_constant="add",
        )
        augmented_pred = augmented.predict(augmented_x_test)
        baseline_rmse = rmse(test[target_col].to_numpy(float), baseline_pred)
        augmented_rmse = rmse(test[target_col].to_numpy(float), augmented_pred)
        if baseline_rmse > 0:
            improvements.append((baseline_rmse - augmented_rmse) / baseline_rmse)
        fold_betas.append(float(augmented.params[1]))
    if not fold_betas:
        return 0, math.nan, math.nan, []
    full_sign = math.copysign(1.0, float(np.mean(fold_betas)))
    sign_agreement = float(
        np.mean([math.copysign(1.0, value) == full_sign for value in fold_betas])
    )
    return len(fold_betas), sign_agreement, float(np.mean(improvements)), fold_betas


def placebo_p_value(
    data: pd.DataFrame,
    target_col: str,
    feature_col: str,
    observed_beta: float,
    seed_offset: int,
) -> float:
    rng = np.random.default_rng(RANDOM_SEED + seed_offset)
    news = data[feature_col].to_numpy(float)
    y = data[target_col].to_numpy(float)
    controls = data[["lag_return", "lag_abs_return"]].to_numpy(float)
    magnitudes: list[float] = []
    min_shift = max(10, len(news) // 10)
    for _ in range(PLACEBO_REPEATS):
        shift = int(rng.integers(min_shift, max(min_shift + 1, len(news) - min_shift)))
        shifted = np.roll(news, shift)
        model, _ = fit_hac(y, shifted, controls)
        magnitudes.append(abs(float(model.params[1])))
    return float(
        (1 + np.sum(np.asarray(magnitudes) >= abs(observed_beta)))
        / (len(magnitudes) + 1)
    )


def run_test(
    aligned: pd.DataFrame,
    asset: dict[str, Any],
    factor_id: str,
    feature: str,
    target_type: str,
    horizon: int,
    seed_offset: int,
) -> TestResult | None:
    target_col = f"forward_{target_type}_{horizon}d"
    columns = ["date", target_col, feature, "lag_return", "lag_abs_return"]
    data = aligned[columns].replace([np.inf, -np.inf], np.nan).dropna().copy()
    if len(data) < MIN_OBSERVATIONS:
        return None
    y = data[target_col].to_numpy(float)
    news = data[feature].to_numpy(float)
    controls = data[["lag_return", "lag_abs_return"]].to_numpy(float)
    model, design = fit_hac(y, news, controls)
    beta = float(model.params[1])
    se = float(model.bse[1])
    fold_count, sign_agreement, mean_improvement, improvements = walk_forward(
        data, target_col, feature
    )
    placebo = placebo_p_value(data, target_col, feature, beta, seed_offset)
    return TestResult(
        asset_id=asset["asset_id"],
        symbol=asset["symbol"],
        market=asset["market"],
        factor_id=factor_id,
        feature=feature,
        target_type=target_type,
        horizon=horizon,
        n=len(data),
        beta=beta,
        standard_error=se,
        t_value=float(model.tvalues[1]),
        p_value=float(model.pvalues[1]),
        ci_low=beta - 1.96 * se,
        ci_high=beta + 1.96 * se,
        condition_number=float(np.linalg.cond(design)),
        fold_count=fold_count,
        fold_sign_agreement=sign_agreement,
        mean_oos_rmse_improvement=mean_improvement,
        median_oos_rmse_improvement=float(np.median(improvements))
        if improvements
        else math.nan,
        placebo_p_value=placebo,
    )


def apply_fdr_and_decisions(results: list[TestResult]) -> list[TestResult]:
    raw = [asdict(item) for item in results]
    global_q = bh_fdr([item["p_value"] for item in raw])
    for item, q_value in zip(raw, global_q, strict=True):
        item["q_global"] = q_value
    family_groups: dict[tuple[str, str, int], list[int]] = {}
    for index, item in enumerate(raw):
        key = (item["feature"], item["target_type"], item["horizon"])
        family_groups.setdefault(key, []).append(index)
    for indices in family_groups.values():
        family_q = bh_fdr([raw[index]["p_value"] for index in indices])
        for index, q_value in zip(indices, family_q, strict=True):
            raw[index]["q_family"] = q_value
    for item in raw:
        gates = {
            "fdr": item["q_family"] <= 0.05,
            "oos": item["mean_oos_rmse_improvement"] > 0,
            "stability": item["fold_sign_agreement"] >= 0.60,
            "placebo": item["placebo_p_value"] <= 0.05,
            "conditioning": item["condition_number"] < 1e6,
        }
        item["decision"] = "SUPPORTED" if all(gates.values()) else "INCONCLUSIVE"
    return [TestResult(**item) for item in raw]


def plot_outputs(
    asset_audit: list[SourceRecord],
    factors: dict[str, pd.DataFrame],
    results: pd.DataFrame,
) -> None:
    available = [record for record in asset_audit if record.rows > 0]
    if available:
        frame = pd.DataFrame([asdict(record) for record in available]).sort_values("rows")
        plt.figure(figsize=(10, 7))
        plt.barh(frame["item_id"], frame["rows"])
        plt.xlabel("Valid trading days")
        plt.title("Pilot multi-market data coverage")
        plt.tight_layout()
        plt.savefig(OUTPUT / "fig01_asset_coverage.png", dpi=180)
        plt.close()

    if factors:
        plt.figure(figsize=(12, 7))
        for factor_id, frame in factors.items():
            valid = frame.dropna(subset=["count_shock_z"])
            plt.plot(valid["date"], valid["count_shock_z"], label=factor_id, linewidth=1)
        plt.axhline(0, linewidth=0.8)
        plt.ylabel("Article-count shock z-score")
        plt.title("GDELT news attention shocks")
        plt.legend(ncol=2, fontsize=8)
        plt.tight_layout()
        plt.savefig(OUTPUT / "fig02_gdelt_factor_shocks.png", dpi=180)
        plt.close()

    if results.empty:
        return
    subset = results[
        (results["feature"] == "count_shock_z")
        & (results["target_type"] == "abs_return")
        & (results["horizon"] == 1)
    ]
    if not subset.empty:
        matrix = subset.pivot(index="asset_id", columns="factor_id", values="t_value")
        plt.figure(figsize=(11, 10))
        image = plt.imshow(matrix.fillna(0).to_numpy(), aspect="auto")
        plt.colorbar(image, label="HAC t-value")
        plt.xticks(range(len(matrix.columns)), matrix.columns, rotation=40, ha="right")
        plt.yticks(range(len(matrix.index)), matrix.index)
        plt.title("News attention and next-day absolute return")
        plt.tight_layout()
        plt.savefig(OUTPUT / "fig03_volatility_t_heatmap.png", dpi=180)
        plt.close()

    top = results.sort_values("p_value").head(25).sort_values("beta")
    if not top.empty:
        labels = top["asset_id"] + " | " + top["factor_id"] + " | " + top["target_type"]
        errors = np.vstack([top["beta"] - top["ci_low"], top["ci_high"] - top["beta"]])
        plt.figure(figsize=(11, 10))
        plt.errorbar(top["beta"], range(len(top)), xerr=errors, fmt="o", capsize=2)
        plt.axvline(0, linewidth=0.8)
        plt.yticks(range(len(top)), labels, fontsize=7)
        plt.xlabel("Coefficient and 95% confidence interval")
        plt.title("Top 25 nominal results before final gates")
        plt.tight_layout()
        plt.savefig(OUTPUT / "fig04_top_coefficients.png", dpi=180)
        plt.close()

    plt.figure(figsize=(9, 6))
    plt.hist(results["mean_oos_rmse_improvement"].dropna(), bins=40)
    plt.axvline(0, linewidth=1)
    plt.xlabel("Out-of-sample RMSE improvement")
    plt.ylabel("Number of tests")
    plt.title("Incremental out-of-sample value of news factors")
    plt.tight_layout()
    plt.savefig(OUTPUT / "fig05_oos_improvement_distribution.png", dpi=180)
    plt.close()

    counts = results["decision"].value_counts()
    plt.figure(figsize=(7, 5))
    plt.bar(counts.index, counts.values)
    plt.ylabel("Number of tests")
    plt.title("Hypothesis Lab decisions")
    plt.tight_layout()
    plt.savefig(OUTPUT / "fig06_decision_counts.png", dpi=180)
    plt.close()


def write_report(
    asset_audit: list[SourceRecord],
    factor_audit: list[SourceRecord],
    results: pd.DataFrame,
    start: str,
    end: str,
) -> None:
    available_assets = sum(record.rows > 0 for record in asset_audit)
    available_factors = sum(record.rows > 0 for record in factor_audit)
    supported = int((results["decision"] == "SUPPORTED").sum()) if not results.empty else 0
    lines = [
        "# GDELT 全球新闻—多市场金融影响：首轮真实数据试验",
        "",
        f"研究窗口：{start} 至 {end}",
        "",
        "## 摘要",
        "",
        f"首轮试验成功获得 {available_assets} 个资产和 {available_factors} 个 GDELT 新闻因子。",
        f"完成 {len(results)} 项确认性检验，其中 {supported} 项同时通过 FDR、样本外、稳定性和安慰剂门禁。",
        "该报告是完整 100 页研究的第一阶段证据，不代表最终长样本结论。",
        "",
        "## 数据质量",
        "",
        "### 行情源审计",
        "",
        "|资产|状态|行数|开始|结束|说明|",
        "|---|---:|---:|---|---|---|",
    ]
    for record in asset_audit:
        lines.append(
            f"|{record.item_id}|{record.status}|{record.rows}|{record.start or ''}|"
            f"{record.end or ''}|{record.note or ''}|"
        )
    lines.extend(
        [
            "",
            "### GDELT 因子审计",
            "",
            "|因子|状态|行数|开始|结束|说明|",
            "|---|---:|---:|---|---|---|",
        ]
    )
    for record in factor_audit:
        lines.append(
            f"|{record.item_id}|{record.status}|{record.rows}|{record.start or ''}|"
            f"{record.end or ''}|{record.note or ''}|"
        )
    lines.extend(["", "## 核心裁决", ""])
    if results.empty:
        lines.append("没有形成满足最小样本量的检验。")
    else:
        summary = (
            results.groupby(["market", "target_type", "decision"])
            .size()
            .reset_index(name="count")
            .sort_values(["market", "target_type", "decision"])
        )
        lines.extend(["|市场|目标|裁决|数量|", "|---|---|---|---:|"])
        for row in summary.itertuples(index=False):
            lines.append(f"|{row.market}|{row.target_type}|{row.decision}|{row.count}|")
        lines.extend(["", "### 通过全部门禁的结果", ""])
        confirmed = results[results["decision"] == "SUPPORTED"].sort_values("q_family")
        if confirmed.empty:
            lines.append(
                "没有检验同时通过全部门禁。该结果应解读为首轮样本尚未发现稳健规律，"
                "而不是新闻完全无效。"
            )
        else:
            lines.extend(
                [
                    "|资产|新闻因子|特征|目标|h|β|q|OOS改善|安慰剂p|",
                    "|---|---|---|---|---:|---:|---:|---:|---:|",
                ]
            )
            for row in confirmed.head(50).itertuples(index=False):
                lines.append(
                    f"|{row.asset_id}|{row.factor_id}|{row.feature}|{row.target_type}|"
                    f"{row.horizon}|{row.beta:.6g}|{row.q_family:.4g}|"
                    f"{row.mean_oos_rmse_improvement:.2%}|{row.placebo_p_value:.4g}|"
                )
        lines.extend(["", "### 名义显著但未通过全部门禁的前 30 项", ""])
        nominal = results.sort_values("p_value").head(30)
        lines.extend(
            [
                "|资产|因子|目标|h|β|p|q|OOS改善|安慰剂p|裁决|",
                "|---|---|---|---:|---:|---:|---:|---:|---:|---|",
            ]
        )
        for row in nominal.itertuples(index=False):
            lines.append(
                f"|{row.asset_id}|{row.factor_id}|{row.target_type}|{row.horizon}|"
                f"{row.beta:.6g}|{row.p_value:.4g}|{row.q_family:.4g}|"
                f"{row.mean_oos_rmse_improvement:.2%}|{row.placebo_p_value:.4g}|"
                f"{row.decision}|"
            )
    lines.extend(
        [
            "",
            "## 方法边界",
            "",
            "1. 行情来自公开试验源，不能替代最终交易所或许可数据；",
            "2. GDELT DOC API 用于近一年受控试验，长样本将切换至原始 Events/EventMentions/GKG；",
            "3. 当前使用前一 UTC 日新闻进行保守对齐，尚未细分盘前、盘中和盘后；",
            "4. 期货连续合约来自数据提供方定义，生产研究需自建换月与展期规则；",
            "5. 所有名义显著结果只有在通过全部门禁后才被列为支持。",
        ]
    )
    (OUTPUT / "pilot_report_cn.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    assets_config = load_json(ASSET_CONFIG)
    factors_config = load_json(FACTOR_CONFIG)
    start = assets_config["research_window"]["start"]
    end = assets_config["research_window"]["end"]
    snapshots = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (ASSET_CONFIG, FACTOR_CONFIG, HYPOTHESIS_CONFIG, SOURCE_CONFIG)
    }

    asset_frames: dict[str, pd.DataFrame] = {}
    asset_audit: list[SourceRecord] = []
    for asset in assets_config["assets"]:
        frame, record = download_market_series(asset, start, end)
        asset_audit.append(record)
        if not frame.empty:
            asset_frames[asset["asset_id"]] = prepare_asset_frame(frame, asset)

    factor_frames: dict[str, pd.DataFrame] = {}
    factor_audit: list[SourceRecord] = []
    for factor in factors_config["factors"]:
        frame, record = download_gdelt_factor(factor, start, end)
        factor_audit.append(record)
        if not frame.empty:
            factor_frames[factor["factor_id"]] = frame

    pd.DataFrame([asdict(record) for record in asset_audit + factor_audit]).to_json(
        OUTPUT / "source_audit.json", orient="records", indent=2
    )

    if asset_frames:
        pd.concat(asset_frames.values(), ignore_index=True).to_csv(
            OUTPUT / "market_prices.csv", index=False
        )
    if factor_frames:
        pd.concat(factor_frames.values(), ignore_index=True).to_csv(
            OUTPUT / "gdelt_factors.csv", index=False
        )

    assets_by_id = {asset["asset_id"]: asset for asset in assets_config["assets"]}
    test_results: list[TestResult] = []
    analysis_panel_rows: list[pd.DataFrame] = []
    seed_offset = 0
    for asset_id, asset_frame in asset_frames.items():
        asset = assets_by_id[asset_id]
        for factor_id, factor_frame in factor_frames.items():
            aligned = align_news(asset_frame, factor_frame)
            panel_slice = aligned.copy()
            panel_slice["asset_id"] = asset_id
            panel_slice["factor_id"] = factor_id
            analysis_panel_rows.append(panel_slice)
            for feature in PRIMARY_FEATURES:
                for target_type in TARGET_TYPES:
                    for horizon in HORIZONS:
                        result = run_test(
                            aligned,
                            asset,
                            factor_id,
                            feature,
                            target_type,
                            horizon,
                            seed_offset,
                        )
                        seed_offset += 1
                        if result is not None:
                            test_results.append(result)

    if analysis_panel_rows:
        pd.concat(analysis_panel_rows, ignore_index=True).to_csv(
            OUTPUT / "analysis_panel.csv", index=False
        )

    final_results = apply_fdr_and_decisions(test_results) if test_results else []
    results_frame = pd.DataFrame([asdict(item) for item in final_results])
    results_frame.to_csv(OUTPUT / "result_registry.csv", index=False)

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "research_window": {"start": start, "end": end},
        "config_sha256": snapshots,
        "available_assets": len(asset_frames),
        "available_factors": len(factor_frames),
        "test_count": len(results_frame),
        "supported_count": int((results_frame["decision"] == "SUPPORTED").sum())
        if not results_frame.empty
        else 0,
        "source_failures": [
            asdict(record)
            for record in asset_audit + factor_audit
            if record.status == "SOURCE_FAILED"
        ],
    }
    (OUTPUT / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    plot_outputs(asset_audit, factor_frames, results_frame)
    write_report(asset_audit, factor_audit, results_frame, start, end)
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if len(asset_frames) < 8:
        raise SystemExit("fewer than eight market series available")
    if len(factor_frames) < 3:
        raise SystemExit("fewer than three GDELT factors available")
    if results_frame.empty:
        raise SystemExit("no valid hypothesis tests produced")


if __name__ == "__main__":
    main()
