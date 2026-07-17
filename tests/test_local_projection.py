import numpy as np
import pytest

pytest.importorskip("scipy")

from hello_gdelt.research.models.local_projection import (
    LocalProjectionError,
    fit_panel_local_projections,
)


def synthetic_local_projection_inputs():
    rng = np.random.default_rng(20260718)
    entities = [f"A{index:02d}" for index in range(20)]
    times = list(range(36))
    entity_labels: list[str] = []
    time_labels: list[int] = []
    regressors: list[list[float]] = []
    shocks: list[float] = []
    control_values: list[float] = []
    entity_effect = rng.normal(scale=0.6, size=len(entities))
    time_effect = rng.normal(scale=0.4, size=len(times))
    for entity_index, entity in enumerate(entities):
        for time_index in times:
            shock = rng.normal()
            control = rng.normal()
            entity_labels.append(entity)
            time_labels.append(time_index)
            shocks.append(shock)
            control_values.append(control)
            regressors.append([shock, control])
    outcomes: dict[int, np.ndarray] = {}
    for horizon, beta in ((0, 0.8), (1, 0.5), (2, 0.2), (5, 0.0)):
        values: list[float] = []
        for index, (entity, time_index) in enumerate(
            zip(entity_labels, time_labels, strict=True)
        ):
            entity_index = entities.index(entity)
            values.append(
                beta * shocks[index]
                + 0.25 * control_values[index]
                + entity_effect[entity_index]
                + time_effect[time_index]
                + rng.normal(scale=0.3)
            )
        outcomes[horizon] = np.asarray(values)
    return outcomes, np.asarray(regressors), entity_labels, time_labels


def test_local_projection_recovers_decaying_impulse_response() -> None:
    outcomes, regressors, entities, times = synthetic_local_projection_inputs()
    result = fit_panel_local_projections(
        outcomes,
        regressors,
        regressor_names=("news_shock", "control"),
        shock_name="news_shock",
        entity_labels=entities,
        time_labels=times,
    )
    estimates = {point.horizon: point.estimate for point in result.horizons}
    assert estimates[0] == pytest.approx(0.8, abs=0.05)
    assert estimates[1] == pytest.approx(0.5, abs=0.05)
    assert estimates[2] == pytest.approx(0.2, abs=0.05)
    assert estimates[5] == pytest.approx(0.0, abs=0.05)
    assert all(
        point.confidence_lower <= point.estimate <= point.confidence_upper
        for point in result.horizons
    )


def test_local_projection_rejects_unknown_shock() -> None:
    outcomes, regressors, entities, times = synthetic_local_projection_inputs()
    with pytest.raises(LocalProjectionError, match="not a regressor"):
        fit_panel_local_projections(
            outcomes,
            regressors,
            regressor_names=("news_shock", "control"),
            shock_name="missing",
            entity_labels=entities,
            time_labels=times,
        )


def test_local_projection_rejects_negative_horizon() -> None:
    outcomes, regressors, entities, times = synthetic_local_projection_inputs()
    invalid = {-1: outcomes[0]}
    with pytest.raises(LocalProjectionError, match="non-negative"):
        fit_panel_local_projections(
            invalid,
            regressors,
            regressor_names=("news_shock", "control"),
            shock_name="news_shock",
            entity_labels=entities,
            time_labels=times,
        )
