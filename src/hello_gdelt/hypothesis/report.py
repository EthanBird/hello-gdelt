from __future__ import annotations

from .runner import ExperimentResult
from .schema import ExperimentPlan


def render_markdown(plan: ExperimentPlan, result: ExperimentResult) -> str:
    spec = plan.spec
    lines = [
        f"# Hypothesis Report: {plan.hypothesis_id}",
        "",
        f"**Decision:** `{result.decision.value}`",
        "",
        "## Claim",
        "",
        spec.claim,
        "",
        "## Pre-registered design",
        "",
        f"- Feature: `{spec.feature.feature_id}` ({spec.feature.transform.value}, "
        f"window={spec.feature.window_days}, lag={spec.feature.lag_days})",
        f"- Target: `{spec.target.target_id}` (horizon={spec.target.horizon_days})",
        f"- Model: `{spec.model.type.value}`",
        f"- Expected sign: `{spec.expected_sign.value}`",
        f"- Period: `{spec.universe.start_date}` to `{spec.universe.end_date}`",
        f"- Plan hash: `{plan.plan_hash}`",
        "",
        "## Results",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Observations | {result.observations} |",
        f"| Entities | {result.entities} |",
        f"| Coefficient | {result.coefficient:.6g} |",
        f"| Standard error | {result.standard_error:.6g} |",
        f"| p-value | {result.p_value:.6g} |",
        f"| q-value | {result.q_value:.6g} |",
        f"| OOS R² | {result.oos_r2:.6g} |",
        f"| Fold sign agreement | {result.fold_sign_agreement:.3f} |",
        f"| Placebo outperformed | {result.placebo_outperformed} |",
        "",
        "## Decision rationale",
        "",
        *(f"- {reason}" for reason in result.decision_reasons),
        "",
        "## Lineage",
        "",
        *(f"- `{key}`: `{value}`" for key, value in sorted(result.lineage.items())),
    ]
    if result.warnings:
        lines.extend(["", "## Warnings", "", *(f"- {item}" for item in result.warnings)])
    lines.append("")
    return "\n".join(lines)
