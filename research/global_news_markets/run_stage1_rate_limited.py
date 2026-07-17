from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import run_stage1 as base

MIN_INTERVAL_SECONDS = 12.0
_last_request_at = 0.0


def http_json_rate_limited(url: str, *, retries: int = 12) -> dict[str, Any]:
    global _last_request_at
    last_error: Exception | None = None
    for attempt in range(retries):
        elapsed = time.monotonic() - _last_request_at
        if elapsed < MIN_INTERVAL_SECONDS:
            time.sleep(MIN_INTERVAL_SECONDS - elapsed)
        try:
            request = urllib.request.Request(url, headers={"User-Agent": base.USER_AGENT})
            _last_request_at = time.monotonic()
            with urllib.request.urlopen(request, timeout=180) as response:  # noqa: S310
                payload = response.read()
            parsed = json.loads(payload.decode("utf-8-sig"))
            if not isinstance(parsed, dict):
                raise ValueError("JSON root is not an object")
            return parsed
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code == 429:
                retry_after = exc.headers.get("Retry-After")
                delay = float(retry_after) if retry_after and retry_after.isdigit() else 60.0 + 15.0 * attempt
                print(f"GDELT HTTP 429; waiting {delay:.0f}s before retry {attempt + 2}/{retries}")
                time.sleep(delay)
                continue
            time.sleep(min(60.0, 3.0 * (attempt + 1)))
        except Exception as exc:
            last_error = exc
            time.sleep(min(60.0, 3.0 * (attempt + 1)))
    raise RuntimeError(f"failed to fetch {url}: {last_error}")


def simplify_stage1_queries(path: Path) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["topics"] = {
        "geopolitical_risk": "war",
        "monetary_policy": "\"central bank\"",
        "inflation": "inflation",
        "recession": "recession",
        "trade_tariff": "tariff",
        "sanctions": "sanctions",
        "energy_supply": "oil",
        "precious_metals": "gold",
        "semiconductors": "semiconductor",
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    simplify_stage1_queries(base.ROOT / "asset_universe.json")
    base.http_json = http_json_rate_limited
    base.main()


if __name__ == "__main__":
    main()
