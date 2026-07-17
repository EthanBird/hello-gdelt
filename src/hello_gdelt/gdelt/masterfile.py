from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from hello_gdelt.gdelt.lastupdate import (
    GdeltArtifact,
    LastUpdateParseError,
    parse_artifact_line,
)

_DATASETS = ("events", "gkg", "mentions")


class MasterFileParseError(ValueError):
    """Raised when the historical GDELT master file list is internally inconsistent."""


@dataclass(frozen=True, slots=True)
class GdeltArtifactTrio:
    timestamp: str
    artifacts: tuple[GdeltArtifact, GdeltArtifact, GdeltArtifact]

    @property
    def total_size_bytes(self) -> int:
        return sum(artifact.size_bytes for artifact in self.artifacts)


@dataclass(frozen=True, slots=True)
class IncompleteTimestamp:
    timestamp: str
    present_datasets: tuple[str, ...]
    missing_datasets: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MasterFileIndex:
    trios: tuple[GdeltArtifactTrio, ...]
    incomplete: tuple[IncompleteTimestamp, ...]
    parsed_lines: int
    retained_artifacts: int

    @property
    def total_size_bytes(self) -> int:
        return sum(trio.total_size_bytes for trio in self.trios)


def parse_masterfile_lines(
    lines: Iterable[str],
    *,
    start_timestamp: str | None = None,
    end_timestamp: str | None = None,
    max_lines: int = 2_000_000,
) -> MasterFileIndex:
    """Parse an English GDELT master list and materialize complete aligned trios.

    Timestamp bounds are inclusive and use the native sortable YYYYMMDDhhmmss format.
    Incomplete timestamps are retained as explicit audit findings rather than silently filled.
    """

    if max_lines <= 0:
        raise ValueError("max_lines must be positive")
    for name, value in (("start_timestamp", start_timestamp), ("end_timestamp", end_timestamp)):
        if value is not None and (len(value) != 14 or not value.isdigit()):
            raise ValueError(f"{name} must be a 14-digit GDELT timestamp")
    if start_timestamp is not None and end_timestamp is not None:
        if start_timestamp > end_timestamp:
            raise ValueError("start_timestamp must be <= end_timestamp")

    grouped: dict[str, dict[str, GdeltArtifact]] = {}
    parsed_lines = 0
    retained_artifacts = 0
    for line_number, raw_line in enumerate(lines, start=1):
        if not raw_line.strip():
            continue
        parsed_lines += 1
        if parsed_lines > max_lines:
            raise MasterFileParseError(
                f"master file exceeded max_lines={max_lines:,}; aborting bounded parse"
            )
        try:
            artifact = parse_artifact_line(raw_line, line_number=line_number)
        except LastUpdateParseError as exc:
            raise MasterFileParseError(str(exc)) from exc
        if start_timestamp is not None and artifact.timestamp < start_timestamp:
            continue
        if end_timestamp is not None and artifact.timestamp > end_timestamp:
            continue
        retained_artifacts += 1
        by_dataset = grouped.setdefault(artifact.timestamp, {})
        existing = by_dataset.get(artifact.dataset)
        if existing is not None:
            raise MasterFileParseError(
                f"duplicate {artifact.dataset} artifact for timestamp {artifact.timestamp}: "
                f"{existing.url} and {artifact.url}"
            )
        by_dataset[artifact.dataset] = artifact

    trios: list[GdeltArtifactTrio] = []
    incomplete: list[IncompleteTimestamp] = []
    expected = set(_DATASETS)
    for timestamp in sorted(grouped):
        by_dataset = grouped[timestamp]
        present = set(by_dataset)
        missing = expected - present
        if missing:
            incomplete.append(
                IncompleteTimestamp(
                    timestamp=timestamp,
                    present_datasets=tuple(sorted(present)),
                    missing_datasets=tuple(sorted(missing)),
                )
            )
            continue
        artifacts = tuple(by_dataset[dataset] for dataset in _DATASETS)
        trios.append(GdeltArtifactTrio(timestamp=timestamp, artifacts=artifacts))

    return MasterFileIndex(
        trios=tuple(trios),
        incomplete=tuple(incomplete),
        parsed_lines=parsed_lines,
        retained_artifacts=retained_artifacts,
    )


def parse_masterfile(
    text: str,
    *,
    start_timestamp: str | None = None,
    end_timestamp: str | None = None,
    max_lines: int = 2_000_000,
) -> MasterFileIndex:
    return parse_masterfile_lines(
        text.splitlines(),
        start_timestamp=start_timestamp,
        end_timestamp=end_timestamp,
        max_lines=max_lines,
    )
