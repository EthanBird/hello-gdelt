from __future__ import annotations

from pathlib import Path

from gdelt_world.preflight import run_preflight


def test_preflight_passes_with_development_threshold(tmp_path: Path) -> None:
    report = run_preflight(tmp_path, min_free_gb=0)

    assert report["status"] == "PASS"
    checks = {item["name"]: item["status"] for item in report["checks"]}
    assert checks["sqlite_wal"] == "PASS"
    assert checks["sqlite_fts5"] == "PASS"
    assert checks["package_duckdb"] == "PASS"
