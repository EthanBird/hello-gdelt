from __future__ import annotations

from datetime import date, datetime, timezone
from enum import StrEnum
from hashlib import sha256
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Identifier = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z][a-z0-9_]{2,63}$", strip_whitespace=True),
]
VersionIdentifier = Annotated[
    str,
    StringConstraints(pattern=r"^v[0-9][A-Za-z0-9_.-]{0,31}$", strip_whitespace=True),
]
EntityIdentifier = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$", strip_whitespace=True),
]
ScalarFilter = str | int | float | bool


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class EntityType(StrEnum):
    COUNTRY = "country"
    PAIR = "pair"
    ORGANIZATION = "organization"
    MARKET = "market"


class Transform(StrEnum):
    IDENTITY = "identity"
    ZSCORE = "zscore"
    EXPOSURE_ADJUSTED_ZSCORE = "exposure_adjusted_zscore"
    LOG1P = "log1p"
    DIFFERENCE = "difference"


class ModelType(StrEnum):
    OLS = "ols"
    PANEL_OLS = "panel_ols"


class FixedEffect(StrEnum):
    ENTITY = "entity"
    TIME = "time"


class EffectSign(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NONZERO = "nonzero"


class PlaceboType(StrEnum):
    SHUFFLE_DATE = "shuffle_date"
    SHUFFLE_ENTITY = "shuffle_entity"
    REVERSE_TIME = "reverse_time"
    RANDOM_FEATURE = "random_feature"


class Decision(StrEnum):
    SUPPORTED = "supported"
    REJECTED = "rejected"
    INCONCLUSIVE = "inconclusive"


class UniverseSpec(StrictModel):
    entity_type: EntityType
    start_date: date
    end_date: date
    entities: tuple[EntityIdentifier, ...] = ()
    filters: dict[Identifier, ScalarFilter | tuple[ScalarFilter, ...]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_dates_and_entities(self) -> UniverseSpec:
        if self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date")
        if len(self.entities) > 200:
            raise ValueError("a hypothesis may reference at most 200 entities")
        if len(set(self.entities)) != len(self.entities):
            raise ValueError("entities must be unique")
        return self


class FeatureSpec(StrictModel):
    feature_id: Identifier
    transform: Transform = Transform.IDENTITY
    window_days: int = Field(default=7, ge=1, le=3650)
    lag_days: int = Field(default=0, ge=0, le=365)


class TargetSpec(StrictModel):
    target_id: Identifier
    horizon_days: int = Field(default=1, ge=0, le=365)


class ModelSpec(StrictModel):
    type: ModelType
    controls: tuple[Identifier, ...] = ()
    fixed_effects: tuple[FixedEffect, ...] = ()
    include_intercept: bool = True

    @model_validator(mode="after")
    def validate_model(self) -> ModelSpec:
        if len(self.controls) > 20:
            raise ValueError("at most 20 controls are allowed")
        if len(set(self.controls)) != len(self.controls):
            raise ValueError("controls must be unique")
        if len(set(self.fixed_effects)) != len(self.fixed_effects):
            raise ValueError("fixed_effects must be unique")
        if self.type is ModelType.OLS and self.fixed_effects:
            raise ValueError("fixed_effects require panel_ols")
        return self


class ValidationSpec(StrictModel):
    method: Literal["walk_forward"] = "walk_forward"
    min_train_periods: int = Field(default=60, ge=20, le=10000)
    test_periods: int = Field(default=20, ge=1, le=1000)
    step_periods: int = Field(default=20, ge=1, le=1000)
    min_observations: int = Field(default=100, ge=30, le=10_000_000)
    alpha: float = Field(default=0.05, gt=0.0, le=0.2)


class RobustnessSpec(StrictModel):
    placebos: tuple[PlaceboType, ...] = (
        PlaceboType.SHUFFLE_DATE,
        PlaceboType.SHUFFLE_ENTITY,
        PlaceboType.RANDOM_FEATURE,
    )
    placebo_repeats: int = Field(default=10, ge=1, le=100)
    random_seed: int = Field(default=20260717, ge=0, le=2**32 - 1)
    alternative_windows: tuple[int, ...] = ()

    @model_validator(mode="after")
    def validate_robustness(self) -> RobustnessSpec:
        if len(set(self.placebos)) != len(self.placebos):
            raise ValueError("placebos must be unique")
        if len(set(self.alternative_windows)) != len(self.alternative_windows):
            raise ValueError("alternative_windows must be unique")
        if any(window < 1 or window > 3650 for window in self.alternative_windows):
            raise ValueError("alternative_windows must be between 1 and 3650")
        return self


class DecisionRule(StrictModel):
    max_q_value: float = Field(default=0.05, gt=0.0, le=0.2)
    min_effect_abs: float = Field(default=0.0, ge=0.0)
    min_fold_sign_agreement: float = Field(default=0.6, ge=0.5, le=1.0)
    min_oos_r2: float = Field(default=-0.05, ge=-10.0, le=1.0)
    require_placebo_outperformance: bool = True


class ResourceBudget(StrictModel):
    max_rows: int = Field(default=2_000_000, ge=100, le=20_000_000)
    max_entities: int = Field(default=200, ge=1, le=1000)
    max_runtime_seconds: int = Field(default=900, ge=1, le=86_400)
    max_memory_mb: int = Field(default=4096, ge=128, le=24_576)


class HypothesisSpec(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    hypothesis_id: Identifier | None = None
    claim: Annotated[str, StringConstraints(min_length=20, max_length=2000)]
    universe: UniverseSpec
    feature: FeatureSpec
    target: TargetSpec
    model: ModelSpec
    expected_sign: EffectSign
    validation: ValidationSpec = Field(default_factory=ValidationSpec)
    robustness: RobustnessSpec = Field(default_factory=RobustnessSpec)
    decision_rule: DecisionRule = Field(default_factory=DecisionRule)
    resource_budget: ResourceBudget = Field(default_factory=ResourceBudget)
    tags: tuple[Identifier, ...] = ()

    @model_validator(mode="after")
    def validate_cross_fields(self) -> HypothesisSpec:
        if self.feature.feature_id == self.target.target_id:
            raise ValueError("feature and target must be different")
        if self.feature.feature_id in self.model.controls:
            raise ValueError("primary feature cannot also be a control")
        if len(set(self.tags)) != len(self.tags):
            raise ValueError("tags must be unique")
        if self.universe.entities and len(self.universe.entities) > self.resource_budget.max_entities:
            raise ValueError("entity count exceeds resource budget")
        return self

    def canonical_json(self) -> str:
        return self.model_dump_json(exclude_none=True, by_alias=True)

    def deterministic_id(self) -> str:
        if self.hypothesis_id:
            return self.hypothesis_id
        digest = sha256(self.canonical_json().encode("utf-8")).hexdigest()[:16]
        return f"h_{digest}"


class FeatureDefinition(StrictModel):
    feature_id: Identifier
    entity_type: EntityType
    allowed_transforms: tuple[Transform, ...]
    description: str
    version: VersionIdentifier = "v1"


class TargetDefinition(StrictModel):
    target_id: Identifier
    entity_type: EntityType
    description: str
    version: VersionIdentifier = "v1"


class ResolvedArtifact(StrictModel):
    artifact_id: Identifier
    version: VersionIdentifier
    description: str


class ExperimentPlan(StrictModel):
    plan_version: Literal["1.0"] = "1.0"
    hypothesis_id: Identifier
    plan_hash: str
    compiled_at: datetime
    spec: HypothesisSpec
    feature: ResolvedArtifact
    target: ResolvedArtifact
    controls: tuple[ResolvedArtifact, ...]
    estimated_rows: int | None = None
    warnings: tuple[str, ...] = ()

    @classmethod
    def build(
        cls,
        *,
        spec: HypothesisSpec,
        feature: ResolvedArtifact,
        target: ResolvedArtifact,
        controls: tuple[ResolvedArtifact, ...],
        estimated_rows: int | None,
        warnings: tuple[str, ...],
    ) -> ExperimentPlan:
        hypothesis_id = spec.deterministic_id()
        payload: dict[str, Any] = {
            "hypothesis_id": hypothesis_id,
            "spec": spec.model_dump(mode="json", exclude_none=True),
            "feature": feature.model_dump(mode="json"),
            "target": target.model_dump(mode="json"),
            "controls": [item.model_dump(mode="json") for item in controls],
        }
        digest = sha256(
            __import__("json").dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return cls(
            hypothesis_id=hypothesis_id,
            plan_hash=digest,
            compiled_at=datetime.now(timezone.utc),
            spec=spec,
            feature=feature,
            target=target,
            controls=controls,
            estimated_rows=estimated_rows,
            warnings=warnings,
        )
