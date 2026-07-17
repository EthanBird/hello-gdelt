from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml


class RegistryValidationError(ValueError):
    """Raised when a frozen research registry violates its declared contract."""


@dataclass(frozen=True, slots=True)
class Asset:
    asset_id: str
    name: str
    asset_type: str
    provider_symbol: str | None
    exchange: str
    timezone: str
    currency: str
    primary_source: str
    proxy: bool
    market_group: str


@dataclass(frozen=True, slots=True)
class HypothesisCell:
    hypothesis_id: str
    family: str
    market_group: str
    exposure: str
    outcome: str
    expected_direction: str
    primary_model: str


def _read_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RegistryValidationError(f"registry must be a mapping: {path}")
    return payload


def load_asset_universe(path: Path) -> tuple[Asset, ...]:
    payload = _read_yaml(path)
    columns = payload.get("columns")
    expected_columns = [
        "asset_id",
        "name",
        "asset_type",
        "provider_symbol",
        "exchange",
        "timezone",
        "currency",
        "primary_source",
        "proxy",
    ]
    if columns != expected_columns:
        raise RegistryValidationError("asset universe columns do not match the frozen contract")

    groups = payload.get("market_groups")
    if not isinstance(groups, dict) or not groups:
        raise RegistryValidationError("asset universe contains no market groups")

    assets: list[Asset] = []
    seen: set[str] = set()
    for market_group, group_spec in groups.items():
        if not isinstance(group_spec, dict):
            raise RegistryValidationError(f"market group {market_group} must be a mapping")
        rows = group_spec.get("assets")
        if not isinstance(rows, list) or not rows:
            raise RegistryValidationError(f"market group {market_group} has no assets")
        for row_number, row in enumerate(rows, start=1):
            if not isinstance(row, list) or len(row) != len(expected_columns):
                raise RegistryValidationError(
                    f"{market_group} row {row_number}: expected {len(expected_columns)} columns"
                )
            values = dict(zip(expected_columns, row, strict=True))
            asset_id = values["asset_id"]
            if not isinstance(asset_id, str) or not asset_id:
                raise RegistryValidationError(f"{market_group} row {row_number}: invalid asset_id")
            if asset_id in seen:
                raise RegistryValidationError(f"duplicate asset_id: {asset_id}")
            seen.add(asset_id)
            timezone = values["timezone"]
            try:
                ZoneInfo(timezone)
            except (ZoneInfoNotFoundError, TypeError) as exc:
                raise RegistryValidationError(
                    f"{asset_id}: invalid IANA timezone {timezone!r}"
                ) from exc
            proxy = values["proxy"]
            if not isinstance(proxy, bool):
                raise RegistryValidationError(f"{asset_id}: proxy must be boolean")
            if market_group == "LONDON_PROXY" and not proxy:
                raise RegistryValidationError(f"{asset_id}: London proxy assets must be marked proxy")
            assets.append(Asset(market_group=market_group, **values))

    declared = payload.get("expected_asset_count")
    if declared != len(assets):
        raise RegistryValidationError(
            f"asset count mismatch: declared={declared!r}, materialized={len(assets)}"
        )
    return tuple(assets)


def materialize_hypotheses(path: Path) -> tuple[HypothesisCell, ...]:
    payload = _read_yaml(path)
    if payload.get("status") != "LOCKED":
        raise RegistryValidationError("confirmatory hypothesis registry must be LOCKED")
    market_groups = payload.get("market_groups")
    families = payload.get("families")
    if not isinstance(market_groups, list) or len(set(market_groups)) != len(market_groups):
        raise RegistryValidationError("market_groups must be a unique non-empty list")
    if not isinstance(families, list) or not families:
        raise RegistryValidationError("families must be a non-empty list")

    cells: list[HypothesisCell] = []
    seen_families: set[str] = set()
    index = 1
    required = {
        "family",
        "exposure",
        "outcome",
        "expected_direction",
        "primary_model",
    }
    for family_spec in families:
        if not isinstance(family_spec, dict) or not required.issubset(family_spec):
            raise RegistryValidationError("each hypothesis family must include all frozen fields")
        family = family_spec["family"]
        if family in seen_families:
            raise RegistryValidationError(f"duplicate hypothesis family: {family}")
        seen_families.add(family)
        for market_group in market_groups:
            cells.append(
                HypothesisCell(
                    hypothesis_id=f"H{index:03d}",
                    family=family,
                    market_group=market_group,
                    exposure=family_spec["exposure"],
                    outcome=family_spec["outcome"],
                    expected_direction=family_spec["expected_direction"],
                    primary_model=family_spec["primary_model"],
                )
            )
            index += 1

    declared = payload.get("confirmatory_count")
    if declared != len(cells):
        raise RegistryValidationError(
            f"hypothesis count mismatch: declared={declared!r}, materialized={len(cells)}"
        )
    return tuple(cells)
