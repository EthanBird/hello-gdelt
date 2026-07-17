from __future__ import annotations

from hello_gdelt.hypothesis.catalog import default_catalog
from hello_gdelt.hypothesis.compiler import HypothesisCompiler
from hello_gdelt.hypothesis.dataset import InMemoryDatasetProvider, Observation
from hello_gdelt.hypothesis.runner import HypothesisRunner
from hello_gdelt.hypothesis.schema import Decision, HypothesisSpec


def test_detects_stable_negative_signal(
    negative_signal_spec: HypothesisSpec,
    negative_signal_observations: list[Observation],
) -> None:
    plan = HypothesisCompiler(default_catalog()).compile(negative_signal_spec)
    result = HypothesisRunner().run(
        plan, InMemoryDatasetProvider(negative_signal_observations, "negative_signal_v1")
    )
    assert result.decision is Decision.SUPPORTED
    assert result.coefficient < -1.3
    assert result.q_value < 0.05
    assert result.oos_r2 > 0.8
    assert result.fold_sign_agreement == 1.0
    assert result.placebo_outperformed


def test_rejects_significant_opposite_signal(
    base_spec_dict: dict[str, object],
    negative_signal_observations: list[Observation],
) -> None:
    payload = dict(base_spec_dict)
    payload["expected_sign"] = "positive"
    spec = HypothesisSpec.model_validate(payload)
    plan = HypothesisCompiler(default_catalog()).compile(spec)
    result = HypothesisRunner().run(
        plan, InMemoryDatasetProvider(negative_signal_observations, "negative_signal_v1")
    )
    assert result.decision is Decision.REJECTED
