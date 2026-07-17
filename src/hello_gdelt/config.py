from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ResourceLimits:
    """Hard limits used by preflight and ingestion commands."""

    max_download_bytes: int = 1_500_000_000
    min_free_disk_bytes: int = 300_000_000_000
    request_timeout_seconds: float = 90.0
    max_retries: int = 4


@dataclass(frozen=True, slots=True)
class Paths:
    root: Path
    data: Path
    reports: Path
    temp: Path

    @classmethod
    def from_root(cls, root: Path) -> "Paths":
        resolved = root.expanduser().resolve()
        return cls(
            root=resolved,
            data=resolved / "data",
            reports=resolved / "reports",
            temp=resolved / "tmp",
        )

    def ensure_runtime_dirs(self) -> None:
        for path in (self.data, self.reports, self.temp):
            path.mkdir(parents=True, exist_ok=True)
