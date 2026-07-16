from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import duckdb
import httpx

from gdelt_world.api import create_app
from gdelt_world.pipeline import run_minimal_pipeline


async def get_health(output_root: Path) -> httpx.Response:
    transport = httpx.ASGITransport(app=create_app(output_root))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/health")


def test_minimal_pipeline_is_repeatable(events_zip: Path, tmp_path: Path) -> None:
    output_root = tmp_path / "data"

    first = run_minimal_pipeline(events_zip, output_root)
    second = run_minimal_pipeline(events_zip, output_root)

    assert first["status"] == "PASS"
    assert first["rows"] == second["rows"]
    assert first["rows"]["bronze"] == 1
    assert first["rows"]["silver"] == 1
    assert first["rows"]["gold_country_day_state"] == 1
    assert first["rows"]["gold_pair_day_relation"] == 1
    assert first["quality"]["silver_min_date_added"].endswith("+00")

    pair_path = Path(first["artifacts"]["gold_pair_day_relation"])
    row = (
        duckdb.connect()
        .execute(
            "SELECT actor1_country_code, actor2_country_code, relation_class FROM read_parquet(?)",
            [str(pair_path)],
        )
        .fetchone()
    )
    assert row == ("USA", "IRN", "material_conflict")

    control = sqlite3.connect(first["artifacts"]["control"])
    assert control.execute("SELECT count(*) FROM source_file").fetchone()[0] == 1
    assert control.execute("SELECT count(*) FROM dataset_artifact").fetchone()[0] == 4
    assert control.execute("SELECT count(*) FROM validation_run").fetchone()[0] == 2
    control.close()

    health = asyncio.run(get_health(output_root))
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["control_schema_version"] == "2"
