from pathlib import Path

from hello_gdelt.config import ResourceLimits
from hello_gdelt.validation.preflight import run_local_preflight, write_report


def test_preflight_records_missing_heavy_dependencies(tmp_path: Path) -> None:
    limits = ResourceLimits(min_free_disk_bytes=1)
    report = run_local_preflight(tmp_path, limits=limits)
    names = {check.name for check in report.checks}
    assert "sqlite_wal" in names
    assert "sqlite_fts5" in names
    assert "dependency:duckdb" in names
    assert report.gate in {"GO", "CONDITIONAL_GO", "NO_GO"}


def test_write_report_is_deterministic_shape(tmp_path: Path) -> None:
    report = run_local_preflight(
        tmp_path,
        limits=ResourceLimits(min_free_disk_bytes=1),
        enforce_disk_gate=False,
    )
    json_path, markdown_path = write_report(report, tmp_path / "reports")
    assert '"gate"' in json_path.read_text(encoding="utf-8")
    assert "门禁结论" in markdown_path.read_text(encoding="utf-8")
