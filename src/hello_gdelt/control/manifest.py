from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from hello_gdelt.gdelt.lastupdate import GdeltArtifact

ArtifactStatus = Literal[
    "DISCOVERED",
    "DOWNLOADING",
    "VERIFIED",
    "EXTRACTED",
    "BRONZE_READY",
    "FAILED",
]


class ManifestConflictError(RuntimeError):
    """Raised when a source identity changes under an existing manifest key."""


class InvalidStatusTransitionError(RuntimeError):
    """Raised when an ingestion artifact skips or reverses required states."""


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    source_url: str
    dataset: str
    source_timestamp: str
    expected_size_bytes: int
    expected_md5: str
    status: ArtifactStatus
    local_archive_path: str | None
    local_extracted_path: str | None
    bronze_path: str | None
    actual_sha256: str | None
    attempt_count: int
    last_error: str | None
    discovered_at_utc: str
    updated_at_utc: str


_ALLOWED_TRANSITIONS: dict[ArtifactStatus, frozenset[ArtifactStatus]] = {
    "DISCOVERED": frozenset({"DOWNLOADING", "FAILED"}),
    "DOWNLOADING": frozenset({"VERIFIED", "FAILED"}),
    "VERIFIED": frozenset({"EXTRACTED", "FAILED"}),
    "EXTRACTED": frozenset({"BRONZE_READY", "FAILED"}),
    "BRONZE_READY": frozenset(),
    "FAILED": frozenset({"DOWNLOADING"}),
}


class ManifestStore:
    """Small transactional registry for deterministic and restartable ingestion."""

    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.execute("PRAGMA busy_timeout=5000")
        self._migrate()

    def __enter__(self) -> ManifestStore:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def close(self) -> None:
        self._connection.close()

    def _migrate(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_migration (
                version INTEGER PRIMARY KEY,
                applied_at_utc TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS gdelt_artifact_manifest (
                source_url TEXT PRIMARY KEY,
                dataset TEXT NOT NULL CHECK(dataset IN ('events', 'mentions', 'gkg')),
                source_timestamp TEXT NOT NULL CHECK(length(source_timestamp) = 14),
                expected_size_bytes INTEGER NOT NULL CHECK(expected_size_bytes > 0),
                expected_md5 TEXT NOT NULL CHECK(length(expected_md5) = 32),
                status TEXT NOT NULL CHECK(status IN (
                    'DISCOVERED', 'DOWNLOADING', 'VERIFIED',
                    'EXTRACTED', 'BRONZE_READY', 'FAILED'
                )),
                local_archive_path TEXT,
                local_extracted_path TEXT,
                bronze_path TEXT,
                actual_sha256 TEXT CHECK(actual_sha256 IS NULL OR length(actual_sha256) = 64),
                attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count >= 0),
                last_error TEXT,
                discovered_at_utc TEXT NOT NULL,
                updated_at_utc TEXT NOT NULL,
                UNIQUE(dataset, source_timestamp)
            );

            CREATE INDEX IF NOT EXISTS idx_gdelt_manifest_status_time
            ON gdelt_artifact_manifest(status, source_timestamp);
            """
        )
        now = datetime.now(UTC).isoformat()
        self._connection.execute(
            "INSERT OR IGNORE INTO schema_migration(version, applied_at_utc) VALUES (1, ?)",
            (now,),
        )
        self._connection.commit()

    def register(self, artifacts: Iterable[GdeltArtifact]) -> tuple[ArtifactRecord, ...]:
        materialized = tuple(artifacts)
        if not materialized:
            raise ValueError("at least one artifact is required")
        now = datetime.now(UTC).isoformat()
        records: list[ArtifactRecord] = []
        with self._connection:
            for artifact in materialized:
                existing = self._connection.execute(
                    "SELECT * FROM gdelt_artifact_manifest WHERE source_url = ?",
                    (artifact.url,),
                ).fetchone()
                if existing is not None:
                    immutable = (
                        existing["dataset"],
                        existing["source_timestamp"],
                        existing["expected_size_bytes"],
                        existing["expected_md5"],
                    )
                    incoming = (
                        artifact.dataset,
                        artifact.timestamp,
                        artifact.size_bytes,
                        artifact.md5,
                    )
                    if immutable != incoming:
                        raise ManifestConflictError(
                            f"source identity drift for {artifact.url}: "
                            f"stored={immutable!r}, incoming={incoming!r}"
                        )
                else:
                    self._connection.execute(
                        """
                        INSERT INTO gdelt_artifact_manifest(
                            source_url, dataset, source_timestamp,
                            expected_size_bytes, expected_md5, status,
                            discovered_at_utc, updated_at_utc
                        ) VALUES (?, ?, ?, ?, ?, 'DISCOVERED', ?, ?)
                        """,
                        (
                            artifact.url,
                            artifact.dataset,
                            artifact.timestamp,
                            artifact.size_bytes,
                            artifact.md5,
                            now,
                            now,
                        ),
                    )
                record = self.get(artifact.url)
                if record is None:
                    raise RuntimeError(f"manifest row disappeared after registration: {artifact.url}")
                records.append(record)
        return tuple(records)

    def get(self, source_url: str) -> ArtifactRecord | None:
        row = self._connection.execute(
            "SELECT * FROM gdelt_artifact_manifest WHERE source_url = ?",
            (source_url,),
        ).fetchone()
        return None if row is None else self._to_record(row)

    def list_by_status(
        self,
        *statuses: ArtifactStatus,
        limit: int = 1000,
    ) -> tuple[ArtifactRecord, ...]:
        if not statuses:
            raise ValueError("at least one status is required")
        if limit <= 0:
            raise ValueError("limit must be positive")
        placeholders = ",".join("?" for _ in statuses)
        rows = self._connection.execute(
            f"""
            SELECT * FROM gdelt_artifact_manifest
            WHERE status IN ({placeholders})
            ORDER BY source_timestamp, dataset
            LIMIT ?
            """,
            (*statuses, limit),
        ).fetchall()
        return tuple(self._to_record(row) for row in rows)

    def transition(
        self,
        source_url: str,
        status: ArtifactStatus,
        *,
        local_archive_path: Path | None = None,
        local_extracted_path: Path | None = None,
        bronze_path: Path | None = None,
        actual_sha256: str | None = None,
        error: str | None = None,
    ) -> ArtifactRecord:
        current = self.get(source_url)
        if current is None:
            raise KeyError(source_url)
        if status not in _ALLOWED_TRANSITIONS[current.status]:
            raise InvalidStatusTransitionError(
                f"invalid artifact transition {current.status} -> {status} for {source_url}"
            )
        if status == "VERIFIED":
            if local_archive_path is None or actual_sha256 is None:
                raise ValueError("VERIFIED requires local_archive_path and actual_sha256")
            if len(actual_sha256) != 64:
                raise ValueError("actual_sha256 must contain 64 hexadecimal characters")
            try:
                int(actual_sha256, 16)
            except ValueError as exc:
                raise ValueError("actual_sha256 must be hexadecimal") from exc
        if status == "EXTRACTED" and local_extracted_path is None:
            raise ValueError("EXTRACTED requires local_extracted_path")
        if status == "BRONZE_READY" and bronze_path is None:
            raise ValueError("BRONZE_READY requires bronze_path")
        if status == "FAILED" and not error:
            raise ValueError("FAILED requires a non-empty error")

        now = datetime.now(UTC).isoformat()
        archive_value = (
            str(local_archive_path.expanduser().resolve())
            if local_archive_path is not None
            else current.local_archive_path
        )
        extracted_value = (
            str(local_extracted_path.expanduser().resolve())
            if local_extracted_path is not None
            else current.local_extracted_path
        )
        bronze_value = (
            str(bronze_path.expanduser().resolve())
            if bronze_path is not None
            else current.bronze_path
        )
        sha256_value = actual_sha256 or current.actual_sha256
        attempt_increment = 1 if status == "DOWNLOADING" else 0
        last_error = error if status == "FAILED" else None
        with self._connection:
            self._connection.execute(
                """
                UPDATE gdelt_artifact_manifest
                SET status = ?,
                    local_archive_path = ?,
                    local_extracted_path = ?,
                    bronze_path = ?,
                    actual_sha256 = ?,
                    attempt_count = attempt_count + ?,
                    last_error = ?,
                    updated_at_utc = ?
                WHERE source_url = ?
                """,
                (
                    status,
                    archive_value,
                    extracted_value,
                    bronze_value,
                    sha256_value,
                    attempt_increment,
                    last_error,
                    now,
                    source_url,
                ),
            )
        updated = self.get(source_url)
        if updated is None:
            raise RuntimeError(f"manifest row disappeared after transition: {source_url}")
        return updated

    @staticmethod
    def _to_record(row: sqlite3.Row) -> ArtifactRecord:
        return ArtifactRecord(
            source_url=row["source_url"],
            dataset=row["dataset"],
            source_timestamp=row["source_timestamp"],
            expected_size_bytes=row["expected_size_bytes"],
            expected_md5=row["expected_md5"],
            status=row["status"],
            local_archive_path=row["local_archive_path"],
            local_extracted_path=row["local_extracted_path"],
            bronze_path=row["bronze_path"],
            actual_sha256=row["actual_sha256"],
            attempt_count=row["attempt_count"],
            last_error=row["last_error"],
            discovered_at_utc=row["discovered_at_utc"],
            updated_at_utc=row["updated_at_utc"],
        )
