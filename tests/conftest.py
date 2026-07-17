from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from hello_gdelt.hypothesis.dataset import Observation
from hello_gdelt.hypothesis.schema import HypothesisSpec


@pytest.fixture
def base_spec_dict() -> dict[str, object]:
    return {
        "claim": "Higher media-observed financial stress predicts local-currency depreciation.",
        "universe": {
            "entity_type": "country",
            "start_date": "2024-01-01",
            "end_date": "2024-07-31",
            "entities": ["BRA", "MEX", "ZAF", "TUR"],
        },
        "feature": {
            "feature_id": "financial_stress_narrative",
            "window_days": 7,
            "lag_days": 0,
        },
        "target": {"target_id": "fx_return_usd", "horizon_days": 1},
        "model": {"type": "panel_ols", "fixed_effects": ["entity"]},
        "expected_sign": "negative",
        "validation": {
            "min_train_periods": 80,
            "test_periods": 20,
            "step_periods": 20,
            "min_observations": 200,
        },
        "robustness": {
            "placebos": ["shuffle_date", "shuffle_entity", "random_feature"],
            "placebo_repeats": 3,
            "random_seed": 99,
        },
        "decision_rule": {
            "max_q_value": 0.05,
            "min_fold_sign_agreement": 0.75,
            "min_oos_r2": 0.05,
            "require_placebo_outperformance": True,
        },
    }


@pytest.fixture
def negative_signal_spec(base_spec_dict: dict[str, object]) -> HypothesisSpec:
    return HypothesisSpec.model_validate(base_spec_dict)


@pytest.fixture
def negative_signal_observations() -> list[Observation]:
    rng = np.random.default_rng(7)
    start = date(2024, 1, 1)
    observations: list[Observation] = []
    for entity_index, entity in enumerate(("BRA", "MEX", "ZAF", "TUR")):
        feature = rng.normal(size=210)
        target = np.zeros(210)
        target[1:] = -1.5 * feature[:-1] + rng.normal(scale=0.2, size=209)
        target += entity_index * 0.02
        for index in range(210):
            observations.append(
                Observation(
                    date=start + timedelta(days=index),
                    entity_id=entity,
                    values={
                        "financial_stress_narrative": float(feature[index]),
                        "fx_return_usd": float(target[index]),
                    },
                )
            )
    return observations
