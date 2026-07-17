from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
from pydantic import ValidationError

from .hypothesis.catalog import default_catalog
from .hypothesis.compiler import CompilationError, HypothesisCompiler
from .hypothesis.dataset import InMemoryDatasetProvider, Observation
from .hypothesis.registry import HypothesisRegistry
from .hypothesis.report import render_markdown
from .hypothesis.runner import HypothesisRunner
from .hypothesis.schema import HypothesisSpec


def _load_spec(path: Path) -> HypothesisSpec:
    return HypothesisSpec.model_validate_json(path.read_text(encoding="utf-8"))


def _demo_observations() -> list[Observation]:
    rng = np.random.default_rng(42)
    observations: list[Observation] = []
    start = date(2024, 1, 1)
    for entity_index, entity in enumerate(("BRA", "MEX", "ZAF", "TUR")):
        features = rng.normal(size=180)
        noise = rng.normal(scale=0.25, size=180)
        targets = np.zeros(180)
        targets[1:] = -1.2 * features[:-1] + noise[1:] + entity_index * 0.01
        for index in range(180):
            observations.append(
                Observation(
                    date=start + timedelta(days=index),
                    entity_id=entity,
                    values={
                        "financial_stress_narrative": float(features[index]),
                        "fx_return_usd": float(targets[index]),
                    },
                )
            )
    return observations


def _demo_spec() -> HypothesisSpec:
    return HypothesisSpec.model_validate(
        {
            "claim": "Higher media-observed financial stress predicts local-currency depreciation.",
            "universe": {
                "entity_type": "country",
                "start_date": "2024-01-01",
                "end_date": "2024-06-28",
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
            "robustness": {"placebo_repeats": 5},
            "decision_rule": {"min_oos_r2": 0.05},
        }
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hello-gdelt")
    subparsers = parser.add_subparsers(dest="command", required=True)
    hypothesis = subparsers.add_parser("hypothesis")
    hypothesis_sub = hypothesis.add_subparsers(dest="hypothesis_command", required=True)

    validate = hypothesis_sub.add_parser("validate")
    validate.add_argument("spec", type=Path)

    compile_parser = hypothesis_sub.add_parser("compile")
    compile_parser.add_argument("spec", type=Path)

    demo = hypothesis_sub.add_parser("demo")
    demo.add_argument("--registry", type=Path, default=Path("data/control/hypothesis.sqlite"))
    demo.add_argument("--report", type=Path, default=Path("reports/hypothesis_demo.md"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.hypothesis_command == "validate":
            spec = _load_spec(args.spec)
            print(spec.model_dump_json(indent=2))
            return 0
        if args.hypothesis_command == "compile":
            plan = HypothesisCompiler(default_catalog()).compile(_load_spec(args.spec))
            print(plan.model_dump_json(indent=2))
            return 0
        if args.hypothesis_command == "demo":
            spec = _demo_spec()
            plan = HypothesisCompiler(default_catalog()).compile(spec)
            provider = InMemoryDatasetProvider(_demo_observations(), "synthetic_demo_v1")
            result = HypothesisRunner().run(plan, provider)
            registry = HypothesisRegistry(args.registry)
            registry.register(spec, plan)
            registry.save_result(result)
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(render_markdown(plan, result), encoding="utf-8")
            print(json.dumps(result.model_dump(mode="json"), indent=2, default=str))
            return 0
    except (OSError, ValueError, ValidationError, CompilationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
