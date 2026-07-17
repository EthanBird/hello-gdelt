from __future__ import annotations

from dataclasses import dataclass, field

from .schema import EntityType, FeatureDefinition, TargetDefinition, Transform


class CatalogError(ValueError):
    """Raised when an artifact cannot be resolved safely."""


@dataclass(slots=True)
class Catalog:
    features: dict[str, FeatureDefinition] = field(default_factory=dict)
    targets: dict[str, TargetDefinition] = field(default_factory=dict)

    def register_feature(self, definition: FeatureDefinition) -> None:
        if definition.feature_id in self.features:
            raise CatalogError(f"feature already registered: {definition.feature_id}")
        self.features[definition.feature_id] = definition

    def register_target(self, definition: TargetDefinition) -> None:
        if definition.target_id in self.targets:
            raise CatalogError(f"target already registered: {definition.target_id}")
        self.targets[definition.target_id] = definition

    def resolve_feature(self, feature_id: str) -> FeatureDefinition:
        try:
            return self.features[feature_id]
        except KeyError as exc:
            raise CatalogError(f"unknown feature: {feature_id}") from exc

    def resolve_target(self, target_id: str) -> TargetDefinition:
        try:
            return self.targets[target_id]
        except KeyError as exc:
            raise CatalogError(f"unknown target: {target_id}") from exc


def default_catalog() -> Catalog:
    catalog = Catalog()
    transforms = (
        Transform.IDENTITY,
        Transform.ZSCORE,
        Transform.EXPOSURE_ADJUSTED_ZSCORE,
        Transform.LOG1P,
        Transform.DIFFERENCE,
    )
    country_features = {
        "domestic_risk_pressure": "Media-observed domestic risk pressure.",
        "financial_stress_narrative": "Financial-stress narrative intensity.",
        "policy_hawkishness": "Media-observed monetary-policy hawkishness.",
        "policy_uncertainty": "Monetary-policy uncertainty narrative.",
        "social_unrest_pressure": "Protest and unrest narrative pressure.",
        "external_conflict_pressure": "External material and verbal conflict pressure.",
        "bilateral_tension": "Directed bilateral tension score.",
        "media_attention_shock": "Exposure-adjusted abnormal media attention.",
        "vix": "VIX control series.",
        "dxy": "US dollar index control series.",
        "rate_differential": "Local-minus-US policy or short-rate differential.",
    }
    for feature_id, description in country_features.items():
        entity_type = EntityType.PAIR if feature_id == "bilateral_tension" else EntityType.COUNTRY
        catalog.register_feature(
            FeatureDefinition(
                feature_id=feature_id,
                entity_type=entity_type,
                allowed_transforms=transforms,
                description=description,
            )
        )

    country_targets = {
        "fx_return_usd": "Future local-currency return against USD.",
        "equity_return": "Future local equity-index return.",
        "short_rate_change": "Future short-rate or OIS change.",
        "sovereign_spread_change": "Future sovereign spread change.",
        "future_material_conflict": "Future material-conflict intensity.",
    }
    for target_id, description in country_targets.items():
        entity_type = EntityType.PAIR if target_id == "future_material_conflict" else EntityType.COUNTRY
        catalog.register_target(
            TargetDefinition(
                target_id=target_id,
                entity_type=entity_type,
                description=description,
            )
        )
    return catalog
