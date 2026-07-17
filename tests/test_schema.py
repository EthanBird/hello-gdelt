from __future__ import annotations

import pytest
from pydantic import ValidationError

from hello_gdelt.hypothesis.schema import HypothesisSpec


def test_rejects_unregistered_execution_fields(base_spec_dict: dict[str, object]) -> None:
    payload = dict(base_spec_dict)
    payload["sql"] = "DROP TABLE hypothesis"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        HypothesisSpec.model_validate(payload)


def test_rejects_resource_overflow(base_spec_dict: dict[str, object]) -> None:
    payload = dict(base_spec_dict)
    payload["resource_budget"] = {"max_entities": 2}
    with pytest.raises(ValidationError, match="entity count exceeds resource budget"):
        HypothesisSpec.model_validate(payload)


def test_deterministic_id_is_stable(base_spec_dict: dict[str, object]) -> None:
    first = HypothesisSpec.model_validate(base_spec_dict)
    second = HypothesisSpec.model_validate(base_spec_dict)
    assert first.deterministic_id() == second.deterministic_id()
