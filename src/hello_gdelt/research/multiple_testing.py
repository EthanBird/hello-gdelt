from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Literal


class MultipleTestingError(ValueError):
    """Raised when confirmatory p-values or hypothesis identities are invalid."""


@dataclass(frozen=True, slots=True)
class HypothesisTestResult:
    hypothesis_id: str
    family: str
    market_group: str
    p_value: float
    estimate: float
    expected_direction: Literal["POSITIVE", "NEGATIVE", "TWO_SIDED"]
    economic_significance_pass: bool
    placebo_pass: bool
    data_sufficient: bool = True
    licence_available: bool = True
    q_family: float | None = None
    q_market: float | None = None
    q_global: float | None = None


Decision = Literal[
    "SUPPORTED",
    "REJECTED",
    "INCONCLUSIVE",
    "DATA_INSUFFICIENT",
    "LICENCE_BLOCKED",
]


def benjamini_hochberg(p_values: tuple[float, ...]) -> tuple[float, ...]:
    """Return monotone Benjamini-Hochberg adjusted p-values in input order."""

    if not p_values:
        return ()
    for value in p_values:
        if not math.isfinite(value) or value < 0.0 or value > 1.0:
            raise MultipleTestingError(f"p-value outside [0, 1]: {value!r}")
    count = len(p_values)
    ranked = sorted(enumerate(p_values), key=lambda item: (item[1], item[0]))
    adjusted_sorted = [1.0] * count
    running = 1.0
    for reverse_rank in range(count - 1, -1, -1):
        original_index, p_value = ranked[reverse_rank]
        rank = reverse_rank + 1
        candidate = min(1.0, p_value * count / rank)
        running = min(running, candidate)
        adjusted_sorted[reverse_rank] = running
    adjusted = [1.0] * count
    for sorted_index, (original_index, _) in enumerate(ranked):
        adjusted[original_index] = adjusted_sorted[sorted_index]
    return tuple(adjusted)


def apply_hierarchical_fdr(
    results: tuple[HypothesisTestResult, ...],
) -> tuple[HypothesisTestResult, ...]:
    """Attach family-, market-, and global-level BH q-values.

    This is deliberately an auditable three-view adjustment, not a claim that the
    three dependent selections constitute a specialized tree-FDR procedure. Formal
    support requires the global q-value to pass in addition to the grouped views.
    """

    if not results:
        return ()
    identifiers = [item.hypothesis_id for item in results]
    if len(set(identifiers)) != len(identifiers):
        raise MultipleTestingError("hypothesis_id values must be unique")
    global_q = benjamini_hochberg(tuple(item.p_value for item in results))
    family_q: dict[str, float] = {}
    market_q: dict[str, float] = {}

    families = sorted({item.family for item in results})
    for family in families:
        positions = [index for index, item in enumerate(results) if item.family == family]
        adjusted = benjamini_hochberg(tuple(results[index].p_value for index in positions))
        for position, q_value in zip(positions, adjusted, strict=True):
            family_q[results[position].hypothesis_id] = q_value

    markets = sorted({item.market_group for item in results})
    for market in markets:
        positions = [index for index, item in enumerate(results) if item.market_group == market]
        adjusted = benjamini_hochberg(tuple(results[index].p_value for index in positions))
        for position, q_value in zip(positions, adjusted, strict=True):
            market_q[results[position].hypothesis_id] = q_value

    return tuple(
        replace(
            item,
            q_family=family_q[item.hypothesis_id],
            q_market=market_q[item.hypothesis_id],
            q_global=global_q[index],
        )
        for index, item in enumerate(results)
    )


def _direction_matches(result: HypothesisTestResult) -> bool:
    if result.expected_direction == "POSITIVE":
        return result.estimate > 0
    if result.expected_direction == "NEGATIVE":
        return result.estimate < 0
    return result.estimate != 0


def decide_result(
    result: HypothesisTestResult,
    *,
    alpha: float = 0.05,
    rejection_power_sufficient: bool = False,
) -> Decision:
    if not 0 < alpha < 1:
        raise MultipleTestingError("alpha must lie strictly between zero and one")
    if not result.licence_available:
        return "LICENCE_BLOCKED"
    if not result.data_sufficient:
        return "DATA_INSUFFICIENT"
    if result.q_global is None or result.q_family is None or result.q_market is None:
        raise MultipleTestingError("hierarchical FDR must be applied before decision")
    globally_significant = result.q_global <= alpha
    grouped_significant = result.q_family <= alpha and result.q_market <= alpha
    direction_matches = _direction_matches(result)
    if (
        globally_significant
        and grouped_significant
        and direction_matches
        and result.economic_significance_pass
        and result.placebo_pass
    ):
        return "SUPPORTED"
    if globally_significant and grouped_significant and not direction_matches:
        return "REJECTED"
    if rejection_power_sufficient and not globally_significant:
        return "REJECTED"
    return "INCONCLUSIVE"
