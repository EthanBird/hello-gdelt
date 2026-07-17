from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Protocol

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict, Field

from .schema import ExperimentPlan, Transform


class Observation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    date: date
    entity_id: str
    values: dict[str, float] = Field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MaterializedDataset:
    dates: tuple[date, ...]
    entities: tuple[str, ...]
    feature_names: tuple[str, ...]
    x: NDArray[np.float64]
    y: NDArray[np.float64]
    lineage: dict[str, str]

    def __post_init__(self) -> None:
        row_count = len(self.dates)
        if len(self.entities) != row_count or self.x.shape[0] != row_count:
            raise ValueError("dataset row dimensions are inconsistent")
        if self.y.shape != (row_count,):
            raise ValueError("target dimensions are inconsistent")
        if self.x.shape[1] != len(self.feature_names):
            raise ValueError("feature name count is inconsistent")


class DatasetProvider(Protocol):
    def materialize(self, plan: ExperimentPlan) -> MaterializedDataset: ...


class InMemoryDatasetProvider:
    """Reference provider used by tests and small reproducible experiments.

    Lag and horizon are expressed in ordered observations per entity. Production
    providers must record their calendar/trading-day alignment semantics in lineage.
    """

    def __init__(self, observations: list[Observation], dataset_id: str = "in_memory_v1") -> None:
        self._observations = observations
        self._dataset_id = dataset_id

    def materialize(self, plan: ExperimentPlan) -> MaterializedDataset:
        spec = plan.spec
        requested = (
            plan.feature.artifact_id,
            *(item.artifact_id for item in plan.controls),
            plan.target.artifact_id,
        )
        grouped: dict[str, list[Observation]] = defaultdict(list)
        allowed_entities = set(spec.universe.entities)
        for item in self._observations:
            if item.date < spec.universe.start_date or item.date > spec.universe.end_date:
                continue
            if allowed_entities and item.entity_id not in allowed_entities:
                continue
            if all(name in item.values for name in requested):
                grouped[item.entity_id].append(item)

        rows: list[tuple[date, str, list[float], float]] = []
        lag = spec.feature.lag_days
        horizon = spec.target.horizon_days
        feature_names = (plan.feature.artifact_id, *(item.artifact_id for item in plan.controls))
        for entity_id, entity_rows in grouped.items():
            ordered = sorted(entity_rows, key=lambda item: item.date)
            for index in range(lag, len(ordered) - horizon):
                feature_row = ordered[index - lag]
                target_row = ordered[index + horizon]
                values = [float(feature_row.values[name]) for name in feature_names]
                target = float(target_row.values[plan.target.artifact_id])
                if np.isfinite(values).all() and np.isfinite(target):
                    rows.append((feature_row.date, entity_id, values, target))

        if len(rows) > spec.resource_budget.max_rows:
            raise ValueError("materialized dataset exceeds max_rows")
        entities = {row[1] for row in rows}
        if len(entities) > spec.resource_budget.max_entities:
            raise ValueError("materialized dataset exceeds max_entities")
        if not rows:
            raise ValueError("no observations match the hypothesis")

        rows.sort(key=lambda row: (row[0], row[1]))
        x = np.asarray([row[2] for row in rows], dtype=float)
        x[:, 0] = self._transform(x[:, 0], spec.feature.transform)
        return MaterializedDataset(
            dates=tuple(row[0] for row in rows),
            entities=tuple(row[1] for row in rows),
            feature_names=feature_names,
            x=x,
            y=np.asarray([row[3] for row in rows], dtype=float),
            lineage={
                "dataset_id": self._dataset_id,
                "alignment": "ordered_observation_periods",
                "feature_version": plan.feature.version,
                "target_version": plan.target.version,
                "plan_hash": plan.plan_hash,
            },
        )

    @staticmethod
    def _transform(values: NDArray[np.float64], transform: Transform) -> NDArray[np.float64]:
        if transform is Transform.IDENTITY or transform is Transform.EXPOSURE_ADJUSTED_ZSCORE:
            return values
        if transform is Transform.ZSCORE:
            std = float(np.std(values))
            return (values - float(np.mean(values))) / (std if std > 0 else 1.0)
        if transform is Transform.LOG1P:
            if np.any(values <= -1):
                raise ValueError("log1p transform requires values greater than -1")
            return np.log1p(values)
        if transform is Transform.DIFFERENCE:
            result = np.empty_like(values)
            result[0] = 0.0
            result[1:] = np.diff(values)
            return result
        raise ValueError(f"unsupported transform: {transform}")
