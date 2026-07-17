from dataclasses import replace
from pathlib import Path

import pytest

from hello_gdelt.research.results import (
    ResultRegistry,
    ResultRegistryError,
    create_result,
    validate_experiment_result,
)

GIT_SHA = "a" * 40
SHA256 = "b" * 64


def supported_result(run_id: str = "run-001"):
    return create_result(
        run_id=run_id,
        hypothesis_id="H001",
        family="attention_shock",
        market_group="US_EQUITY",
        sample_period="VALIDATE",
        model_name="panel_fixed_effect",
        outcome_name="close_to_close_return",
        exposure_name="attention_z",
        horizon=1,
        decision="SUPPORTED",
        observation_count=10_000,
        asset_count=24,
        start_date="2023-01-01",
        end_date="2024-12-31",
        git_commit=GIT_SHA,
        data_sha256=SHA256,
        config_sha256="c" * 64,
        code_sha256="d" * 64,
        estimate=0.0004,
        standard_error=0.0001,
        statistic=4.0,
        p_value=0.0001,
        q_family=0.001,
        q_market=0.002,
        q_global=0.004,
        economic_effect_bps=4.0,
        placebo_pass=True,
        economic_significance_pass=True,
        result_payload={"covariance": "two_way_cluster"},
    )


def test_supported_result_requires_global_fdr_placebo_and_economics() -> None:
    result = supported_result()
    validate_experiment_result(result)
    with pytest.raises(ResultRegistryError, match="q_global"):
        validate_experiment_result(replace(result, q_global=0.2))
    with pytest.raises(ResultRegistryError, match="placebo_pass"):
        validate_experiment_result(replace(result, placebo_pass=False))
    with pytest.raises(ResultRegistryError, match="economic_significance"):
        validate_experiment_result(replace(result, economic_significance_pass=False))


def test_licence_blocked_cannot_hide_a_model_estimate() -> None:
    blocked = create_result(
        run_id="run-blocked",
        hypothesis_id="H050",
        family="geopolitical_safe_haven",
        market_group="LONDON_PROXY",
        sample_period="FINAL",
        model_name="local_projection",
        outcome_name="spot_return",
        exposure_name="conflict_shock",
        horizon=5,
        decision="LICENCE_BLOCKED",
        observation_count=0,
        asset_count=0,
        start_date="2025-01-01",
        end_date="2026-06-30",
        git_commit=GIT_SHA,
        data_sha256=SHA256,
        config_sha256="c" * 64,
        code_sha256="d" * 64,
        result_payload={"reason": "official benchmark licence unavailable"},
    )
    with pytest.raises(ResultRegistryError, match="must not contain"):
        validate_experiment_result(replace(blocked, estimate=1.0))


def test_registry_append_is_idempotent_but_conflicts_are_rejected(tmp_path: Path) -> None:
    database = tmp_path / "results.sqlite3"
    original = supported_result()
    with ResultRegistry(database) as registry:
        registry.append(original)
        registry.append(original)
        assert registry.list_results() == (original,)
        with pytest.raises(ResultRegistryError, match="different content"):
            registry.append(replace(original, hypothesis_id="H002"))


def test_registry_exports_machine_readable_parquet(tmp_path: Path) -> None:
    pl = pytest.importorskip("polars")
    database = tmp_path / "results.sqlite3"
    destination = tmp_path / "result_registry.parquet"
    with ResultRegistry(database) as registry:
        registry.append(supported_result())
        exported = registry.export_parquet(destination)
    frame = pl.read_parquet(exported)
    assert frame.height == 1
    assert frame["hypothesis_id"].item() == "H001"
    assert frame["decision"].item() == "SUPPORTED"
    assert frame["q_global"].item() == pytest.approx(0.004)


def test_digest_and_payload_validation_are_strict() -> None:
    result = supported_result()
    with pytest.raises(ResultRegistryError, match="data_sha256"):
        validate_experiment_result(replace(result, data_sha256="bad"))
    with pytest.raises(ResultRegistryError, match="JSON"):
        validate_experiment_result(replace(result, result_payload_json="[]"))
