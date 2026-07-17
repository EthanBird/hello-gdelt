from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parent
START = "2019-01-01"
END = "2026-07-18"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def flatten_columns(frame: pd.DataFrame, ticker: str) -> pd.DataFrame:
    if not isinstance(frame.columns, pd.MultiIndex):
        return frame.copy()
    first = frame.columns.get_level_values(0)
    last = frame.columns.get_level_values(-1)
    if ticker in last:
        result = frame.xs(ticker, axis=1, level=-1, drop_level=True)
    elif ticker in first:
        result = frame.xs(ticker, axis=1, level=0, drop_level=True)
    else:
        result = frame.copy()
        result.columns = ["_".join(str(part) for part in column if part) for column in result.columns]
    return result


def proxy_flags(asset: dict[str, Any]) -> list[str]:
    flags: list[str] = ["YAHOO_STAGE1_SOURCE"]
    instrument_type = str(asset["type"])
    if instrument_type == "futures_proxy":
        flags.extend(["CONTINUOUS_FUTURES_PROXY", "ROLL_RULE_NOT_AUDITED"])
    if instrument_type == "spot_proxy_etf":
        flags.extend(["ETF_EXPOSURE_PROXY", "NOT_LBMA_BENCHMARK"])
    if instrument_type == "yield_proxy":
        flags.append("YIELD_INDEX_PROXY")
    if str(asset["market"]) in {"China", "Korea", "Japan"}:
        flags.append("EXCHANGE_OFFICIAL_SOURCE_REQUIRED_FOR_CONFIRMATION")
    return flags


def status_for_rows(rows: int) -> str:
    if rows >= 750:
        return "AVAILABLE"
    if rows >= 120:
        return "PARTIAL"
    return "UNAVAILABLE"


def download_asset(asset: dict[str, Any], output: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    ticker = str(asset["ticker"])
    asset_id = str(asset["id"])
    last_error: str | None = None
    raw = pd.DataFrame()
    for attempt in range(4):
        try:
            raw = yf.download(
                ticker,
                start=START,
                end=END,
                auto_adjust=False,
                actions=True,
                progress=False,
                threads=False,
                timeout=90,
            )
            if not raw.empty:
                break
            last_error = "empty response"
        except Exception as exc:  # pragma: no cover - network-dependent
            last_error = repr(exc)
        time.sleep(2 ** attempt)
    if raw.empty:
        return pd.DataFrame(), {
            **asset,
            "status": "UNAVAILABLE",
            "rows": 0,
            "error": last_error,
            "risk_flags": proxy_flags(asset),
        }

    frame = flatten_columns(raw, ticker)
    frame = frame.reset_index()
    date_column = next((column for column in frame.columns if str(column).lower() in {"date", "datetime"}), None)
    if date_column is None:
        raise ValueError(f"{ticker}: no Date/Datetime column")
    frame = frame.rename(columns={date_column: "date"})
    dates = pd.to_datetime(frame["date"], errors="coerce")
    if getattr(dates.dt, "tz", None) is not None:
        dates = dates.dt.tz_convert(None)
    frame["date"] = dates.dt.normalize()
    standard_names = {str(column).lower().replace(" ", "_"): column for column in frame.columns}
    rename: dict[Any, str] = {}
    for canonical in ["open", "high", "low", "close", "adj_close", "volume", "dividends", "stock_splits"]:
        if canonical in standard_names:
            rename[standard_names[canonical]] = canonical
    frame = frame.rename(columns=rename)
    required = ["date", "close"]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"{ticker}: missing required columns {missing}; got {list(frame.columns)}")
    keep = [column for column in ["date", "open", "high", "low", "close", "adj_close", "volume", "dividends", "stock_splits"] if column in frame.columns]
    frame = frame[keep].copy()
    for column in keep:
        if column != "date":
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["date", "close"]).sort_values("date")
    duplicates = int(frame["date"].duplicated().sum())
    frame = frame.drop_duplicates("date", keep="last")
    price_column = "adj_close" if "adj_close" in frame.columns and frame["adj_close"].notna().sum() >= 0.95 * len(frame) else "close"
    frame["analysis_price"] = frame[price_column]
    frame["log_return"] = np.log(frame["analysis_price"].where(frame["analysis_price"] > 0)).diff()
    frame["abs_return"] = frame["log_return"].abs()
    frame["asset_id"] = asset_id
    frame["ticker"] = ticker
    path = output / "per_asset" / f"{asset_id}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    positive_returns = frame["log_return"].dropna().abs()
    audit: dict[str, Any] = {
        **asset,
        "status": status_for_rows(int(frame["close"].notna().sum())),
        "rows": int(len(frame)),
        "start": str(frame["date"].min().date()),
        "end": str(frame["date"].max().date()),
        "duplicate_dates_before_dedupe": duplicates,
        "missing_close_fraction": float(frame["close"].isna().mean()),
        "nonpositive_analysis_price": int((frame["analysis_price"] <= 0).sum()),
        "analysis_price_column": price_column,
        "return_abs_q99": float(positive_returns.quantile(0.99)) if not positive_returns.empty else math.nan,
        "return_abs_max": float(positive_returns.max()) if not positive_returns.empty else math.nan,
        "csv_sha256": sha256_file(path),
        "risk_flags": proxy_flags(asset),
    }
    for column in ["open", "high", "low", "volume"]:
        audit[f"missing_{column}_fraction"] = (
            float(frame[column].isna().mean()) if column in frame.columns else None
        )
    return frame, audit


def save_figures(combined: pd.DataFrame, coverage: pd.DataFrame, output: Path) -> None:
    figures = output / "figures"
    figures.mkdir(exist_ok=True)
    sorted_coverage = coverage.sort_values(["status", "rows"], ascending=[True, True])
    fig, ax = plt.subplots(figsize=(11, 10))
    ax.barh(sorted_coverage["id"], sorted_coverage["rows"])
    ax.axvline(750, linestyle="--", linewidth=1, label="AVAILABLE threshold")
    ax.set_xlabel("Daily observations")
    ax.set_title("Cross-market history coverage (2019-2026)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(figures / "01_coverage_rows.png", dpi=180)
    plt.close(fig)

    returns = combined.pivot(index="date", columns="asset_id", values="log_return")
    available_ids = coverage.loc[coverage["status"] == "AVAILABLE", "id"].tolist()
    available_ids = [asset_id for asset_id in available_ids if asset_id in returns.columns]
    correlations = returns[available_ids].corr(min_periods=120) if available_ids else pd.DataFrame()
    correlations.to_csv(output / "return_correlation.csv")
    if not correlations.empty:
        fig, ax = plt.subplots(figsize=(13, 11))
        image = ax.imshow(correlations.to_numpy(), vmin=-1, vmax=1, aspect="auto")
        ax.set_xticks(range(len(correlations.columns)), correlations.columns, rotation=90, fontsize=7)
        ax.set_yticks(range(len(correlations.index)), correlations.index, fontsize=7)
        ax.set_title("Daily return correlations for AVAILABLE assets")
        fig.colorbar(image, ax=ax, shrink=0.75)
        fig.tight_layout()
        fig.savefig(figures / "02_return_correlation.png", dpi=180)
        plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("market_coverage_output"))
    args = parser.parse_args()
    output: Path = args.output
    output.mkdir(parents=True, exist_ok=True)
    universe = json.loads((ROOT / "asset_universe.json").read_text(encoding="utf-8"))
    all_frames: list[pd.DataFrame] = []
    audits: list[dict[str, Any]] = []
    for asset in universe["assets"]:
        try:
            frame, audit = download_asset(asset, output)
        except Exception as exc:  # pragma: no cover - defensive network parsing
            frame = pd.DataFrame()
            audit = {
                **asset,
                "status": "UNAVAILABLE",
                "rows": 0,
                "error": repr(exc),
                "risk_flags": proxy_flags(asset),
            }
        audits.append(audit)
        if not frame.empty:
            all_frames.append(frame)
        print(f"{asset['id']}: {audit['status']} rows={audit['rows']}")
        time.sleep(0.5)
    coverage = pd.DataFrame(audits)
    coverage.to_json(output / "market_coverage.json", orient="records", indent=2, force_ascii=False)
    if not all_frames:
        raise RuntimeError("no market series downloaded")
    combined = pd.concat(all_frames, ignore_index=True)
    combined.to_parquet(output / "market_daily.parquet", index=False, compression="zstd")
    save_figures(combined, coverage, output)
    manifest = {
        "study_id": "cross-market-price-coverage-pilot",
        "window": {"start": START, "end_exclusive": END},
        "planned_assets": int(len(universe["assets"])),
        "available": int((coverage["status"] == "AVAILABLE").sum()),
        "partial": int((coverage["status"] == "PARTIAL").sum()),
        "unavailable": int((coverage["status"] == "UNAVAILABLE").sum()),
        "combined_rows": int(len(combined)),
        "market_daily_sha256": sha256_file(output / "market_daily.parquet"),
        "coverage_sha256": sha256_file(output / "market_coverage.json"),
    }
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
