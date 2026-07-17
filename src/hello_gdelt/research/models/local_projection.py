from __future__ import annotations

from dataclasses import dataclass
from typing import Hashable, Mapping, Sequence

from scipy import stats

from hello_gdelt.research.models.panel_fe import (
    PanelFixedEffectResult,
    PanelModelError,
    fit_two_way_fixed_effects,
)


class LocalProjectionError(ValueError):
    """Raised when horizon-specific panel outcomes violate the LP contract."""


@dataclass(frozen=True, slots=True)
class LocalProjectionPoint:
    horizon: int
    shock_name: str
    estimate: float
    standard_error: float
    p_value: float
    confidence_level: float
    confidence_lower: float
    confidence_upper: float
    panel_result: PanelFixedEffectResult


@dataclass(frozen=True, slots=True)
class LocalProjectionResult:
    shock_name: str
    horizons: tuple[LocalProjectionPoint, ...]
    confidence_level: float
    covariance_type: str = "TWO_WAY_CLUSTER_ENTITY_TIME"


def fit_panel_local_projections(
    outcomes_by_horizon: Mapping[int, Sequence[float]],
    regressors: Sequence[Sequence[float]],
    *,
    regressor_names: Sequence[str],
    shock_name: str,
    entity_labels: Sequence[Hashable],
    time_labels: Sequence[Hashable],
    confidence_level: float = 0.95,
    tolerance: float = 1e-10,
    max_iterations: int = 10_000,
) -> LocalProjectionResult:
    """Fit a horizon-by-horizon panel local projection with identical controls.

    The caller constructs each dependent variable as the preregistered cumulative or
    endpoint response for horizon h. This runner freezes the right-hand-side design,
    fixed effects and covariance treatment across horizons.
    """

    if not outcomes_by_horizon:
        raise LocalProjectionError("outcomes_by_horizon is empty")
    if not 0 < confidence_level < 1:
        raise LocalProjectionError("confidence_level must lie strictly between 0 and 1")
    names = tuple(regressor_names)
    if shock_name not in names:
        raise LocalProjectionError(f"shock_name is not a regressor: {shock_name}")
    horizons = tuple(sorted(outcomes_by_horizon))
    if any(horizon < 0 for horizon in horizons):
        raise LocalProjectionError("local-projection horizons must be non-negative")
    shock_index = names.index(shock_name)
    points: list[LocalProjectionPoint] = []
    alpha = 1.0 - confidence_level
    for horizon in horizons:
        outcome = outcomes_by_horizon[horizon]
        try:
            panel = fit_two_way_fixed_effects(
                outcome,
                regressors,
                regressor_names=names,
                entity_labels=entity_labels,
                time_labels=time_labels,
                tolerance=tolerance,
                max_iterations=max_iterations,
            )
        except PanelModelError as exc:
            raise LocalProjectionError(f"horizon {horizon}: {exc}") from exc
        coefficient = panel.coefficients[shock_index]
        cluster_df = min(panel.entity_count, panel.time_count) - 1
        critical = float(stats.t.ppf(1.0 - alpha / 2.0, df=cluster_df))
        half_width = critical * coefficient.standard_error
        points.append(
            LocalProjectionPoint(
                horizon=horizon,
                shock_name=shock_name,
                estimate=coefficient.estimate,
                standard_error=coefficient.standard_error,
                p_value=coefficient.p_value,
                confidence_level=confidence_level,
                confidence_lower=coefficient.estimate - half_width,
                confidence_upper=coefficient.estimate + half_width,
                panel_result=panel,
            )
        )
    return LocalProjectionResult(
        shock_name=shock_name,
        horizons=tuple(points),
        confidence_level=confidence_level,
    )
