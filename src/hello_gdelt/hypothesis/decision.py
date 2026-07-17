from __future__ import annotations

from dataclasses import dataclass

from .schema import Decision, DecisionRule, EffectSign


@dataclass(frozen=True, slots=True)
class DecisionInputs:
    coefficient: float
    q_value: float
    oos_r2: float
    fold_sign_agreement: float
    placebo_outperformed: bool


@dataclass(frozen=True, slots=True)
class DecisionOutcome:
    decision: Decision
    reasons: tuple[str, ...]


def _sign_matches(coefficient: float, expected: EffectSign) -> bool:
    if expected is EffectSign.POSITIVE:
        return coefficient > 0
    if expected is EffectSign.NEGATIVE:
        return coefficient < 0
    return coefficient != 0


def decide(
    inputs: DecisionInputs,
    expected: EffectSign,
    rule: DecisionRule,
) -> DecisionOutcome:
    sign_matches = _sign_matches(inputs.coefficient, expected)
    gates = {
        "q_value": inputs.q_value <= rule.max_q_value,
        "effect_size": abs(inputs.coefficient) >= rule.min_effect_abs,
        "expected_sign": sign_matches,
        "fold_stability": inputs.fold_sign_agreement >= rule.min_fold_sign_agreement,
        "oos_r2": inputs.oos_r2 >= rule.min_oos_r2,
        "placebo": inputs.placebo_outperformed or not rule.require_placebo_outperformance,
    }
    if all(gates.values()):
        return DecisionOutcome(
            decision=Decision.SUPPORTED,
            reasons=("all pre-registered decision gates passed",),
        )

    if inputs.q_value <= rule.max_q_value and not sign_matches:
        return DecisionOutcome(
            decision=Decision.REJECTED,
            reasons=("effect is statistically distinguishable but opposite to the expected sign",),
        )

    failed = tuple(name for name, passed in gates.items() if not passed)
    return DecisionOutcome(
        decision=Decision.INCONCLUSIVE,
        reasons=("failed gates: " + ", ".join(failed),),
    )
