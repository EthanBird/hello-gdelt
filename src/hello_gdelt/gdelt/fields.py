from __future__ import annotations

"""Pinned semantic column order for the GDELT 2.x raw TSV contracts.

The raw Bronze layer deliberately preserves generic positional names. These tuples are
used only when projecting a validated 61/16/27-column record into the Silver layer.
They are pinned to the GDELT 2.0 Event/EventMentions and GKG 2.1 codebooks referenced
by the official GDELT 2.0 launch documentation.
"""

EVENT_COLUMNS: tuple[str, ...] = (
    "global_event_id",
    "sql_date",
    "month_year",
    "year",
    "fraction_date",
    "actor1_code",
    "actor1_name",
    "actor1_country_code",
    "actor1_known_group_code",
    "actor1_ethnic_code",
    "actor1_religion1_code",
    "actor1_religion2_code",
    "actor1_type1_code",
    "actor1_type2_code",
    "actor1_type3_code",
    "actor2_code",
    "actor2_name",
    "actor2_country_code",
    "actor2_known_group_code",
    "actor2_ethnic_code",
    "actor2_religion1_code",
    "actor2_religion2_code",
    "actor2_type1_code",
    "actor2_type2_code",
    "actor2_type3_code",
    "is_root_event",
    "event_code",
    "event_base_code",
    "event_root_code",
    "quad_class",
    "goldstein_scale",
    "num_mentions",
    "num_sources",
    "num_articles",
    "avg_tone",
    "actor1_geo_type",
    "actor1_geo_full_name",
    "actor1_geo_country_code",
    "actor1_geo_adm1_code",
    "actor1_geo_adm2_code",
    "actor1_geo_lat",
    "actor1_geo_long",
    "actor1_geo_feature_id",
    "actor2_geo_type",
    "actor2_geo_full_name",
    "actor2_geo_country_code",
    "actor2_geo_adm1_code",
    "actor2_geo_adm2_code",
    "actor2_geo_lat",
    "actor2_geo_long",
    "actor2_geo_feature_id",
    "action_geo_type",
    "action_geo_full_name",
    "action_geo_country_code",
    "action_geo_adm1_code",
    "action_geo_adm2_code",
    "action_geo_lat",
    "action_geo_long",
    "action_geo_feature_id",
    "date_added",
    "source_url",
)

MENTION_COLUMNS: tuple[str, ...] = (
    "global_event_id",
    "event_time_date",
    "mention_time_date",
    "mention_type",
    "mention_source_name",
    "mention_identifier",
    "sentence_id",
    "actor1_char_offset",
    "actor2_char_offset",
    "action_char_offset",
    "in_raw_text",
    "confidence",
    "mention_doc_len",
    "mention_doc_tone",
    "mention_doc_translation_info",
    "extras",
)

GKG_COLUMNS: tuple[str, ...] = (
    "gkg_record_id",
    "v2_1_date",
    "v2_source_collection_identifier",
    "v2_source_common_name",
    "v2_document_identifier",
    "v1_counts",
    "v2_1_counts",
    "v1_themes",
    "v2_enhanced_themes",
    "v1_locations",
    "v2_enhanced_locations",
    "v1_persons",
    "v2_enhanced_persons",
    "v1_organizations",
    "v2_enhanced_organizations",
    "v1_5_tone",
    "v2_1_enhanced_dates",
    "v2_gcam",
    "v2_1_sharing_image",
    "v2_1_related_images",
    "v2_1_social_image_embeds",
    "v2_1_social_video_embeds",
    "v2_1_quotations",
    "v2_1_all_names",
    "v2_1_amounts",
    "v2_1_translation_info",
    "v2_extras_xml",
)

SEMANTIC_COLUMNS: dict[str, tuple[str, ...]] = {
    "events": EVENT_COLUMNS,
    "mentions": MENTION_COLUMNS,
    "gkg": GKG_COLUMNS,
}


def semantic_column_names(dataset: str) -> tuple[str, ...]:
    try:
        return SEMANTIC_COLUMNS[dataset]
    except KeyError as exc:
        raise KeyError(f"unknown GDELT semantic schema: {dataset}") from exc
