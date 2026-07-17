from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

import httpx

from hello_gdelt.config import Paths, ResourceLimits
from hello_gdelt.control.manifest import ManifestStore
from hello_gdelt.gdelt.history import BackfillPlan
from hello_gdelt.gdelt.pipeline import ProcessedGdeltTrio, process_gdelt_trio


class BackfillExecutionError(RuntimeError):
    """Raised when a bounded GDELT backfill cannot safely continue."""


@dataclass(frozen=True, slots=True)
class BackfillFailure:
    source_timestamp: str
    error_type: str
    message: str


@dataclass(frozen=True, slots=True)
class BackfillExecutionResult:
    requested_start_timestamp: str
    requested_end_timestamp: str
    selected_trios: int
    completed_trios: tuple[ProcessedGdeltTrio, ...]
    failures: tuple[BackfillFailure, ...]
    selected_compressed_bytes: int
    stopped_early: bool

    @property
    def completed_count(self) -> int:
        return len(self.completed_trios)



def execute_backfill_plan(
    client: httpx.Client,
    plan: BackfillPlan,
    root: Path,
    *,
    limits: ResourceLimits,
    sample_rows: int = 10_000,
    allow_insecure_http: bool = False,
    continue_on_error: bool = False,
) -> BackfillExecutionResult:
    """Execute a pre-budgeted chronological plan with restartable artifact states."""

    if not plan.selected_trios:
        raise BackfillExecutionError("backfill plan selected no complete trios")
    if plan.selected_compressed_bytes > plan.available_compressed_bytes:
        raise BackfillExecutionError("selected bytes exceed available range bytes")
    paths = Paths.from_root(root)
    paths.ensure_runtime_dirs()
    store_path = paths.data / "control" / "hello_gdelt.sqlite3"
    completed: list[ProcessedGdeltTrio] = []
    failures: list[BackfillFailure] = []
    stopped_early = False
    with ManifestStore(store_path) as store:
        for trio in plan.selected_trios:
            free_bytes = shutil.disk_usage(paths.root).free
            if free_bytes < limits.min_free_disk_bytes:
                error = BackfillExecutionError(
                    f"free disk below gate before {trio.timestamp}: "
                    f"free={free_bytes}, required={limits.min_free_disk_bytes}"
                )
                failures.append(
                    BackfillFailure(
                        source_timestamp=trio.timestamp,
                        error_type=type(error).__name__,
                        message=str(error),
                    )
                )
                stopped_early = True
                break
            try:
                processed = process_gdelt_trio(
                    client,
                    trio,
                    paths,
                    store,
                    limits=limits,
                    sample_rows=sample_rows,
                    allow_insecure_http=allow_insecure_http,
                )
                completed.append(processed)
            except Exception as exc:
                failures.append(
                    BackfillFailure(
                        source_timestamp=trio.timestamp,
                        error_type=type(exc).__name__,
                        message=str(exc),
                    )
                )
                if not continue_on_error:
                    stopped_early = True
                    break
    if failures and not completed:
        first = failures[0]
        raise BackfillExecutionError(
            f"no trio completed; first failure {first.source_timestamp}: "
            f"{first.error_type}: {first.message}"
        )
    return BackfillExecutionResult(
        requested_start_timestamp=plan.start_timestamp,
        requested_end_timestamp=plan.end_timestamp,
        selected_trios=len(plan.selected_trios),
        completed_trios=tuple(completed),
        failures=tuple(failures),
        selected_compressed_bytes=plan.selected_compressed_bytes,
        stopped_early=stopped_early,
    )
