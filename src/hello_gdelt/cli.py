from __future__ import annotations

from pathlib import Path

import typer

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
