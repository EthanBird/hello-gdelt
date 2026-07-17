from __future__ import annotations

import hashlib
import json
import math
import os
import random
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm

from hello_gdelt.hypothesis.statistics import bh_fdr

ROOT = Path(__file__).resolve().parent
OUTPUT = Path(os.environ.get("MARKET_RESEARCH_OUTPUT", "market_research_output"))
RAW = OUTPUT / "raw"
FIGURES = OUTPUT / "figures"
START = "2025-07-18"
END = "2026-07-16"
START_GDELT = "20250718000000"
END_GDELT = "20260716235959"
USER_AGENT = "hello-gdelt-market-research/1.0 (+https://github.com/EthanBird/hello-gdelt)"


@dataclass(frozen=True)
class GateConfig:
    fdr_alpha: float
    placebo_alpha: float
    min_oos_improvement: float
    min_sign_stability: float
    min_observations: int
    placebo_repetitions: int
    hac_lags: int


def stable_seed(*parts: str) -> int:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % (2**32 - 1)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def http_json(url: str, *, retries: int = 5) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310
                payload = response.read()
            parsed = json.loads(payload.decode("utf-8-sig"))
            if not isinstance(parsed, dict):
                raise ValueError("JSON root is not an object")
            return parsed
        except Exception as exc:
            last_error = exc
            time.sleep(min(30, 2**attempt))
    raise RuntimeError(f"failed to fetch {url}: {last_error}")


def timeline_frame(payload: dict[str, Any], value_name: str) -> pd.DataFrame:
    timeline = payload.get("timeline")
    if not isinstance(timeline, list) or not timeline:
        raise ValueError("GDELT response has no timeline")
    candidates: list[dict[str, Any]] = []
    for series in timeline:
        if isinstance(series, dict) and isinstance(series.get("data"), list):
            candidates.extend(item for item in series["data"] if isinstance(item, dict))
    if not candidates:
        raise ValueError("GDELT response timeline has no data")
    rows: list[dict[str, Any]] = []
    for item in candidates:
        date_value = item.get("date")
        value = item.get("value")
        if date_value is None or value is None:
            continue
        row: dict[str, Any] = {
            "date": pd.to_datetime(date_value, utc=True).tz_convert(None).normalize()
        }
        row[value_name] = float(value)
        if item.get("norm") is not None:
            row["norm"] = float(item["norm"])
        rows.append(row)
    frame = pd.DataFrame(rows)
    if frame.empty:
        raise ValueError("GDELT timeline produced no parseable rows")
    aggregations = {value_name: "mean"}
    if "norm" in frame.columns:
        aggregations["norm"] = "mean"
    return frame.groupby("date", as_index=False).agg(aggregations).sort_values("date")


def gdelt_url(query: str, mode: str) -> str:
    params = {
        "query": query,
        "mode": mode,
        "format": "json",
        "startdatetime": START_GDELT,
        "enddatetime": END_GDELT,
        "timelinesmooth": "0",
    }
    return "https://api.gdeltproject.org/api/v2/doc/doc?" + urllib.parse.urlencode(params)


def fetch_gdelt_topics(
    topics: dict[str, str],
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    all_frames: list[pd.DataFrame] = []
    audit: list[dict[str, Any]] = []
    for topic_id, query in topics.items():
        topic_dir = RAW / "gdelt" / topic_id
        topic_dir.mkdir(parents=True, exist_ok=True)
        vol_url = gdelt_url(query, "timelinevolraw")
        tone_url = gdelt_url(query, "timelinetone")
        vol_payload = http_json(vol_url)
        time.sleep(1.0)
        tone_payload = http_json(tone_url)
        vol_path = topic_dir / "timelinevolraw.json"
        tone_path = topic_dir / "timelinetone.json"
        vol_path.write_text(
            json.dumps(vol_payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tone_path.write_text(
            json.dumps(tone_payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        vol = timeline_frame(vol_payload, "article_count")
        tone = timeline_frame(tone_payload, "tone")[["date", "tone"]]
        frame = vol.merge(tone, on="date", how="outer").sort_values("date")
        if "norm" not in frame.columns:
            raise ValueError(f"{topic_id}: TimelineVolRaw did not include norm")
        frame["volume_share"] = np.where(
            frame["norm"] > 0, frame["article_count"] / frame["norm"], np.nan
        )
        for column in ["volume_share", "tone"]:
            rolling_mean = frame[column].rolling(30, min_periods=14).mean()
            rolling_std = frame[column].rolling(30, min_periods=14).std(ddof=0)
            frame[f"{column}_z30"] = (
                frame[column] - rolling_mean
            ) / rolling_std.replace(0, np.nan)
        frame["negative_pressure"] = np.maximum(
            frame["volume_share_z30"], 0.0
        ) * np.maximum(-frame["tone_z30"], 0.0)
        frame["topic"] = topic_id
        all_frames.append(frame)
        audit.append(
            {
                "topic": topic_id,
                "query": query,
                "rows": int(len(frame)),
                "start": str(frame["date"].min().date()),
                "end": str(frame["date"].max().date()),
                "missing_volume": int(frame["volume_share"].isna().sum()),
                "missing_tone": int(frame["tone"].isna().sum()),
                "vol_sha256": sha256_file(vol_path),
                "tone_sha256": sha256_file(tone_path),
                "vol_url": vol_url,
                "tone_url": tone_url,
            }
        )
        print(f"GDELT {topic_id}: {len(frame)} daily rows")
    combined = pd.concat(all_frames, ignore_index=True)
    combined.to_csv(OUTPUT / "gdelt_topic_daily.csv", index=False)
    return combined, audit


def extract_close(downloaded: pd.DataFrame) -> pd.Series:
    if downloaded.empty:
        return pd.Series(dtype=float)
    if isinstance(downloaded.columns, pd.MultiIndex):
        if "Close" in downloaded.columns.get_level_values(0):
            selected = downloaded["Close"]
        elif "Close" in downloaded.columns.get_level_values(-1):
            selected = downloaded.xs("Close", axis=1, level=-1)
        else:
            raise ValueError("download has no Close column")
        if isinstance(selected, pd.DataFrame):
            selected = selected.iloc[:, 0]
        return selected.astype(float)
    if "Close" not in downloaded.columns:
        raise ValueError("download has no Close column")
    return downloaded["Close"].astype(float)


def fetch_market_data(
    assets: list[dict[str, Any]],
) -> tuple[dict[str, pd.DataFrame], list[dict[str, Any]]]:
    import yfinance as yf

    frames: dict[str, pd.DataFrame] = {}
    audit: list[dict[str, Any]] = []
    market_dir = RAW / "market"
    market_dir.mkdir(parents=True, exist_ok=True)
    for asset in assets:
        asset_id = str(asset["id"])
        ticker = str(asset["ticker"])
        error: str | None = None
        frame = pd.DataFrame()
        for attempt in range(3):
            try:
                downloaded = yf.download(
                    ticker,
                    start="2025-07-14",
                    end="2026-07-18",
                    auto_adjust=True,
                    progress=False,
                    threads=False,
                    timeout=60,
                )
                close = extract_close(downloaded).dropna()
                if len(close) < 20:
                    raise ValueError(f"only {len(close)} close observations")
                index = pd.to_datetime(close.index)
                if getattr(index, "tz", None) is not None:
                    index = index.tz_convert(None)
                frame = pd.DataFrame(
                    {"date": index.normalize(), "close": close.to_numpy(dtype=float)}
                )
                frame = frame.drop_duplicates("date").sort_values("date")
                break
            except Exception as exc:
                error = str(exc)
                time.sleep(2**attempt)
        if not frame.empty:
            frame["return"] = np.log(frame["close"]).diff()
            frame["abs_return"] = frame["return"].abs()
            path = market_dir / f"{asset_id}.csv"
            frame.to_csv(path, index=False)
            frames[asset_id] = frame
            audit.append(
                {
                    **asset,
                    "status": "AVAILABLE",
                    "rows": int(len(frame)),
                    "start": str(frame["date"].min().date()),
                    "end": str(frame["date"].max().date()),
                    "sha256": sha256_file(path),
                }
            )
            print(f"MARKET {asset_id} {ticker}: {len(frame)} rows")
        else:
            audit.append(
                {**asset, "status": "UNAVAILABLE", "rows": 0, "error": error}
            )
            print(f"MARKET {asset_id} {ticker}: unavailable: {error}")
        time.sleep(0.4)
    pd.DataFrame(audit).to_json(
        OUTPUT / "market_coverage.json", orient="records", indent=2, force_ascii=False
    )
    return frames, audit


def aggregate_news_to_trading_dates(
    topic_frame: pd.DataFrame, trading_dates: pd.Series, feature: str
) -> pd.Series:
    source = topic_frame.set_index("date")[feature].sort_index()
    dates = pd.DatetimeIndex(pd.to_datetime(trading_dates)).sort_values()
    output: list[float] = []
    previous: pd.Timestamp | None = None
    for current in dates:
        start = current if previous is None else previous + pd.Timedelta(days=1)
        window = source.loc[(source.index >= start) & (source.index <= current)].dropna()
        output.append(float(window.sum()) if not window.empty else math.nan)
        previous = current
    return pd.Series(output, index=dates, dtype=float)


def fit_hac(x: pd.DataFrame, y: pd.Series, lags: int) -> Any:
    matrix = sm.add_constant(x.astype(float), has_constant="add")
    return sm.OLS(y.astype(float), matrix, missing="drop").fit(
        cov_type="HAC", cov_kwds={"maxlags": lags}
    )


def linear_predict(
    train_x: np.ndarray, train_y: np.ndarray, test_x: np.ndarray
) -> tuple[np.ndarray, float]:
    design_train = np.column_stack([np.ones(len(train_x)), train_x])
    design_test = np.column_stack([np.ones(len(test_x)), test_x])
    coefficients = np.linalg.lstsq(design_train, train_y, rcond=None)[0]
    return design_test @ coefficients, float(coefficients[-1])


def walk_forward(frame: pd.DataFrame, target: str, feature: str) -> dict[str, float | int | str]:
    n = len(frame)
    initial = max(80, int(n * 0.55))
    block = 20
    baseline_errors: list[float] = []
    full_errors: list[float] = []
    fold_betas: list[float] = []
    folds = 0
    controls = ["return", "abs_return"]
    for start in range(initial, n, block):
        stop = min(n, start + block)
        if stop - start < 5:
            continue
        train = frame.iloc[:start]
        test = frame.iloc[start:stop]
        baseline_pred, _ = linear_predict(
            train[controls].to_numpy(),
            train[target].to_numpy(),
            test[controls].to_numpy(),
        )
        full_pred, beta = linear_predict(
            train[controls + [feature]].to_numpy(),
            train[target].to_numpy(),
            test[controls + [feature]].to_numpy(),
        )
        actual = test[target].to_numpy()
        baseline_errors.extend((actual - baseline_pred).tolist())
        full_errors.extend((actual - full_pred).tolist())
        fold_betas.append(beta)
        folds += 1
    if not baseline_errors:
        return {
            "folds": 0,
            "baseline_rmse": math.nan,
            "full_rmse": math.nan,
            "oos_improvement": math.nan,
            "sign_stability": math.nan,
            "fold_betas_json": "[]",
        }
    baseline_rmse = float(np.sqrt(np.mean(np.square(baseline_errors))))
    full_rmse = float(np.sqrt(np.mean(np.square(full_errors))))
    improvement = (
        (baseline_rmse - full_rmse) / baseline_rmse
        if baseline_rmse > 0
        else math.nan
    )
    return {
        "folds": folds,
        "baseline_rmse": baseline_rmse,
        "full_rmse": full_rmse,
        "oos_improvement": float(improvement),
        "fold_betas_json": json.dumps(fold_betas),
    }


def placebo_p_value(
    frame: pd.DataFrame,
    target: str,
    feature: str,
    beta: float,
    repetitions: int,
    seed: int,
) -> float:
    rng = random.Random(seed)
    n = len(frame)
    controls = frame[["return", "abs_return"]].to_numpy()
    y = frame[target].to_numpy()
    feature_values = frame[feature].to_numpy()
    placebo: list[float] = []
    minimum = min(10, max(2, n // 8))
    shifts = list(range(minimum, max(minimum + 1, n - minimum)))
    for _ in range(repetitions):
        shift = rng.choice(shifts)
        shifted = np.roll(feature_values, shift)
        x = np.column_stack([controls, shifted])
        _, placebo_beta = linear_predict(x, y, x[:1])
        placebo.append(abs(placebo_beta))
    return float(
        (1 + sum(value >= abs(beta) for value in placebo)) / (repetitions + 1)
    )


def build_panel(
    asset_frame: pd.DataFrame, topic_frame: pd.DataFrame, feature: str
) -> pd.DataFrame:
    frame = asset_frame.copy().sort_values("date")
    frame[feature] = aggregate_news_to_trading_dates(
        topic_frame, frame["date"], feature
    ).to_numpy()
    frame["next_return"] = frame["return"].shift(-1)
    frame["next_abs_return"] = frame["abs_return"].shift(-1)
    return frame.dropna(
        subset=["return", "abs_return", feature, "next_return", "next_abs_return"]
    ).reset_index(drop=True)


def run_hypotheses(
    universe: dict[str, Any],
    hypotheses: dict[str, Any],
    gdelt: pd.DataFrame,
    markets: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    gates = GateConfig(
        fdr_alpha=float(hypotheses["fdr_alpha"]),
        placebo_alpha=float(hypotheses["placebo_alpha"]),
        min_oos_improvement=float(hypotheses["min_oos_improvement"]),
        min_sign_stability=float(hypotheses["min_sign_stability"]),
        min_observations=int(hypotheses["min_observations"]),
        placebo_repetitions=int(hypotheses["placebo_repetitions"]),
        hac_lags=int(hypotheses["hac_lags"]),
    )
    results: list[dict[str, Any]] = []
    topic_lookup = {name: group.copy() for name, group in gdelt.groupby("topic")}
    for asset in universe["assets"]:
        asset_id = str(asset["id"])
        if asset_id not in markets:
            continue
        for topic in asset["topics"]:
            if topic not in topic_lookup:
                continue
            for feature in hypotheses["features"]:
                panel = build_panel(markets[asset_id], topic_lookup[topic], feature)
                for family in hypotheses["families"]:
                    target = family["target"]
                    row: dict[str, Any] = {
                        "hypothesis_id": f"{family['id']}::{asset_id}::{topic}::{feature}",
                        "family": family["id"],
                        "target": target,
                        "expected": family["expected"],
                        "asset_id": asset_id,
                        "asset_name": asset["name"],
                        "ticker": asset["ticker"],
                        "market": asset["market"],
                        "instrument_type": asset["type"],
                        "topic": topic,
                        "feature": feature,
                        "nobs": int(len(panel)),
                        "status": "DATA_INSUFFICIENT",
                    }
                    if len(panel) < gates.min_observations:
                        results.append(row)
                        continue
                    fit = fit_hac(
                        panel[["return", "abs_return", feature]],
                        panel[target],
                        gates.hac_lags,
                    )
                    beta = float(fit.params[feature])
                    se = float(fit.bse[feature])
                    p_value = float(fit.pvalues[feature])
                    ci_low, ci_high = [
                        float(value) for value in fit.conf_int().loc[feature]
                    ]
                    oos = walk_forward(panel, target, feature)
                    fold_betas = json.loads(str(oos.get("fold_betas_json", "[]")))
                    sign_stability = (
                        float(
                            np.mean(
                                [
                                    math.copysign(1, value)
                                    == math.copysign(1, beta)
                                    for value in fold_betas
                                ]
                            )
                        )
                        if fold_betas and beta != 0
                        else math.nan
                    )
                    placebo = placebo_p_value(
                        panel,
                        target,
                        feature,
                        beta,
                        gates.placebo_repetitions,
                        stable_seed(asset_id, topic, feature, target),
                    )
                    effect_std = beta * float(panel[feature].std(ddof=0))
                    target_std = float(panel[target].std(ddof=0))
                    row.update(
                        {
                            "status": "TESTED",
                            "beta": beta,
                            "standard_error_hac": se,
                            "p_value": p_value,
                            "ci_low": ci_low,
                            "ci_high": ci_high,
                            "effect_std_units": (
                                effect_std / target_std if target_std > 0 else math.nan
                            ),
                            "placebo_p": placebo,
                            "folds": int(oos["folds"]),
                            "baseline_rmse": oos["baseline_rmse"],
                            "full_rmse": oos["full_rmse"],
                            "oos_improvement": oos["oos_improvement"],
                            "sign_stability": sign_stability,
                            "fold_betas_json": oos.get("fold_betas_json", "[]"),
                        }
                    )
                    results.append(row)
    frame = pd.DataFrame(results)
    frame["q_value"] = math.nan
    tested_groups = frame.loc[frame["status"] == "TESTED"].groupby("family").groups
    for _, indices in tested_groups.items():
        p_values = frame.loc[indices, "p_value"].astype(float).tolist()
        frame.loc[indices, "q_value"] = bh_fdr(p_values)
    decisions: list[str] = []
    for row in frame.to_dict("records"):
        if row["status"] != "TESTED":
            decisions.append("DATA_INSUFFICIENT")
            continue
        direction_ok = row["expected"] == "nonzero" or float(row["beta"]) > 0
        supported = (
            direction_ok
            and float(row["q_value"]) <= gates.fdr_alpha
            and float(row["placebo_p"]) <= gates.placebo_alpha
            and float(row["oos_improvement"]) > gates.min_oos_improvement
            and float(row["sign_stability"]) >= gates.min_sign_stability
        )
        decisions.append("SUPPORTED" if supported else "INCONCLUSIVE")
    frame["decision"] = decisions
    return frame


def save_figures(
    results: pd.DataFrame, gdelt: pd.DataFrame, coverage: list[dict[str, Any]]
) -> None:
    FIGURES.mkdir(parents=True, exist_ok=True)
    available = pd.DataFrame(coverage)
    if not available.empty:
        plot_data = available.sort_values("rows")
        fig, ax = plt.subplots(figsize=(10, 9))
        ax.barh(plot_data["id"], plot_data["rows"])
        ax.set_title("Stage 1 market data coverage")
        ax.set_xlabel("Daily observations")
        fig.tight_layout()
        fig.savefig(FIGURES / "01_market_coverage.png", dpi=180)
        plt.close(fig)

    pivot = gdelt.pivot(index="date", columns="topic", values="volume_share_z30")
    fig, ax = plt.subplots(figsize=(12, 6))
    pivot.plot(ax=ax, linewidth=1)
    ax.set_title("GDELT topic attention shocks (30-day z-score)")
    ax.set_xlabel("Date")
    ax.set_ylabel("z-score")
    ax.legend(ncol=3, fontsize=8)
    fig.tight_layout()
    fig.savefig(FIGURES / "02_gdelt_topic_shocks.png", dpi=180)
    plt.close(fig)

    tested = results[
        (results["status"] == "TESTED")
        & (results["feature"] == "negative_pressure")
    ]
    targets = [
        (
            "next_return",
            "03_return_beta_heatmap.png",
            "News pressure coefficients: next return",
        ),
        (
            "next_abs_return",
            "04_abs_return_beta_heatmap.png",
            "News pressure coefficients: next absolute return",
        ),
    ]
    for target, filename, title in targets:
        subset = tested[tested["target"] == target]
        if subset.empty:
            continue
        matrix = subset.pivot(index="asset_id", columns="topic", values="beta")
        fig, ax = plt.subplots(figsize=(12, max(6, len(matrix) * 0.32)))
        image = ax.imshow(matrix.to_numpy(), aspect="auto", interpolation="nearest")
        ax.set_xticks(
            range(len(matrix.columns)), matrix.columns, rotation=45, ha="right"
        )
        ax.set_yticks(range(len(matrix.index)), matrix.index)
        ax.set_title(title)
        fig.colorbar(image, ax=ax, shrink=0.7)
        fig.tight_layout()
        fig.savefig(FIGURES / filename, dpi=180)
        plt.close(fig)

    tested = results[results["status"] == "TESTED"].copy()
    if not tested.empty:
        tested["minus_log10_q"] = -np.log10(tested["q_value"].clip(lower=1e-12))
        fig, ax = plt.subplots(figsize=(10, 6))
        for family, group in tested.groupby("family"):
            ax.scatter(
                group["oos_improvement"] * 100,
                group["minus_log10_q"],
                alpha=0.55,
                label=family,
            )
        ax.axvline(0, linestyle="--", linewidth=1)
        ax.axhline(-math.log10(0.10), linestyle="--", linewidth=1)
        ax.set_xlabel("Out-of-sample RMSE improvement (%)")
        ax.set_ylabel("-log10(q-value)")
        ax.set_title("Statistical vs out-of-sample evidence")
        ax.legend()
        fig.tight_layout()
        fig.savefig(FIGURES / "05_evidence_scatter.png", dpi=180)
        plt.close(fig)

        counts = tested.groupby(["market", "decision"]).size().unstack(fill_value=0)
        fig, ax = plt.subplots(figsize=(10, 6))
        counts.plot(kind="bar", stacked=True, ax=ax)
        ax.set_title("Hypothesis decisions by market")
        ax.set_xlabel("Market")
        ax.set_ylabel("Count")
        fig.tight_layout()
        fig.savefig(FIGURES / "06_decisions_by_market.png", dpi=180)
        plt.close(fig)


def markdown_table(
    frame: pd.DataFrame, columns: list[str], limit: int = 20
) -> str:
    if frame.empty:
        return "_无记录_"
    selected = frame.loc[:, columns].head(limit).copy()
    return selected.to_markdown(index=False, floatfmt=".4g")


def write_report(
    results: pd.DataFrame,
    gdelt_audit: list[dict[str, Any]],
    market_audit: list[dict[str, Any]],
) -> None:
    tested = results[results["status"] == "TESTED"].copy()
    supported = tested[tested["decision"] == "SUPPORTED"].sort_values(
        ["q_value", "placebo_p"]
    )
    near = tested.sort_values(
        ["q_value", "placebo_p", "oos_improvement"],
        ascending=[True, True, False],
    )
    unavailable = pd.DataFrame(market_audit)
    unavailable = (
        unavailable[unavailable["status"] != "AVAILABLE"]
        if not unavailable.empty
        else unavailable
    )
    unavailable_columns = [
        column
        for column in ["id", "ticker", "market", "error"]
        if column in unavailable.columns
    ]
    lines = [
        "# 全球新闻—多市场研究 Stage 1 结果",
        "",
        f"研究窗口：{START} 至 {END}",
        "",
        "## 1. 研究定位",
        "",
        "本轮是使用真实 GDELT 和真实市场价格执行的预注册筛选研究。结果不是最终确认性论文结论；连续期货、黄金现货和日频 UTC 会话对齐均将在后续阶段以更严格数据重做。",
        "",
        "## 2. 数据覆盖",
        "",
        f"- GDELT 主题：{len(gdelt_audit)}；",
        f"- 资产计划数：{len(market_audit)}；",
        f"- 可用资产数：{sum(item['status'] == 'AVAILABLE' for item in market_audit)}；",
        f"- 完成检验数：{len(tested)}；",
        f"- 数据不足数：{int((results['decision'] == 'DATA_INSUFFICIENT').sum())}。",
        "",
        "### 不可用资产",
        "",
        markdown_table(unavailable, unavailable_columns),
        "",
        "## 3. 严格裁决结果",
        "",
        f"SUPPORTED 数量：**{len(supported)}**。",
        "",
        markdown_table(
            supported,
            [
                "hypothesis_id",
                "beta",
                "q_value",
                "placebo_p",
                "oos_improvement",
                "sign_stability",
                "nobs",
            ],
            40,
        ),
        "",
        "## 4. 证据最强但未通过全部门禁的候选",
        "",
        markdown_table(
            near,
            [
                "hypothesis_id",
                "decision",
                "beta",
                "q_value",
                "placebo_p",
                "oos_improvement",
                "sign_stability",
                "nobs",
            ],
            30,
        ),
        "",
        "## 5. 解释规则",
        "",
        "名义显著、FDR 显著、安慰剂通过或样本外改善中的任何单项都不足以构成结论。只有五道门同时通过才标记 SUPPORTED。",
        "",
        "## 6. 下一阶段",
        "",
        "1. 用 GDELT raw/BigQuery 扩展到 2015 年以来；",
        "2. 实现交易所时区与盘前/盘中/盘后对齐；",
        "3. 替换 Yahoo 连续期货代理为可审计换月序列；",
        "4. 加入局部投影、事件研究、双向聚类标准误与层级 FDR；",
        "5. 扩展公司级实体匹配和正式公告对照。",
        "",
    ]
    (OUTPUT / "stage1_report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)
    universe = json.loads((ROOT / "asset_universe.json").read_text(encoding="utf-8"))
    hypotheses = json.loads((ROOT / "hypotheses.json").read_text(encoding="utf-8"))
    gdelt, gdelt_audit = fetch_gdelt_topics(universe["topics"])
    markets, market_audit = fetch_market_data(universe["assets"])
    results = run_hypotheses(universe, hypotheses, gdelt, markets)
    results.to_csv(OUTPUT / "hypothesis_results.csv", index=False)
    save_figures(results, gdelt, market_audit)
    write_report(results, gdelt_audit, market_audit)
    manifest: dict[str, Any] = {
        "study_id": "global-news-markets-stage1",
        "window": {"start": START, "end": END},
        "generated_at_utc": pd.Timestamp.utcnow().isoformat(),
        "gdelt_audit": gdelt_audit,
        "market_audit": market_audit,
        "hypothesis_counts": results["decision"].value_counts(dropna=False).to_dict(),
        "tested": int((results["status"] == "TESTED").sum()),
        "supported": int((results["decision"] == "SUPPORTED").sum()),
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
    print(
        json.dumps(
            {
                "tested": manifest["tested"],
                "supported": manifest["supported"],
                "counts": manifest["hypothesis_counts"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
