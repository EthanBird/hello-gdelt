from __future__ import annotations

from datetime import date
from pathlib import Path

import typer

from hello_gdelt.config import ResourceLimits
from hello_gdelt.validation.ecb_fx_sample import (
    run_ecb_fx_sample,
    write_ecb_fx_sample_report,
)
from hello_gdelt.validation.gdelt_sample import (
    run_gdelt_latest_sample,
    write_gdelt_sample_report,
)
from hello_gdelt.validation.preflight import run_local_preflight, write_report

app = typer.Typer(no_args_is_help=True, help="GDELT observed-world research CLI")


@app.command("preflight")
def preflight(
    root: Path = typer.Option(Path.cwd(), help="Repository/runtime root"),
    enforce_disk_gate: bool = typer.Option(
        True,
        help="Treat the 300GB free-space rule as a hard gate",
    ),
) -> None:
    """Run the local part of the M1 development gate."""

    report = run_local_preflight(root, enforce_disk_gate=enforce_disk_gate)
    json_path, markdown_path = write_report(report, root / "reports")
    typer.echo(report.to_markdown())
    typer.echo(f"JSON: {json_path}")
    typer.echo(f"Markdown: {markdown_path}")
    raise typer.Exit(code=0 if report.gate != "NO_GO" else 2)


@app.command("gdelt-sample")
def gdelt_sample(
    root: Path = typer.Option(Path.cwd(), help="Repository/runtime root"),
    sample_rows: int = typer.Option(10_000, min=1, max=1_000_000),
    max_download_mb: int = typer.Option(1_500, min=1, max=20_000),
    min_free_disk_gb: int = typer.Option(300, min=1),
    allow_insecure_http: bool = typer.Option(
        False,
        help="Explicitly allow the legacy unauthenticated HTTP GDELT raw endpoint",
    ),
) -> None:
    """Download and validate one real aligned GDELT trio through Gold and DuckDB."""

    limits = ResourceLimits(
        max_download_bytes=max_download_mb * 1_000_000,
        min_free_disk_bytes=min_free_disk_gb * 1_000_000_000,
    )
    report = run_gdelt_latest_sample(
        root,
        limits=limits,
        sample_rows=sample_rows,
        allow_insecure_http=allow_insecure_http,
    )
    json_path, markdown_path = write_gdelt_sample_report(report, root / "reports")
    typer.echo(report.to_markdown())
    typer.echo(f"JSON: {json_path}")
    typer.echo(f"Markdown: {markdown_path}")
    raise typer.Exit(code=0 if report.gate == "GO" else 2)


@app.command("ecb-fx-sample")
def ecb_fx_sample(
    root: Path = typer.Option(Path.cwd(), help="Repository/runtime root"),
    start_date: str | None = typer.Option(
        None,
        help="Inclusive ISO date; defaults to lookback-days before end-date",
    ),
    end_date: str | None = typer.Option(
        None,
        help="Inclusive ISO date; defaults to yesterday UTC",
    ),
    lookback_days: int = typer.Option(45, min=7, max=366),
) -> None:
    """Validate official ECB EXR data and derive the frozen 16-pair FX panel."""

    parsed_start = None if start_date is None else date.fromisoformat(start_date)
    parsed_end = None if end_date is None else date.fromisoformat(end_date)
    report = run_ecb_fx_sample(
        root,
        start_date=parsed_start,
        end_date=parsed_end,
        lookback_days=lookback_days,
    )
    json_path, markdown_path = write_ecb_fx_sample_report(report, root / "reports")
    typer.echo(report.to_markdown())
    typer.echo(f"JSON: {json_path}")
    typer.echo(f"Markdown: {markdown_path}")
    raise typer.Exit(code=0 if report.gate == "GO" else 2)
