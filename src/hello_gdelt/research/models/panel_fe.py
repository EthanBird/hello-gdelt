from __future__ import annotations

from dataclasses import dataclass
from typing import Hashable, Sequence

import numpy as np
from scipy import stats


class PanelModelError(ValueError):
    """Raised when a fixed-effect panel model is unidentified or numerically unsafe."""


@dataclass(frozen=True, slots=True)
class PanelCoefficient:
    name: str
    estimate: float
    standard_error: float
    t_statistic: float
    p_value: float


@dataclass(frozen=True, slots=True)
class PanelFixedEffectResult:
    coefficients: tuple[PanelCoefficient, ...]
    covariance: tuple[tuple[float, ...], ...]
    observation_count: int
    entity_count: int
    time_count: int
    regressor_count: int
    residual_degrees_of_freedom: int
    within_r_squared: float
    residual_sum_squares: float
    within_iterations: int
    within_converged: bool
    covariance_type: str = "TWO_WAY_CLUSTER_ENTITY_TIME"


def _validate_labels(labels: Sequence[Hashable], *, name: str, n: int) -> tuple[Hashable, ...]:
    materialized = tuple(labels)
    if len(materialized) != n:
        raise PanelModelError(f"{name} length {len(materialized)} != observations {n}")
    try:
        unique = set(materialized)
    except TypeError as exc:
        raise PanelModelError(f"{name} labels must be hashable") from exc
    if len(unique) < 2:
        raise PanelModelError(f"{name} requires at least two clusters")
    return materialized


def _group_positions(labels: tuple[Hashable, ...]) -> tuple[np.ndarray, ...]:
    grouped: dict[Hashable, list[int]] = {}
    for index, label in enumerate(labels):
        grouped.setdefault(label, []).append(index)
    return tuple(np.asarray(positions, dtype=np.int64) for positions in grouped.values())


def _alternating_within_transform(
    values: np.ndarray,
    entity_labels: tuple[Hashable, ...],
    time_labels: tuple[Hashable, ...],
    *,
    tolerance: float,
    max_iterations: int,
) -> tuple[np.ndarray, int, bool]:
    transformed = np.asarray(values, dtype=np.float64).copy()
    if transformed.ndim == 1:
        transformed = transformed[:, None]
    entity_groups = _group_positions(entity_labels)
    time_groups = _group_positions(time_labels)
    for iteration in range(1, max_iterations + 1):
        previous = transformed.copy()
        for positions in entity_groups:
            transformed[positions] -= transformed[positions].mean(axis=0, keepdims=True)
        for positions in time_groups:
            transformed[positions] -= transformed[positions].mean(axis=0, keepdims=True)
        maximum_change = float(np.max(np.abs(transformed - previous)))
        if maximum_change <= tolerance:
            return transformed, iteration, True
    return transformed, max_iterations, False


def _cluster_meat(
    design: np.ndarray,
    residuals: np.ndarray,
    labels: tuple[Hashable, ...],
) -> np.ndarray:
    scores = design * residuals[:, None]
    grouped: dict[Hashable, np.ndarray] = {}
    for index, label in enumerate(labels):
        existing = grouped.get(label)
        if existing is None:
            grouped[label] = scores[index].copy()
        else:
            existing += scores[index]
    meat = np.zeros((design.shape[1], design.shape[1]), dtype=np.float64)
    for score_sum in grouped.values():
        meat += np.outer(score_sum, score_sum)
    return meat


def _finite_sample_factor(cluster_count: int, observation_count: int, rank: int) -> float:
    if cluster_count <= 1 or observation_count <= rank:
        raise PanelModelError("insufficient clusters or residual degrees of freedom")
    return (cluster_count / (cluster_count - 1)) * (
        (observation_count - 1) / (observation_count - rank)
    )


def fit_two_way_fixed_effects(
    outcome: Sequence[float],
    regressors: Sequence[Sequence[float]],
    *,
    regressor_names: Sequence[str],
    entity_labels: Sequence[Hashable],
    time_labels: Sequence[Hashable],
    tolerance: float = 1e-10,
    max_iterations: int = 10_000,
) -> PanelFixedEffectResult:
    """Fit an unweighted two-way fixed-effect OLS with two-way clustered covariance.

    Fixed effects are removed by alternating projections, which remains valid for an
    unbalanced panel. The covariance uses the Cameron-Gelbach-Miller inclusion-
    exclusion form: entity meat + time meat - entity×time intersection meat.
    """

    y = np.asarray(outcome, dtype=np.float64)
    x = np.asarray(regressors, dtype=np.float64)
    if y.ndim != 1 or y.size == 0:
        raise PanelModelError("outcome must be a non-empty one-dimensional vector")
    if x.ndim != 2 or x.shape[0] != y.size or x.shape[1] == 0:
        raise PanelModelError("regressors must be an N×K matrix aligned with outcome")
    if not np.isfinite(y).all() or not np.isfinite(x).all():
        raise PanelModelError("outcome and regressors must be finite")
    names = tuple(regressor_names)
    if len(names) != x.shape[1] or len(set(names)) != len(names):
        raise PanelModelError("regressor_names must be unique and match K")
    if tolerance <= 0 or max_iterations <= 0:
        raise PanelModelError("tolerance and max_iterations must be positive")

    n = y.size
    entities = _validate_labels(entity_labels, name="entity_labels", n=n)
    times = _validate_labels(time_labels, name="time_labels", n=n)
    combined = np.column_stack((y, x))
    within, iterations, converged = _alternating_within_transform(
        combined,
        entities,
        times,
        tolerance=tolerance,
        max_iterations=max_iterations,
    )
    if not converged:
        raise PanelModelError(
            f"two-way within transform did not converge after {max_iterations} iterations"
        )
    y_within = within[:, 0]
    x_within = within[:, 1:]
    rank = int(np.linalg.matrix_rank(x_within))
    if rank != x.shape[1]:
        raise PanelModelError(
            f"within-transformed design is rank deficient: rank={rank}, K={x.shape[1]}"
        )
    if n <= rank:
        raise PanelModelError("no residual degrees of freedom")

    coefficients, _, _, _ = np.linalg.lstsq(x_within, y_within, rcond=None)
    fitted = x_within @ coefficients
    residuals = y_within - fitted
    residual_sum_squares = float(residuals @ residuals)
    centered_sum_squares = float(y_within @ y_within)
    within_r_squared = (
        float("nan")
        if centered_sum_squares == 0
        else 1.0 - residual_sum_squares / centered_sum_squares
    )

    xtx_inverse = np.linalg.inv(x_within.T @ x_within)
    entity_count = len(set(entities))
    time_count = len(set(times))
    intersections = tuple(zip(entities, times, strict=True))
    intersection_count = len(set(intersections))
    entity_meat = _cluster_meat(x_within, residuals, entities)
    time_meat = _cluster_meat(x_within, residuals, times)
    intersection_meat = _cluster_meat(x_within, residuals, intersections)
    entity_factor = _finite_sample_factor(entity_count, n, rank)
    time_factor = _finite_sample_factor(time_count, n, rank)
    intersection_factor = _finite_sample_factor(intersection_count, n, rank)
    covariance = xtx_inverse @ (
        entity_factor * entity_meat
        + time_factor * time_meat
        - intersection_factor * intersection_meat
    ) @ xtx_inverse
    covariance = (covariance + covariance.T) / 2.0
    diagonal = np.diag(covariance)
    if np.any(diagonal < -1e-12):
        raise PanelModelError(
            "two-way clustered covariance has a materially negative variance; "
            "increase cluster support or revise the specification"
        )
    standard_errors = np.sqrt(np.maximum(diagonal, 0.0))
    cluster_degrees_of_freedom = min(entity_count, time_count) - 1
    if cluster_degrees_of_freedom <= 0:
        raise PanelModelError("two-way covariance requires at least two clusters per dimension")

    coefficient_results: list[PanelCoefficient] = []
    for index, name in enumerate(names):
        standard_error = float(standard_errors[index])
        estimate = float(coefficients[index])
        if standard_error == 0:
            t_statistic = math.copysign(float("inf"), estimate) if estimate != 0 else 0.0
            p_value = 0.0 if estimate != 0 else 1.0
        else:
            t_statistic = estimate / standard_error
            p_value = float(
                2.0
                * stats.t.sf(
                    abs(t_statistic),
                    df=cluster_degrees_of_freedom,
                )
            )
        coefficient_results.append(
            PanelCoefficient(
                name=name,
                estimate=estimate,
                standard_error=standard_error,
                t_statistic=t_statistic,
                p_value=p_value,
            )
        )

    return PanelFixedEffectResult(
        coefficients=tuple(coefficient_results),
        covariance=tuple(tuple(float(value) for value in row) for row in covariance),
        observation_count=n,
        entity_count=entity_count,
        time_count=time_count,
        regressor_count=rank,
        residual_degrees_of_freedom=n - rank,
        within_r_squared=within_r_squared,
        residual_sum_squares=residual_sum_squares,
        within_iterations=iterations,
        within_converged=converged,
    )
