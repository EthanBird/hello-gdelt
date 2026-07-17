from __future__ import annotations

import pytest

from hello_gdelt.hypothesis.catalog import default_catalog
from hello_gdelt.hypothesis.compiler import CompilationError, HypothesisCompiler
from hello_gdelt.hypothesis.schema import HypothesisSpec


def test_compiles_registered_hypothesis(negative_signal_spec: HypothesisSpec) -> None:
    plan = HypothesisCompiler(default_catalog(), lambda _: 800).compile(negative_signal_spec)
    assert plan.hypothesis_id.startswith("h_")
    assert plan.estimated_rows == 800
    assert plan.feature.artifact_id == "financial_stress_narrative"


def test_rejects_unknown_feature(base_spec_dict: dict[str, object]) -> None:
    payload = dict(base_spec_dict)
    payload["feature"] = {
        "feature_id": "unregistered_feature",
        "window_days": 7,
        "lag_days": 0,
    }
    spec = HypothesisSpec.model_validate(payload)
    with pytest.raises(CompilationError, match="unknown feature"):
        HypothesisCompiler(default_catalog()).compile(spec)


def test_rejects_estimated_rows_over_budget(negative_signal_spec: HypothesisSpec) -> None:
    with pytest.raises(CompilationError, match="exceed max_rows"):
        HypothesisCompiler(default_catalog(), lambda _: 3_000_000).compile(negative_signal_spec)
