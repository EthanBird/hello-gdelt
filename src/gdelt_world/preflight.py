from __future__ import annotations

import importlib.metadata
import json
import os
import platform
import shutil
import sqlite3
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

CORE_PACKAGES = ("duckdb", "polars", "pyarrow", "fastapi", "pydantic")


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str


def _memory_bytes() -> int | None:
    path = Path("/proc/meminfo")
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("MemTotal:"):
            return int(line.split()[1]) * 1024
    return None


def _sqlite_checks(directory: Path) -> list[Check]:
    checks: list[Check] = []
    with tempfile.NamedTemporaryFile(dir=directory, suffix=".sqlite", delete=False) as temp:
        database = Path(temp.name)
    try:
        connection = sqlite3.connect(database)
        journal_mode = connection.execute("PRAGMA journal_mode=WAL").fetchone()[0]
        checks.append(
            Check(
                "sqlite_wal",
                "PASS" if str(journal_mode).lower() == "wal" else "FAIL",
                str(journal_mode),
            )
        )
        try:
            connection.execute("CREATE VIRTUAL TABLE evidence_fts USING fts5(title, body)")
            connection.execute(
                "INSERT INTO evidence_fts(title, body) VALUES (?, ?)",
                ("probe", "computable world"),
            )
            found = connection.execute(
                "SELECT count(*) FROM evidence_fts WHERE evidence_fts MATCH 'computable'"
            ).fetchone()[0]
            checks.append(Check("sqlite_fts5", "PASS" if found == 1 else "FAIL", f"rows={found}"))
        except sqlite3.OperationalError as exc:
            checks.append(Check("sqlite_fts5", "FAIL", str(exc)))
        connection.close()
    finally:
        database.unlink(missing_ok=True)
        database.with_name(database.name + "-wal").unlink(missing_ok=True)
        database.with_name(database.name + "-shm").unlink(missing_ok=True)
    return checks


def run_preflight(data_root: Path, *, min_free_gb: float = 500) -> dict[str, object]:
    data_root.mkdir(parents=True, exist_ok=True)
    checks: list[Check] = []

    supported_python = (3, 11) <= sys.version_info[:2] < (3, 13)
    checks.append(
        Check(
            "python_version",
            "PASS" if supported_python else "FAIL",
            platform.python_version(),
        )
    )

    for package in CORE_PACKAGES:
        try:
            version = importlib.metadata.version(package)
            checks.append(Check(f"package_{package}", "PASS", version))
        except importlib.metadata.PackageNotFoundError:
            checks.append(Check(f"package_{package}", "FAIL", "not installed"))

    disk = shutil.disk_usage(data_root)
    free_gb = disk.free / 1024**3
    disk_status = "PASS" if free_gb >= min_free_gb else "FAIL"
    checks.append(Check("disk_free", disk_status, f"{free_gb:.2f} GiB; required={min_free_gb:.2f}"))
    checks.extend(_sqlite_checks(data_root))

    failed = [check.name for check in checks if check.status == "FAIL"]
    return {
        "status": "PASS" if not failed else "FAIL",
        "checks": [asdict(check) for check in checks],
        "failed_checks": failed,
        "environment": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "cpu_count": os.cpu_count(),
            "memory_bytes": _memory_bytes(),
            "disk_total_bytes": disk.total,
            "disk_free_bytes": disk.free,
            "python": platform.python_version(),
        },
    }


def write_report(report: dict[str, object], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
