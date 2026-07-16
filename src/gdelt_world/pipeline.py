from __future__ import annotations

import hashlib
import re
from datetime import UTC, date, datetime
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from gdelt_world.control import (
    connect_control,
    record_validation,
    register_artifact,
    register_source_file,
    sha256_file,
)
from gdelt_world.schemas import EVENT_FIELDS, inspect_zip, iter_tsv_rows
from gdelt_world.source import file_md5

BATCH_PATTERN = re.compile(r"(\d{14})\.export\.CSV\.zip$")
RELATION_CLASS = {
    1: "verbal_cooperation",
    2: "material_cooperation",
    3: "verbal_conflict",
    4: "material_conflict",
}


def _batch_id(path: Path) -> str:
    match = BATCH_PATTERN.search(path.name)
    if not match:
        raise ValueError(f"cannot infer GDELT batch from {path.name}")
    return match.group(1)


def _int(value: str) -> int | None:
    return int(value) if value else None


def _float(value: str) -> float | None:
    return float(value) if value else None


def _date(value: str) -> date | None:
    return datetime.strptime(value, "%Y%m%d").date() if value else None


def _timestamp(value: str) -> datetime | None:
    if not value:
        return None
    return datetime.strptime(value, "%Y%m%d%H%M%S").replace(tzinfo=UTC)


def _quote_path(path: Path) -> str:
    return str(path).replace("'", "''")


def write_bronze_events(events_zip: Path, destination: Path) -> int:
    columns: dict[str, list[object]] = {field: [] for field in EVENT_FIELDS}
    columns["_source_archive"] = []
    columns["_source_row_number"] = []
    columns["_ingested_at"] = []
    ingested_at = datetime.now(UTC)

    for row_number, row in iter_tsv_rows(events_zip, "events"):
        if len(row) != len(EVENT_FIELDS):
            raise ValueError(f"events row {row_number}: expected 61 fields, got {len(row)}")
        for field, value in zip(EVENT_FIELDS, row, strict=True):
            columns[field].append(value)
        columns["_source_archive"].append(events_zip.name)
        columns["_source_row_number"].append(row_number)
        columns["_ingested_at"].append(ingested_at)

    schema = pa.schema(
        [
            *(pa.field(field, pa.string()) for field in EVENT_FIELDS),
            pa.field("_source_archive", pa.string()),
            pa.field("_source_row_number", pa.int64()),
            pa.field("_ingested_at", pa.timestamp("us", tz="UTC")),
        ]
    )
    table = pa.Table.from_pydict(columns, schema=schema)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    pq.write_table(table, temporary, compression="zstd", row_group_size=100_000)
    temporary.replace(destination)
    return table.num_rows


def write_silver_world_event(bronze_path: Path, destination: Path, *, batch_id: str) -> int:
    bronze = pq.read_table(bronze_path)
    records: list[dict[str, object]] = []
    seen: set[str] = set()
    for row in bronze.to_pylist():
        global_event_id = _int(row["GLOBALEVENTID"])
        date_added = _timestamp(row["DATEADDED"])
        dedupe_material = f"{global_event_id}|{row['DATEADDED']}".encode()
        dedupe_key = hashlib.sha256(dedupe_material).hexdigest()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        quad_class = _int(row["QuadClass"])
        records.append(
            {
                "dedupe_key": dedupe_key,
                "global_event_id": global_event_id,
                "event_date": _date(row["SQLDATE"]),
                "date_added": date_added,
                "actor1_code": row["Actor1Code"] or None,
                "actor1_name": row["Actor1Name"] or None,
                "actor1_country_code": row["Actor1CountryCode"] or None,
                "actor2_code": row["Actor2Code"] or None,
                "actor2_name": row["Actor2Name"] or None,
                "actor2_country_code": row["Actor2CountryCode"] or None,
                "event_code": row["EventCode"] or None,
                "event_base_code": row["EventBaseCode"] or None,
                "event_root_code": row["EventRootCode"] or None,
                "quad_class": quad_class,
                "relation_class": RELATION_CLASS.get(quad_class, "unknown"),
                "goldstein_scale": _float(row["GoldsteinScale"]),
                "num_mentions": _int(row["NumMentions"]),
                "num_sources": _int(row["NumSources"]),
                "num_articles": _int(row["NumArticles"]),
                "avg_tone": _float(row["AvgTone"]),
                "action_country_code": row["ActionGeo_CountryCode"] or None,
                "action_latitude": _float(row["ActionGeo_Lat"]),
                "action_longitude": _float(row["ActionGeo_Long"]),
                "source_url": row["SOURCEURL"] or None,
                "batch_id": batch_id,
                "mapping_version": "relation_quadclass_v1",
            }
        )

    schema = pa.schema(
        [
            pa.field("dedupe_key", pa.string(), nullable=False),
            pa.field("global_event_id", pa.int64(), nullable=False),
            pa.field("event_date", pa.date32()),
            pa.field("date_added", pa.timestamp("us", tz="UTC")),
            pa.field("actor1_code", pa.string()),
            pa.field("actor1_name", pa.string()),
            pa.field("actor1_country_code", pa.string()),
            pa.field("actor2_code", pa.string()),
            pa.field("actor2_name", pa.string()),
            pa.field("actor2_country_code", pa.string()),
            pa.field("event_code", pa.string()),
            pa.field("event_base_code", pa.string()),
            pa.field("event_root_code", pa.string()),
            pa.field("quad_class", pa.int8()),
            pa.field("relation_class", pa.string(), nullable=False),
            pa.field("goldstein_scale", pa.float64()),
            pa.field("num_mentions", pa.int32()),
            pa.field("num_sources", pa.int32()),
            pa.field("num_articles", pa.int32()),
            pa.field("avg_tone", pa.float64()),
            pa.field("action_country_code", pa.string()),
            pa.field("action_latitude", pa.float64()),
            pa.field("action_longitude", pa.float64()),
            pa.field("source_url", pa.string()),
            pa.field("batch_id", pa.string(), nullable=False),
            pa.field("mapping_version", pa.string(), nullable=False),
        ]
    )
    table = pa.Table.from_pylist(records, schema=schema)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    pq.write_table(table, temporary, compression="zstd", row_group_size=100_000)
    temporary.replace(destination)
    return table.num_rows


def write_gold_tables(
    silver_path: Path,
    country_destination: Path,
    pair_destination: Path,
) -> tuple[int, int]:
    country_destination.parent.mkdir(parents=True, exist_ok=True)
    pair_destination.parent.mkdir(parents=True, exist_ok=True)
    silver_sql = _quote_path(silver_path)
    country_sql = _quote_path(country_destination)
    pair_sql = _quote_path(pair_destination)

    connection = duckdb.connect()
    connection.execute("SET TimeZone='UTC'")
    connection.execute("SET memory_limit='4GB'")
    connection.execute("SET threads=4")
    connection.execute(
        f"""
        COPY (
            SELECT
                event_date,
                action_country_code AS country_code,
                count(*)::BIGINT AS event_count,
                sum(CASE WHEN relation_class LIKE '%conflict' THEN 1 ELSE 0 END)::BIGINT
                    AS conflict_event_count,
                sum(coalesce(num_mentions, 0))::BIGINT AS mention_count,
                avg(avg_tone) AS avg_tone,
                avg(goldstein_scale) AS avg_goldstein_scale,
                any_value(batch_id) AS source_batch_id,
                'gold_country_day_state_v1' AS schema_version
            FROM read_parquet('{silver_sql}')
            WHERE action_country_code IS NOT NULL AND action_country_code <> ''
            GROUP BY event_date, action_country_code
            ORDER BY event_date, action_country_code
        ) TO '{country_sql}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """
    )
    connection.execute(
        f"""
        COPY (
            SELECT
                event_date,
                actor1_country_code,
                actor2_country_code,
                relation_class,
                count(*)::BIGINT AS event_count,
                sum(coalesce(num_mentions, 0))::BIGINT AS mention_count,
                avg(avg_tone) AS avg_tone,
                avg(goldstein_scale) AS avg_goldstein_scale,
                any_value(batch_id) AS source_batch_id,
                'gold_pair_day_relation_v1' AS schema_version
            FROM read_parquet('{silver_sql}')
            WHERE actor1_country_code IS NOT NULL
              AND actor2_country_code IS NOT NULL
              AND actor1_country_code <> ''
              AND actor2_country_code <> ''
            GROUP BY event_date, actor1_country_code, actor2_country_code, relation_class
            ORDER BY event_date, actor1_country_code, actor2_country_code, relation_class
        ) TO '{pair_sql}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """
    )
    country_rows = connection.execute(
        f"SELECT count(*) FROM read_parquet('{country_sql}')"
    ).fetchone()[0]
    pair_rows = connection.execute(f"SELECT count(*) FROM read_parquet('{pair_sql}')").fetchone()[0]
    connection.close()
    return int(country_rows), int(pair_rows)


def validate_pipeline_outputs(
    bronze_path: Path,
    silver_path: Path,
    country_path: Path,
    pair_path: Path,
) -> dict[str, object]:
    connection = duckdb.connect()
    connection.execute("SET TimeZone='UTC'")
    bronze_sql = _quote_path(bronze_path)
    silver_sql = _quote_path(silver_path)
    country_sql = _quote_path(country_path)
    pair_sql = _quote_path(pair_path)
    bronze_rows = connection.execute(
        f"SELECT count(*) FROM read_parquet('{bronze_sql}')"
    ).fetchone()[0]
    silver_quality = connection.execute(
        f"""
        SELECT
            count(*) AS rows,
            count(DISTINCT dedupe_key) AS distinct_dedupe_keys,
            sum(CASE WHEN event_date IS NULL THEN 1 ELSE 0 END) AS null_event_dates,
            min(event_date) AS min_event_date,
            max(event_date) AS max_event_date,
            cast(min(date_added) AS VARCHAR) AS min_date_added,
            cast(max(date_added) AS VARCHAR) AS max_date_added
        FROM read_parquet('{silver_sql}')
        """
    ).fetchone()
    country_rows = connection.execute(
        f"SELECT count(*) FROM read_parquet('{country_sql}')"
    ).fetchone()[0]
    pair_rows = connection.execute(f"SELECT count(*) FROM read_parquet('{pair_sql}')").fetchone()[0]
    connection.close()
    silver_rows = int(silver_quality[0])
    distinct_keys = int(silver_quality[1])
    return {
        "status": "PASS" if silver_rows == distinct_keys and silver_rows <= bronze_rows else "FAIL",
        "bronze_rows": int(bronze_rows),
        "silver_rows": silver_rows,
        "silver_distinct_dedupe_keys": distinct_keys,
        "silver_null_event_dates": int(silver_quality[2]),
        "silver_min_event_date": str(silver_quality[3]) if silver_quality[3] else None,
        "silver_max_event_date": str(silver_quality[4]) if silver_quality[4] else None,
        "silver_min_date_added": str(silver_quality[5]) if silver_quality[5] else None,
        "silver_max_date_added": str(silver_quality[6]) if silver_quality[6] else None,
        "gold_country_rows": int(country_rows),
        "gold_pair_rows": int(pair_rows),
    }


def run_minimal_pipeline(events_zip: Path, output_root: Path) -> dict[str, object]:
    inspection = inspect_zip(events_zip, "events")
    if not inspection.valid:
        raise ValueError(f"invalid events archive: {inspection.to_dict()}")
    batch_id = _batch_id(events_zip)
    control_path = output_root / "control" / "world_control.sqlite"
    bronze = output_root / "bronze" / "gdelt_events" / f"batch={batch_id}" / "part-000.parquet"
    silver = output_root / "silver" / "world_event" / f"batch={batch_id}" / "part-000.parquet"
    country = output_root / "gold" / "country_day_state" / f"batch={batch_id}" / "part-000.parquet"
    pair = output_root / "gold" / "pair_day_relation" / f"batch={batch_id}" / "part-000.parquet"

    connection = connect_control(control_path)
    source_id = register_source_file(
        connection,
        dataset_kind="events",
        batch_id=batch_id,
        source_url=f"local://{events_zip.name}",
        local_path=events_zip.resolve(),
        size_bytes=events_zip.stat().st_size,
        md5=file_md5(events_zip),
        sha256=sha256_file(events_zip),
        rows=inspection.rows,
        field_count=inspection.expected_fields,
    )
    bronze_rows = write_bronze_events(events_zip, bronze)
    register_artifact(
        connection,
        layer="bronze",
        dataset_name="gdelt_events",
        batch_id=batch_id,
        local_path=bronze.resolve(),
        rows=bronze_rows,
        source_file_id=source_id,
    )
    silver_rows = write_silver_world_event(bronze, silver, batch_id=batch_id)
    register_artifact(
        connection,
        layer="silver",
        dataset_name="world_event",
        batch_id=batch_id,
        local_path=silver.resolve(),
        rows=silver_rows,
        source_file_id=source_id,
    )
    country_rows, pair_rows = write_gold_tables(silver, country, pair)
    register_artifact(
        connection,
        layer="gold",
        dataset_name="country_day_state",
        batch_id=batch_id,
        local_path=country.resolve(),
        rows=country_rows,
        source_file_id=source_id,
    )
    register_artifact(
        connection,
        layer="gold",
        dataset_name="pair_day_relation",
        batch_id=batch_id,
        local_path=pair.resolve(),
        rows=pair_rows,
        source_file_id=source_id,
    )
    quality = validate_pipeline_outputs(bronze, silver, country, pair)
    if quality["status"] != "PASS":
        raise ValueError(f"pipeline output validation failed: {quality}")
    report = {
        "status": "PASS",
        "batch_id": batch_id,
        "source": inspection.to_dict(),
        "rows": {
            "bronze": bronze_rows,
            "silver": silver_rows,
            "gold_country_day_state": country_rows,
            "gold_pair_day_relation": pair_rows,
        },
        "quality": quality,
        "artifacts": {
            "control": str(control_path),
            "bronze": str(bronze),
            "silver": str(silver),
            "gold_country_day_state": str(country),
            "gold_pair_day_relation": str(pair),
        },
    }
    record_validation(connection, run_type="minimal_pipeline", status="PASS", details=report)
    connection.close()
    return report
