import pytest

from hello_gdelt.gdelt.fields import (
    EVENT_COLUMNS,
    GKG_COLUMNS,
    MENTION_COLUMNS,
    semantic_column_names,
)
from hello_gdelt.gdelt.schema import CONTRACTS


@pytest.mark.parametrize(
    ("dataset", "columns"),
    [
        ("events", EVENT_COLUMNS),
        ("mentions", MENTION_COLUMNS),
        ("gkg", GKG_COLUMNS),
    ],
)
def test_semantic_columns_match_raw_width_contract(dataset: str, columns: tuple[str, ...]) -> None:
    assert len(columns) == CONTRACTS[dataset].expected_columns
    assert len(set(columns)) == len(columns)
    assert semantic_column_names(dataset) == columns


def test_event_columns_pin_market_relevant_positions() -> None:
    assert EVENT_COLUMNS[0] == "global_event_id"
    assert EVENT_COLUMNS[30] == "goldstein_scale"
    assert EVENT_COLUMNS[34] == "avg_tone"
    assert EVENT_COLUMNS[59] == "date_added"
    assert EVENT_COLUMNS[60] == "source_url"


def test_mentions_columns_pin_propagation_fields() -> None:
    assert MENTION_COLUMNS[2] == "mention_time_date"
    assert MENTION_COLUMNS[4] == "mention_source_name"
    assert MENTION_COLUMNS[13] == "mention_doc_tone"


def test_gkg_columns_pin_article_entity_and_tone_fields() -> None:
    assert GKG_COLUMNS[4] == "v2_document_identifier"
    assert GKG_COLUMNS[8] == "v2_enhanced_themes"
    assert GKG_COLUMNS[12] == "v2_enhanced_persons"
    assert GKG_COLUMNS[14] == "v2_enhanced_organizations"
    assert GKG_COLUMNS[15] == "v1_5_tone"
