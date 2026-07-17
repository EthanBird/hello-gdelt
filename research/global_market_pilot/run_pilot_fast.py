from __future__ import annotations

import math

import numpy as np
import pandas as pd

import run_pilot as pilot


def fast_placebo_p_value(
    data: pd.DataFrame,
    target_col: str,
    feature_col: str,
    observed_beta: float,
    seed_offset: int,
) -> float:
    """Compute the registered circular-shift placebo with fast OLS point estimates.

    HAC affects uncertainty estimates, not the OLS coefficient itself. The placebo gate
    compares coefficient magnitudes, so using ``numpy.linalg.lstsq`` is numerically
    equivalent for the registered point statistic and avoids tens of thousands of
    unnecessary robust-covariance calculations.
    """

    rng = np.random.default_rng(pilot.RANDOM_SEED + seed_offset)
    news = data[feature_col].to_numpy(float)
    y = data[target_col].to_numpy(float)
    controls = data[["lag_return", "lag_abs_return"]].to_numpy(float)
    magnitudes: list[float] = []
    min_shift = max(10, len(news) // 10)
    upper = max(min_shift + 1, len(news) - min_shift)
    for _ in range(pilot.PLACEBO_REPEATS):
        shift = int(rng.integers(min_shift, upper))
        shifted = np.roll(news, shift)
        design = np.column_stack([np.ones(len(y)), shifted, controls])
        coefficients, *_ = np.linalg.lstsq(design, y, rcond=None)
        magnitudes.append(abs(float(coefficients[1])))
    return float(
        (1 + np.sum(np.asarray(magnitudes) >= abs(observed_beta)))
        / (len(magnitudes) + 1)
    )


_original_market_download = pilot.download_market_series
_original_factor_download = pilot.download_gdelt_factor
_original_run_test = pilot.run_test
_test_counter = 0


def logged_market_download(asset: dict[str, object], start: str, end: str):
    frame, record = _original_market_download(asset, start, end)
    print(
        f"MARKET {asset['asset_id']}: {record.status}, rows={record.rows}",
        flush=True,
    )
    return frame, record


def logged_factor_download(factor: dict[str, object], start: str, end: str):
    frame, record = _original_factor_download(factor, start, end)
    print(
        f"GDELT {factor['factor_id']}: {record.status}, rows={record.rows}",
        flush=True,
    )
    return frame, record


def logged_run_test(*args, **kwargs):
    global _test_counter
    result = _original_run_test(*args, **kwargs)
    _test_counter += 1
    if _test_counter % 100 == 0:
        print(f"TESTS evaluated={_test_counter}", flush=True)
    return result


def main() -> None:
    pilot.placebo_p_value = fast_placebo_p_value
    pilot.download_market_series = logged_market_download
    pilot.download_gdelt_factor = logged_factor_download
    pilot.run_test = logged_run_test
    pilot.main()


if __name__ == "__main__":
    main()
