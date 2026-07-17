from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Any

import pandas as pd
import requests

import run_pilot as pilot
import run_pilot_fast as fast

OUTPUT = Path(os.environ.get("RESEARCH_OUTPUT", "research_output_global_market"))
RAW_DIR = OUTPUT / "gdelt_raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

_RATE_LOCK = threading.Lock()
_LAST_REQUEST_AT = 0.0
MIN_REQUEST_INTERVAL_SECONDS = 15.0


def rate_limited_gdelt_request(
    query: str, mode: str, start: str, end: str
) -> tuple[dict[str, Any], bytes]:
    """Call GDELT with a global rate limit, 429-aware backoff and raw caching."""

    global _LAST_REQUEST_AT
    params = {
        "query": query,
        "mode": mode,
        "format": "json",
        "startdatetime": pd.Timestamp(start).strftime("%Y%m%d000000"),
        "enddatetime": pd.Timestamp(end).strftime("%Y%m%d235959"),
        "timelinesmooth": "0",
    }
    cache_key = hashlib.sha256(
        json.dumps(params, sort_keys=True).encode("utf-8")
    ).hexdigest()
    cache_path = RAW_DIR / f"{cache_key}.json"
    if cache_path.exists():
        raw = cache_path.read_bytes()
        payload = json.loads(raw)
        return payload, raw

    headers = {"User-Agent": "hello-gdelt-global-market-research/0.1"}
    failures: list[str] = []
    for attempt in range(4):
        with _RATE_LOCK:
            delay = MIN_REQUEST_INTERVAL_SECONDS - (time.monotonic() - _LAST_REQUEST_AT)
            if delay > 0:
                time.sleep(delay)
            _LAST_REQUEST_AT = time.monotonic()
        try:
            response = requests.get(
                "https://api.gdeltproject.org/api/v2/doc/doc",
                params=params,
                headers=headers,
                timeout=90,
            )
            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                wait = float(retry_after) if retry_after and retry_after.isdigit() else 45.0
                failures.append(f"attempt {attempt + 1}: HTTP 429")
                time.sleep(wait)
                continue
            if 400 <= response.status_code < 500:
                raise RuntimeError(
                    f"non-retryable HTTP {response.status_code}: {response.text[:300]}"
                )
            response.raise_for_status()
            raw = response.content
            payload = response.json()
            if not isinstance(payload, dict):
                raise TypeError("GDELT response is not an object")
            cache_path.write_bytes(raw)
            return payload, raw
        except Exception as exc:  # noqa: BLE001
            failures.append(f"attempt {attempt + 1}: {type(exc).__name__}: {exc}")
            if attempt < 3:
                time.sleep(5.0 * (attempt + 1))
    raise RuntimeError("; ".join(failures))


def dtype_safe_align_news(
    asset_frame: pd.DataFrame, factor_frame: pd.DataFrame
) -> pd.DataFrame:
    """Normalize both merge keys to nanosecond precision before as-of alignment."""

    market = asset_frame.copy()
    news = factor_frame.copy()
    market["date"] = pd.to_datetime(market["date"], errors="raise").astype(
        "datetime64[ns]"
    )
    news["date"] = pd.to_datetime(news["date"], errors="raise").astype(
        "datetime64[ns]"
    )
    market = market.sort_values("date")
    news = news.sort_values("date")
    return pd.merge_asof(
        market,
        news,
        on="date",
        direction="backward",
        allow_exact_matches=False,
        tolerance=pd.Timedelta(days=4),
    )


def main() -> None:
    pilot.gdelt_request = rate_limited_gdelt_request
    pilot.align_news = dtype_safe_align_news
    fast.main()


if __name__ == "__main__":
    main()
