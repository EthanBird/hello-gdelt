from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from time import monotonic
from typing import Iterable

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict, Field

from .dataset import DatasetProvider, MaterializedDataset
from .decision import DecisionInputs, decide
from .schema import Decision, EffectSign, ExperimentPlan, FixedEffect, PlaceboType
from .statistics import bh_fdr, fit_ols, r2_score


class ResultModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FoldResult(ResultModel):
    fold: int
    train_start: date
    train_end: date
    test_start: date
    test_end: date
    train_rows: int
    test_rows: int
    coefficient: float
    oos_r2: float


class PlaceboResult(ResultModel):
    placebo: PlaceboType
    repeat: int
    oos_r2: float
    coefficient: float


class ExperimentResult(ResultModel):
    run_id: str
    hypothesis_id: str
    plan_hash: str
    started_at: datetime
    finished_at: datetime
    decision: Decision
    decision_reasons: tuple[str, ...]
    observations: int
    entities: int
    periods: int
    coefficient: float
    standard_error: float
    t_value: float
    p_value: float
    q_value: float
    confidence_interval: tuple[float, float]
    oos_r2: float
    fold_sign_agreement: float
    placebo_threshold_r2: float | None
    placebo_outperformed: bool
    condition_number: float
    folds: tuple[FoldResult, ...]
    placebos: tuple[PlaceboResult, ...]
    lineage: dict[str, str]
    warnings: tuple[str, ...] = Field(default_factory=tuple)


@dataclass(slots=True)
class _DesignEncoder:
    include_intercept: bool
    entity_levels: tuple[str, ...]
    time_levels: tuple[date, ...]

    @classmethod
    def fit(
        cls,
        plan: ExperimentPlan,
        dataset: MaterializedDataset,
        mask: NDArray[np.bool_],
    ) -> _DesignEncoder:
        fixed = set(plan.spec.model.fixed_effects)
        entities = (
            tuple(sorted(set(np.asarray(dataset.entities, dtype=object)[mask].tolist())))
            if FixedEffect.ENTITY in fixed
            else ()
        )
        dates = (
            tuple(sorted(set(np.asarray(dataset.dates, dtype=object)[mask].tolist())))
            if FixedEffect.TIME in fixed
            else ()
        )
        return cls(
            include_intercept=plan.spec.model.include_intercept,
            entity_levels=entities,
            time_levels=dates,
        )

    def transform(
        self,
        dataset: MaterializedDataset,
        mask: NDArray[np.bool_],
    ) -> NDArray[np.float64]:
        base = dataset.x[mask].astype(float, copy=True)
        columns: list[NDArray[np.float64]] = []
        if self.include_intercept:
            columns.append(np.ones((base.shape[0], 1), dtype=float))
        columns.append(base)
        entity_values = np.asarray(dataset.entities, dtype=object)[mask]
        date_values = np.asarray(dataset.dates, dtype=object)[mask]
        for level in self.entity_levels[1:]:
            columns.append((entity_values == level).astype(float)[:, None])
        for level in self.time_levels[1:]:
            columns.append((date_values == level).astype(float)[:, None])
        return np.concatenate(columns, axis=1)

    @property
    def primary_index(self) -> int:
        return 1 if self.include_intercept else 0


class HypothesisRunner:
    def run(self, plan: ExperimentPlan, provider: DatasetProvider) -> ExperimentResult:
        started = datetime.now(timezone.utc)
        started_clock = monotonic()
        dataset = provider.materialize(plan)
        self._validate_dataset(plan, dataset)
        folds, oos_r2 = self._walk_forward(plan, dataset)
        full_mask = np.ones(len(dataset.y), dtype=bool)
        encoder = _DesignEncoder.fit(plan, dataset, full_mask)
        full_x = encoder.transform(dataset, full_mask)
        full_fit = fit_ols(full_x, dataset.y)
        primary = encoder.primary_index
        coefficient = float(full_fit.coefficients[primary])
        standard_error = float(full_fit.standard_errors[primary])
        p_value = float(full_fit.p_values[primary])
        q_value = p_value
        agreement = self._fold_sign_agreement(
            [fold.coefficient for fold in folds], plan.spec.expected_sign, coefficient
        )
        placebos = self._run_placebos(plan, dataset)
        threshold = (
            float(np.quantile([item.oos_r2 for item in placebos], 0.95)) if placebos else None
        )
        placebo_outperformed = threshold is None or oos_r2 > threshold
        outcome = decide(
            DecisionInputs(
                coefficient=coefficient,
                q_value=q_value,
                oos_r2=oos_r2,
                fold_sign_agreement=agreement,
                placebo_outperformed=placebo_outperformed,
            ),
            plan.spec.expected_sign,
            plan.spec.decision_rule,
        )
        warnings = list(plan.warnings)
        if full_fit.condition_number > 1e8:
            warnings.append("design matrix is ill-conditioned")
        elapsed = monotonic() - started_clock
        if elapsed > plan.spec.resource_budget.max_runtime_seconds:
            raise TimeoutError("experiment exceeded max_runtime_seconds")
        run_id = f"run_{plan.plan_hash[:12]}_{int(started.timestamp())}"
        return ExperimentResult(
            run_id=run_id,
            hypothesis_id=plan.hypothesis_id,
            plan_hash=plan.plan_hash,
            started_at=started,
            finished_at=datetime.now(timezone.utc),
            decision=outcome.decision,
            decision_reasons=outcome.reasons,
            observations=len(dataset.y),
            entities=len(set(dataset.entities)),
            periods=len(set(dataset.dates)),
            coefficient=coefficient,
            standard_error=standard_error,
            t_value=float(full_fit.t_values[primary]),
            p_value=p_value,
            q_value=q_value,
            confidence_interval=(
                coefficient - 1.96 * standard_error,
                coefficient + 1.96 * standard_error,
            ),
            oos_r2=oos_r2,
            fold_sign_agreement=agreement,
            placebo_threshold_r2=threshold,
            placebo_outperformed=placebo_outperformed,
            condition_number=full_fit.condition_number,
            folds=tuple(folds),
            placebos=tuple(placebos),
            lineage=dataset.lineage,
            warnings=tuple(warnings),
        )

    def run_batch(
        self,
        jobs: Iterable[tuple[ExperimentPlan, DatasetProvider]],
    ) -> tuple[ExperimentResult, ...]:
        job_list = list(jobs)
        results = [self.run(plan, provider) for plan, provider in job_list]
        q_values = bh_fdr([item.p_value for item in results])
        adjusted: list[ExperimentResult] = []
        for result, q_value in zip(results, q_values, strict=True):
            plan, _ = next(
                (job for job in job_list if job[0].plan_hash == result.plan_hash),
                (None, None),
            )
            if plan is None:
                raise RuntimeError("batch plan lookup failed")
            outcome = decide(
                DecisionInputs(
                    coefficient=result.coefficient,
                    q_value=q_value,
                    oos_r2=result.oos_r2,
                    fold_sign_agreement=result.fold_sign_agreement,
                    placebo_outperformed=result.placebo_outperformed,
                ),
                plan.spec.expected_sign,
                plan.spec.decision_rule,
            )
            adjusted.append(
                result.model_copy(
                    update={
                        "q_value": q_value,
                        "decision": outcome.decision,
                        "decision_reasons": outcome.reasons,
                    }
                )
            )
        return tuple(adjusted)

    @staticmethod
    def _validate_dataset(plan: ExperimentPlan, dataset: MaterializedDataset) -> None:
        if len(dataset.y) < plan.spec.validation.min_observations:
            raise ValueError(
                f"dataset has {len(dataset.y)} rows; minimum is "
                f"{plan.spec.validation.min_observations}"
            )
        if len(set(dataset.dates)) < (
            plan.spec.validation.min_train_periods + plan.spec.validation.test_periods
        ):
            raise ValueError("not enough periods for walk-forward validation")
        if not np.isfinite(dataset.x).all() or not np.isfinite(dataset.y).all():
            raise ValueError("dataset contains non-finite values")

    def _walk_forward(
        self,
        plan: ExperimentPlan,
        dataset: MaterializedDataset,
    ) -> tuple[list[FoldResult], float]:
        dates = np.asarray(dataset.dates, dtype=object)
        unique_dates = sorted(set(dataset.dates))
        validation = plan.spec.validation
        folds: list[FoldResult] = []
        all_actual: list[float] = []
        all_predicted: list[float] = []
        fold_number = 0
        train_end = validation.min_train_periods
        while train_end + validation.test_periods <= len(unique_dates):
            train_dates = set(unique_dates[:train_end])
            test_dates = set(unique_dates[train_end : train_end + validation.test_periods])
            train_mask = np.asarray([item in train_dates for item in dates], dtype=bool)
            test_mask = np.asarray([item in test_dates for item in dates], dtype=bool)
            encoder = _DesignEncoder.fit(plan, dataset, train_mask)
            x_train = encoder.transform(dataset, train_mask)
            x_test = encoder.transform(dataset, test_mask)
            fit = fit_ols(x_train, dataset.y[train_mask])
            predictions = x_test @ fit.coefficients
            score = r2_score(dataset.y[test_mask], predictions)
            folds.append(
                FoldResult(
                    fold=fold_number,
                    train_start=min(train_dates),
                    train_end=max(train_dates),
                    test_start=min(test_dates),
                    test_end=max(test_dates),
                    train_rows=int(np.sum(train_mask)),
                    test_rows=int(np.sum(test_mask)),
                    coefficient=float(fit.coefficients[encoder.primary_index]),
                    oos_r2=score,
                )
            )
            all_actual.extend(dataset.y[test_mask].tolist())
            all_predicted.extend(predictions.tolist())
            fold_number += 1
            train_end += validation.step_periods
        if not folds:
            raise ValueError("walk-forward produced no folds")
        return folds, r2_score(np.asarray(all_actual), np.asarray(all_predicted))

    def _run_placebos(
        self,
        plan: ExperimentPlan,
        dataset: MaterializedDataset,
    ) -> list[PlaceboResult]:
        results: list[PlaceboResult] = []
        base_seed = plan.spec.robustness.random_seed
        for placebo in plan.spec.robustness.placebos:
            for repeat in range(plan.spec.robustness.placebo_repeats):
                rng = np.random.default_rng(
                    base_seed + repeat + list(PlaceboType).index(placebo) * 10_000
                )
                altered = self._placebo_dataset(dataset, placebo, rng)
                folds, score = self._walk_forward(plan, altered)
                coefficient = float(np.median([fold.coefficient for fold in folds]))
                results.append(
                    PlaceboResult(
                        placebo=placebo,
                        repeat=repeat,
                        oos_r2=score,
                        coefficient=coefficient,
                    )
                )
        return results

    @staticmethod
    def _placebo_dataset(
        dataset: MaterializedDataset,
        placebo: PlaceboType,
        rng: np.random.Generator,
    ) -> MaterializedDataset:
        x = dataset.x.copy()
        y = dataset.y.copy()
        entities = np.asarray(dataset.entities, dtype=object)
        dates = np.asarray(dataset.dates, dtype=object)
        if placebo is PlaceboType.SHUFFLE_DATE:
            for entity in set(dataset.entities):
                indices = np.flatnonzero(entities == entity)
                y[indices] = rng.permutation(y[indices])
        elif placebo is PlaceboType.SHUFFLE_ENTITY:
            for day in set(dataset.dates):
                indices = np.flatnonzero(dates == day)
                y[indices] = rng.permutation(y[indices])
        elif placebo is PlaceboType.REVERSE_TIME:
            for entity in set(dataset.entities):
                indices = np.flatnonzero(entities == entity)
                y[indices] = y[indices][::-1]
        elif placebo is PlaceboType.RANDOM_FEATURE:
            x[:, 0] = rng.permutation(x[:, 0])
        else:
            raise ValueError(f"unsupported placebo: {placebo}")
        return MaterializedDataset(
            dates=dataset.dates,
            entities=dataset.entities,
            feature_names=dataset.feature_names,
            x=x,
            y=y,
            lineage={**dataset.lineage, "placebo": placebo.value},
        )

    @staticmethod
    def _fold_sign_agreement(
        coefficients: list[float],
        expected: EffectSign,
        overall: float,
    ) -> float:
        if not coefficients:
            return 0.0
        if expected is EffectSign.POSITIVE:
            matches = [value > 0 for value in coefficients]
        elif expected is EffectSign.NEGATIVE:
            matches = [value < 0 for value in coefficients]
        else:
            reference_positive = overall >= 0
            matches = [(value >= 0) == reference_positive for value in coefficients]
        return float(np.mean(matches))
