from dataclasses import replace
from typing import Literal

import pytest

from hello_gdelt.research.multiple_testing import (
    HypothesisTestResult,
    MultipleTestingError,
    apply_hierarchical_fdr,
    benjamini_hochberg,
    decide_result,
)


def result(
    hypothesis_id: str,
    *,
    family: str,
    market: str,
    p_value: float,
    estimate: float = 1.0,
    expected_direction: Literal["POSITIVE", "NEGATIVE", "TWO_SIDED"] = "POSITIVE",
    economic: bool = True,
    placebo: bool = True,
) -> HypothesisTestResult:
    return HypothesisTestResult(
        hypothesis_id=hypothesis_id,
        family=family,
        market_group=market,
        p_value=p_value,
        estimate=estimate,
        expected_direction=expected_direction,
        economic_significance_pass=economic,
        placebo_pass=placebo,
    )


def test_bh_matches_known_example_and_input_order() -> None:
    adjusted = benjamini_hochberg((0.04, 0.001, 0.03, 0.2))
    assert adjusted == pytest.approx((0.0533333333, 0.004, 0.0533333333, 0.2))


def test_bh_rejects_invalid_p_values() -> None:
    with pytest.raises(MultipleTestingError, match="outside"):
        benjamini_hochberg((0.1, -0.01))


def test_hierarchical_fdr_attaches_all_three_views() -> None:
    adjusted = apply_hierarchical_fdr(
        (
            result("H001", family="A", market="US", p_value=0.001),
            result("H002", family="A", market="JP", p_value=0.02),
            result("H003", family="B", market="US", p_value=0.03),
            result("H004", family="B", market="JP", p_value=0.8),
        )
    )
    assert all(item.q_family is not None for item in adjusted)
    assert all(item.q_market is not None for item in adjusted)
    assert all(item.q_global is not None for item in adjusted)
    assert adjusted[0].q_global == pytest.approx(0.004)


def test_decision_requires_direction_economic_placebo_and_global_fdr() -> None:
    supported = apply_hierarchical_fdr(
        (result("H001", family="A", market="US", p_value=0.001),)
    )[0]
    assert decide_result(supported) == "SUPPORTED"

    wrong_direction = apply_hierarchical_fdr(
        (
            result(
                "H002",
                family="A",
                market="US",
                p_value=0.001,
                estimate=-1.0,
            ),
        )
    )[0]
    assert decide_result(wrong_direction) == "REJECTED"

    failed_placebo = apply_hierarchical_fdr(
        (
            result(
                "H003",
                family="A",
                market="US",
                p_value=0.001,
                placebo=False,
            ),
        )
    )[0]
    assert decide_result(failed_placebo) == "INCONCLUSIVE"


def test_data_and_licence_gates_override_significance() -> None:
    base = result("H001", family="A", market="US", p_value=0.001)
    adjusted = apply_hierarchical_fdr((base,))[0]
    assert decide_result(replace(adjusted, licence_available=False)) == "LICENCE_BLOCKED"
