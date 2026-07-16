from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from gdelt_world.api import create_app
from gdelt_world.pipeline import run_minimal_pipeline
from gdelt_world.preflight import run_preflight, write_report
from gdelt_world.schemas import SCHEMAS, inspect_zip
from gdelt_world.source import (
    GDELT_HTTP_ROOT,
    download_entry,
    fetch_lastupdate,
    fetch_masterfile_tail,
    group_complete_batches,
)


def _write_json(data: dict[str, object], output: Path | None) -> None:
    rendered = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


def command_preflight(args: argparse.Namespace) -> int:
    report = run_preflight(args.data_root, min_free_gb=args.min_free_gb)
    if args.output:
        write_report(report, args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 2


def command_inspect(args: argparse.Namespace) -> int:
    inspection = inspect_zip(args.archive, args.kind)
    _write_json(inspection.to_dict(), args.output)
    return 0 if inspection.valid else 2


def command_probe(args: argparse.Namespace) -> int:
    started = datetime.now(UTC).isoformat()
    manifest = fetch_lastupdate(
        timeout=args.timeout,
        allow_http_fallback=args.allow_http_fallback,
    )
    failures: list[dict[str, str]] = []
    downloads = []
    selected_batch = manifest.entries[0].batch_id
    for entry in manifest.entries:
        try:
            downloads.append(
                download_entry(
                    entry,
                    args.download_dir,
                    timeout=args.download_timeout,
                    retries=args.retries,
                )
            )
        except RuntimeError as exc:
            failures.append({"batch_id": entry.batch_id, "kind": entry.kind, "error": str(exc)})

    used_complete_batch_fallback = False
    if failures:
        master_root = (
            GDELT_HTTP_ROOT if args.allow_http_fallback else manifest.source_url.rsplit("/", 1)[0]
        )
        master_entries = fetch_masterfile_tail(
            root=master_root,
            tail_bytes=args.master_tail_bytes,
            timeout=args.timeout,
        )
        latest_batch = max(entry.batch_id for entry in manifest.entries)
        for batch_id, entries in group_complete_batches(master_entries):
            if batch_id >= latest_batch:
                continue
            candidate = []
            try:
                for entry in entries:
                    candidate.append(
                        download_entry(
                            entry,
                            args.download_dir,
                            timeout=args.download_timeout,
                            retries=args.retries,
                        )
                    )
            except RuntimeError as exc:
                failures.append({"batch_id": batch_id, "kind": "complete_batch", "error": str(exc)})
                continue
            downloads = candidate
            selected_batch = batch_id
            used_complete_batch_fallback = True
            break

    complete = {item.entry.kind for item in downloads} == set(SCHEMAS)
    report = {
        "status": "PASS" if complete else "FAIL",
        "started_at": started,
        "finished_at": datetime.now(UTC).isoformat(),
        "manifest": manifest.to_dict(),
        "selected_batch": selected_batch,
        "used_complete_batch_fallback": used_complete_batch_fallback,
        "downloads": [item.to_dict() for item in downloads],
        "failures": failures,
        "security_warnings": (
            [
                "HTTP fallback was used; file size and MD5 were verified, "
                "but transport was not encrypted."
            ]
            if manifest.insecure_transport
            else []
        ),
    }
    _write_json(report, args.output)
    return 0 if complete else 2


def command_pipeline(args: argparse.Namespace) -> int:
    report = run_minimal_pipeline(args.events_zip, args.output_root)
    _write_json(report, args.output)
    return 0


def command_serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run(create_app(args.data_root), host=args.host, port=args.port)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hello-gdelt")
    subparsers = parser.add_subparsers(dest="command", required=True)

    preflight = subparsers.add_parser("preflight", help="check local runtime prerequisites")
    preflight.add_argument("--data-root", type=Path, default=Path("data"))
    preflight.add_argument("--min-free-gb", type=float, default=500)
    preflight.add_argument("--output", type=Path)
    preflight.set_defaults(handler=command_preflight)

    inspect = subparsers.add_parser("inspect", help="validate a GDELT ZIP and field contract")
    inspect.add_argument("kind", choices=sorted(SCHEMAS))
    inspect.add_argument("archive", type=Path)
    inspect.add_argument("--output", type=Path)
    inspect.set_defaults(handler=command_inspect)

    probe = subparsers.add_parser("probe", help="fetch and validate a complete real GDELT batch")
    probe.add_argument("--download-dir", type=Path, default=Path("data/tmp/downloads"))
    probe.add_argument("--output", type=Path)
    probe.add_argument("--timeout", type=float, default=30)
    probe.add_argument("--download-timeout", type=float, default=180)
    probe.add_argument("--retries", type=int, default=2)
    probe.add_argument("--master-tail-bytes", type=int, default=300_000)
    probe.add_argument("--allow-http-fallback", action="store_true")
    probe.set_defaults(handler=command_probe)

    pipeline = subparsers.add_parser("pipeline", help="build minimal Bronze/Silver/Gold data")
    pipeline.add_argument("events_zip", type=Path)
    pipeline.add_argument("--output-root", type=Path, default=Path("data"))
    pipeline.add_argument("--output", type=Path)
    pipeline.set_defaults(handler=command_pipeline)

    serve = subparsers.add_parser("serve", help="run the local-only API")
    serve.add_argument("--data-root", type=Path, default=Path("data"))
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.set_defaults(handler=command_serve)
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        exit_code = args.handler(args)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        exit_code = 1
    raise SystemExit(exit_code)
