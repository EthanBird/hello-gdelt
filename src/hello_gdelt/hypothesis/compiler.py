from __future__ import annotations

from collections.abc import Callable

from .catalog import Catalog, CatalogError
from .schema import ExperimentPlan, HypothesisSpec, ResolvedArtifact


class CompilationError(ValueError):
    """Raised when a hypothesis cannot be compiled into a safe plan."""


class HypothesisCompiler:
    """Resolve a HypothesisSpec only against registered, versioned artifacts."""

    def __init__(
        self,
        catalog: Catalog,
        row_estimator: Callable[[HypothesisSpec], int | None] | None = None,
    ) -> None:
        self._catalog = catalog
        self._row_estimator = row_estimator

    def compile(self, spec: HypothesisSpec) -> ExperimentPlan:
        try:
            feature = self._catalog.resolve_feature(spec.feature.feature_id)
            target = self._catalog.resolve_target(spec.target.target_id)
            controls = tuple(self._catalog.resolve_feature(item) for item in spec.model.controls)
        except CatalogError as exc:
            raise CompilationError(str(exc)) from exc

        if feature.entity_type is not spec.universe.entity_type:
            raise CompilationError(
                f"feature {feature.feature_id} is {feature.entity_type}, "
                f"but universe is {spec.universe.entity_type}"
            )
        if target.entity_type is not spec.universe.entity_type:
            raise CompilationError(
                f"target {target.target_id} is {target.entity_type}, "
                f"but universe is {spec.universe.entity_type}"
            )
        for control in controls:
            if control.entity_type is not spec.universe.entity_type:
                raise CompilationError(
                    f"control {control.feature_id} is incompatible with universe"
                )
        if spec.feature.transform not in feature.allowed_transforms:
            raise CompilationError(
                f"transform {spec.feature.transform} is not allowed for {feature.feature_id}"
            )

        estimated_rows = self._row_estimator(spec) if self._row_estimator else None
        warnings: list[str] = []
        if estimated_rows is not None and estimated_rows > spec.resource_budget.max_rows:
            raise CompilationError(
                f"estimated rows {estimated_rows} exceed max_rows "
                f"{spec.resource_budget.max_rows}"
            )
        if estimated_rows is None:
            warnings.append("row estimate unavailable; runtime budget must be enforced by provider")
        if spec.robustness.placebo_repeats < 10:
            warnings.append("fewer than 10 placebo repeats reduces robustness resolution")

        return ExperimentPlan.build(
            spec=spec,
            feature=ResolvedArtifact(
                artifact_id=feature.feature_id,
                version=feature.version,
                description=feature.description,
            ),
            target=ResolvedArtifact(
                artifact_id=target.target_id,
                version=target.version,
                description=target.description,
            ),
            controls=tuple(
                ResolvedArtifact(
                    artifact_id=item.feature_id,
                    version=item.version,
                    description=item.description,
                )
                for item in controls
            ),
            estimated_rows=estimated_rows,
            warnings=tuple(warnings),
        )
