from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import httpx

from hello_gdelt.config import Paths
from hello_gdelt.gdelt.history import (
    fetch_historical_manifest,
    index_historical_range,
    plan_backfill,
)

Gate = Literal["GO", "NO_GO"]


@dataclass(frozen=True, slots=True)
class GdeltHistoryPlanReport:
    generated_at_utc: str
    gate: Gate
    start_timestamp: str
    end_timestamp: str
    manifest_url: str | None
    transport_security: str | None
    manifest_size_bytes: int
    manifest_sha256: str | None
    parsed_lines: int
    retained_artifacts: int
    available_trios: int
    selected_trios: int
    incomplete_timestamps: tuple[str, ...]
    available_compressed_bytes: int
    selected_compressed_bytes: int
    stopped_by_byte_budget: bool
    stopped_by_trio_limit: bool
    selected_first_timestamp: str | None
    selected_last_timestamp: str | None
    failure: str | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    def to_markdown(self) -> str:
        lines = [
            "# GDELT 历史回填计划验证",
            "",
            f"生成时间（UTC）：`{self.generated_at_utc}`",
            f"目标范围：`{self.start_timestamp}` 至 `{self.end_timestamp}`",
            f"门禁：**{self.gate}**",
            f"传输：**{self.transport_security or 'UNKNOWN'}**",
            f"清单：`{self.manifest_url or 'UNKNOWN'}`",
            f"清单 SHA-256：`{self.manifest_sha256 or 'UNKNOWN'}`",
            "",
            "| 指标 | 数值 |",
            "|---|---:|",
            f"| 清单字节 | {self.manifest_size_bytes} |",
            f"| 解析非空行 | {self.parsed_lines} |",
            f"| 范围内文件 | {self.retained_artifacts} |",
            f"| 完整三表时间戳 | {self.available_trios} |",
            f"| 计划下载三表时间戳 | {self.selected_trios} |",
            f"| 可用压缩字节 | {self.available_compressed_bytes} |",
            f"| 计划压缩字节 | {self.selected_compressed_bytes} |",
            f"| 不完整时间戳 | {len(self.incomplete_timestamps)} |",
        ]
        if self.incomplete_timestamps:
            lines.extend(
                ["", "## 不完整时间戳", "", *[f"- `{item}`" for item in self.incomplete_timestamps]]
            )
        if self.failure:
            lines.extend(["", "## 失败", "", f"`{self.failure}`"])
        lines.extend(
            [
                "",
                "> 该报告只生成可审计下载计划，不下载历史 ZIP；下载执行仍需逐文件完整性、磁盘和断点恢复门禁。",
            ]
        )
        return "\n".join(lines) + "\n"


def run_gdelt_history_plan(
    root: Path,
    *,
    start_timestamp: str,
    end_timestamp: str,
    max_compressed_bytes: int = 20_000_000_000,
    max_trios: int = 96,
    allow_insecure_http: bool = False,
    refresh_manifest: bool = True,
) -> GdeltHistoryPlanReport:
    generated_at = datetime.now(UTC).isoformat()
    paths = Paths.from_root(root)
    paths.ensure_runtime_dirs()
    manifest_url: str | None = None
    transport_security: str | None = None
    manifest_size = 0
    manifest_sha256: str | None = None
    try:
        destination = paths.data / "control" / "gdelt" / "masterfilelist.txt"
        with httpx.Client(headers={"User-Agent": "hello-gdelt/0.1 history-planner"}) as client:
            receipt = fetch_historical_manifest(
                client,
                destination,
                allow_insecure_http=allow_insecure_http,
                refresh=refresh_manifest,
            )
        manifest_url = receipt.source_url
        transport_security = receipt.transport_security
        manifest_size = receipt.size_bytes
        manifest_sha256 = receipt.sha256
        index = index_historical_range(
            Path(receipt.path),
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
        )
        plan = plan_backfill(
            index,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
            max_compressed_bytes=max_compressed_bytes,
            max_trios=max_trios,
        )
        if plan.available_trios == 0:
            raise RuntimeError("requested historical range contains no complete GDELT trios")
        if not plan.selected_trios:
            raise RuntimeError("download budget selected no complete GDELT trio")
        return GdeltHistoryPlanReport(
            generated_at_utc=generated_at,
            gate="GO",
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
            manifest_url=manifest_url,
            transport_security=transport_security,
            manifest_size_bytes=manifest_size,
            manifest_sha256=manifest_sha256,
            parsed_lines=index.parsed_lines,
            retained_artifacts=index.retained_artifacts,
            available_trios=plan.available_trios,
            selected_trios=len(plan.selected_trios),
            incomplete_timestamps=plan.incomplete_timestamps,
            available_compressed_bytes=plan.available_compressed_bytes,
            selected_compressed_bytes=plan.selected_compressed_bytes,
            stopped_by_byte_budget=plan.stopped_by_byte_budget,
            stopped_by_trio_limit=plan.stopped_by_trio_limit,
            selected_first_timestamp=plan.selected_trios[0].timestamp,
            selected_last_timestamp=plan.selected_trios[-1].timestamp,
        )
    except Exception as exc:
        return GdeltHistoryPlanReport(
            generated_at_utc=generated_at,
            gate="NO_GO",
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
            manifest_url=manifest_url,
            transport_security=transport_security,
            manifest_size_bytes=manifest_size,
            manifest_sha256=manifest_sha256,
            parsed_lines=0,
            retained_artifacts=0,
            available_trios=0,
            selected_trios=0,
            incomplete_timestamps=(),
            available_compressed_bytes=0,
            selected_compressed_bytes=0,
            stopped_by_byte_budget=False,
            stopped_by_trio_limit=False,
            selected_first_timestamp=None,
            selected_last_timestamp=None,
            failure=f"{type(exc).__name__}: {exc}",
        )


def write_gdelt_history_plan_report(
    report: GdeltHistoryPlanReport,
    reports_dir: Path,
) -> tuple[Path, Path]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    json_path = reports_dir / "gdelt_history_plan_report.json"
    markdown_path = reports_dir / "gdelt_history_plan_report.md"
    json_path.write_text(report.to_json() + "\n", encoding="utf-8")
    markdown_path.write_text(report.to_markdown(), encoding="utf-8")
    return json_path, markdown_path
