from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class OLSResult:
    coefficients: FloatArray
    standard_errors: FloatArray
    t_values: FloatArray
    p_values: FloatArray
    predictions: FloatArray
    residuals: FloatArray
    rank: int
    condition_number: float


def _normal_two_sided_p(t_value: float) -> float:
    return min(1.0, math.erfc(abs(t_value) / math.sqrt(2.0)))


def fit_ols(x: FloatArray, y: FloatArray) -> OLSResult:
    if x.ndim != 2 or y.ndim != 1:
        raise ValueError("x must be 2D and y must be 1D")
    if x.shape[0] != y.shape[0]:
        raise ValueError("x and y row counts differ")
    if x.shape[0] <= x.shape[1]:
        raise ValueError("insufficient observations for OLS")
    if not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError("x and y must contain only finite values")

    raw_coefficients, _, rank, singular_values = np.linalg.lstsq(x, y, rcond=None)
    coefficients = np.asarray(raw_coefficients, dtype=np.float64)
    predictions = np.asarray(x @ coefficients, dtype=np.float64)
    residuals = np.asarray(y - predictions, dtype=np.float64)
    degrees_freedom = max(1, x.shape[0] - rank)
    sigma_squared = float(residuals @ residuals) / degrees_freedom
    covariance = sigma_squared * np.linalg.pinv(x.T @ x)
    variances = np.maximum(np.diag(covariance), 0.0)
    standard_errors = np.asarray(np.sqrt(variances), dtype=np.float64)
    t_values = np.asarray(
        np.divide(
            coefficients,
            standard_errors,
            out=np.zeros_like(coefficients),
            where=standard_errors > 0,
        ),
        dtype=np.float64,
    )
    p_values = np.asarray(
        [_normal_two_sided_p(float(value)) for value in t_values], dtype=np.float64
    )
    condition_number = (
        float(singular_values[0] / singular_values[-1])
        if singular_values.size and singular_values[-1] > 0
        else math.inf
    )
    return OLSResult(
        coefficients=coefficients,
        standard_errors=standard_errors,
        t_values=t_values,
        p_values=p_values,
        predictions=predictions,
        residuals=residuals,
        rank=int(rank),
        condition_number=condition_number,
    )


def r2_score(y_true: FloatArray, y_pred: FloatArray) -> float:
    residual = float(np.sum((y_true - y_pred) ** 2))
    centered = float(np.sum((y_true - np.mean(y_true)) ** 2))
    if centered <= 0:
        return 0.0
    return 1.0 - residual / centered


def bh_fdr(p_values: list[float]) -> list[float]:
    if not p_values:
        return []
    clipped = np.clip(np.asarray(p_values, dtype=float), 0.0, 1.0)
    order = np.argsort(clipped)
    ranked = clipped[order]
    count = len(ranked)
    adjusted = ranked * count / np.arange(1, count + 1)
    adjusted = np.minimum.accumulate(adjusted[::-1])[::-1]
    adjusted = np.clip(adjusted, 0.0, 1.0)
    result = np.empty_like(adjusted)
    result[order] = adjusted
    return [float(value) for value in result]


def two_way_demean(
    values: FloatArray,
    entity_codes: NDArray[np.int64],
    time_codes: NDArray[np.int64],
    *,
    entity: bool,
    time: bool,
    iterations: int = 8,
) -> FloatArray:
    output = values.astype(float, copy=True)
    if output.ndim == 1:
        output = output[:, None]
    for _ in range(iterations):
        if entity:
            for code in np.unique(entity_codes):
                mask = entity_codes == code
                output[mask] -= np.mean(output[mask], axis=0)
        if time:
            for code in np.unique(time_codes):
                mask = time_codes == code
                output[mask] -= np.mean(output[mask], axis=0)
    return output
