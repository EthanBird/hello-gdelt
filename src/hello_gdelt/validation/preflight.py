from __future__ import annotations

import importlib.util
import json
import os
import platform
import shutil
import sqlite3
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from hello_gdelt.config import Paths, ResourceLimits

Status = Literal["PASS", "WARN", "FAIL", "BLOCKED"]


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    status: Status
    detail: str


@dataclass(frozen=True, slots=True)
class PreflightReport:
    generated_at_utc: str
    python: str
    platform: str
    checks: tuple[CheckResult, ...]
    gate: Literal["GO", "CONDITIONAL_GO", "NO_GO"]

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    def to_markdown(self) -> str:
        rows = [
            "# M1 开发前验证报告",
            "",
            f"生成时间（UTC）：`{self.generated_at_utc}`",
            f"门禁结论：**{self.gate}**",
            "",
            "| 检查项 | 状态 | 说明 |",
            "|---|---|---|",
        ]
        for check in self.checks:
            detail = check.detail.replace("|", "\\|").replace("\n", " ")
            rows.append(f"| `{check.name}` | **{check.status}** | {detail} |")
        rows.extend(
            [
                "",
                "> 该报告只证明当前机器与依赖的可用性，不代表 GDELT 数据质量、金融特征或假设已经验证。",
            ]
        )
        return "\n".join(rows) + "\n"


def _dependency_check(name: str, *, required: bool) -> CheckResult:
    available = importlib.util.find_spec(name) is not None
    if available:
        return CheckResult(f"dependency:{name}", "PASS", "available")
    return CheckResult(
        f"dependency:{name}",
        "FAIL" if required else "BLOCKED",
        "not installed",
    )


def _disk_check(path: Path, minimum_free: int) -> CheckResult:
    usage = shutil.disk_usage(path)
    detail = f"free={usage.free:,} bytes; required={minimum_free:,} bytes"
    return CheckResult("disk_free", "PASS" if usage.free >= minimum_free else "FAIL", detail)


def _sqlite_check(temp_dir: Path) -> tuple[CheckResult, CheckResult]:
    db_path = temp_dir / "preflight.sqlite3"
    if db_path.exists():
        db_path.unlink()
    connection = sqlite3.connect(db_path)
    try:
        journal_mode = str(connection.execute("PRAGMA journal_mode=WAL").fetchone()[0]).lower()
        wal = CheckResult(
            "sqlite_wal",
            "PASS" if journal_mode == "wal" else "FAIL",
            f"journal_mode={journal_mode}",
        )
        try:
            connection.execute("CREATE VIRTUAL TABLE evidence_fts USING fts5(title, body)")
            connection.execute(
                "INSERT INTO evidence_fts(title, body) VALUES (?, ?)",
                ("gold", "central bank reserve narrative"),
            )
            match_count = connection.execute(
                "SELECT count(*) FROM evidence_fts WHERE evidence_fts MATCH 'reserve'"
            ).fetchone()[0]
            fts = CheckResult(
                "sqlite_fts5",
                "PASS" if match_count == 1 else "FAIL",
                f"matches={match_count}",
            )
        except sqlite3.OperationalError as exc:
            fts = CheckResult("sqlite_fts5", "FAIL", str(exc))
    finally:
        connection.close()
        for candidate in temp_dir.glob("preflight.sqlite3*"):
            candidate.unlink(missing_ok=True)
    return wal, fts


def run_local_preflight(
    root: Path,
    *,
    limits: ResourceLimits | None = None,
    enforce_disk_gate: bool = True,
) -> PreflightReport:
    limits = limits or ResourceLimits()
    paths = Paths.from_root(root)
    paths.ensure_runtime_dirs()

    checks: list[CheckResult] = []
    version_ok = (3, 11) <= sys.version_info[:2] < (3, 13)
    checks.append(
        CheckResult(
            "python_version",
            "PASS" if version_ok else "FAIL",
            platform.python_version(),
        )
    )
    checks.append(
        CheckResult(
            "architecture",
            "PASS" if platform.architecture()[0] == "64bit" else "FAIL",
            f"machine={platform.machine()}; bits={platform.architecture()[0]}",
        )
    )
    checks.append(_disk_check(paths.root, limits.min_free_disk_bytes))
    checks.extend(
        [
            _dependency_check("httpx", required=True),
            _dependency_check("pydantic", required=True),
            _dependency_check("yaml", required=True),
            _dependency_check("duckdb", required=True),
            _dependency_check("polars", required=True),
            _dependency_check("pyarrow", required=True),
            _dependency_check("statsmodels", required=False),
        ]
    )
    checks.extend(_sqlite_check(paths.temp))
    writable = os.access(paths.data, os.W_OK) and os.access(paths.reports, os.W_OK)
    checks.append(
        CheckResult(
            "runtime_paths_writable",
            "PASS" if writable else "FAIL",
            f"data={paths.data}; reports={paths.reports}",
        )
    )

    gate_checks = checks if enforce_disk_gate else [c for c in checks if c.name != "disk_free"]
    statuses = {check.status for check in gate_checks}
    if "FAIL" in statuses:
        gate: Literal["GO", "CONDITIONAL_GO", "NO_GO"] = "NO_GO"
    elif "BLOCKED" in statuses or "WARN" in statuses:
        gate = "CONDITIONAL_GO"
    else:
        gate = "GO"

    return PreflightReport(
        generated_at_utc=datetime.now(UTC).isoformat(),
        python=platform.python_version(),
        platform=platform.platform(),
        checks=tuple(checks),
        gate=gate,
    )


def write_report(report: PreflightReport, reports_dir: Path) -> tuple[Path, Path]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    json_path = reports_dir / "m1_preflight_report.json"
    markdown_path = reports_dir / "m1_preflight_report.md"
    json_path.write_text(report.to_json() + "\n", encoding="utf-8")
    markdown_path.write_text(report.to_markdown(), encoding="utf-8")
    return json_path, markdown_path
