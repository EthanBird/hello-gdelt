from __future__ import annotations

from pathlib import Path

from hello_gdelt.hypothesis.catalog import default_catalog
from hello_gdelt.hypothesis.compiler import HypothesisCompiler
from hello_gdelt.hypothesis.dataset import InMemoryDatasetProvider, Observation
from hello_gdelt.hypothesis.registry import HypothesisRegistry
from hello_gdelt.hypothesis.runner import HypothesisRunner
from hello_gdelt.hypothesis.schema import HypothesisSpec


def test_registry_round_trip(
    tmp_path: Path,
    negative_signal_spec: HypothesisSpec,
    negative_signal_observations: list[Observation],
) -> None:
    plan = HypothesisCompiler(default_catalog()).compile(negative_signal_spec)
    result = HypothesisRunner().run(
        plan, InMemoryDatasetProvider(negative_signal_observations, "registry_test_v1")
    )
    registry = HypothesisRegistry(tmp_path / "control.sqlite")
    registry.register(negative_signal_spec, plan)
    registry.save_result(result)
    stored_hypothesis = registry.get_hypothesis(plan.hypothesis_id)
    stored_result = registry.get_result(result.run_id)
    assert stored_hypothesis is not None
    assert stored_hypothesis["status"] == result.decision.value
    assert stored_result == result
