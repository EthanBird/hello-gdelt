from pathlib import Path

from hello_gdelt.validation.gdelt_sample import GdeltSampleReport, write_gdelt_sample_report


def test_failed_sample_report_is_persisted(tmp_path: Path) -> None:
    report = GdeltSampleReport(
        generated_at_utc="2026-07-17T00:00:00+00:00",
        gate="NO_GO",
        source_timestamp="UNKNOWN",
        datasets=(),
        failure="ConnectError: offline",
    )
    json_path, markdown_path = write_gdelt_sample_report(report, tmp_path)
    assert '"gate": "NO_GO"' in json_path.read_text(encoding="utf-8")
    assert "ConnectError: offline" in markdown_path.read_text(encoding="utf-8")
