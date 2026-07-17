from pathlib import Path

import pytest
import yaml

from hello_gdelt.research.registry import (
    RegistryValidationError,
    load_asset_universe,
    materialize_hypotheses,
)

ROOT = Path(__file__).parents[1]


def test_frozen_asset_universe_has_103_unique_assets() -> None:
    assets = load_asset_universe(ROOT / "config" / "asset_universe.yaml")
    assert len(assets) == 103
    assert len({asset.asset_id for asset in assets}) == 103
    assert sum(asset.proxy for asset in assets) == 6


def test_frozen_hypotheses_materialize_to_96_stable_ids() -> None:
    cells = materialize_hypotheses(ROOT / "config" / "hypothesis_registry.yaml")
    assert len(cells) == 96
    assert cells[0].hypothesis_id == "H001"
    assert cells[-1].hypothesis_id == "H096"
    assert len({(cell.family, cell.market_group) for cell in cells}) == 96


def test_asset_count_drift_is_rejected(tmp_path: Path) -> None:
    source = yaml.safe_load((ROOT / "config" / "asset_universe.yaml").read_text())
    source["expected_asset_count"] = 102
    target = tmp_path / "asset_universe.yaml"
    target.write_text(yaml.safe_dump(source), encoding="utf-8")
    with pytest.raises(RegistryValidationError, match="asset count mismatch"):
        load_asset_universe(target)


def test_unlocked_hypotheses_are_rejected(tmp_path: Path) -> None:
    source = yaml.safe_load((ROOT / "config" / "hypothesis_registry.yaml").read_text())
    source["status"] = "DRAFT"
    target = tmp_path / "hypothesis_registry.yaml"
    target.write_text(yaml.safe_dump(source), encoding="utf-8")
    with pytest.raises(RegistryValidationError, match="must be LOCKED"):
        materialize_hypotheses(target)
