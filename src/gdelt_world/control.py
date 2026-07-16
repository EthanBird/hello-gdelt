from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

SCHEMA_VERSION = 2


def connect_control(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=5000")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS schema_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS source_file (
            id INTEGER PRIMARY KEY,
            dataset_kind TEXT NOT NULL,
            batch_id TEXT NOT NULL,
            source_url TEXT NOT NULL,
            local_path TEXT NOT NULL UNIQUE,
            size_bytes INTEGER NOT NULL,
            md5 TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            rows INTEGER NOT NULL,
            field_count INTEGER NOT NULL,
            observed_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS dataset_artifact (
            id INTEGER PRIMARY KEY,
            layer TEXT NOT NULL,
            dataset_name TEXT NOT NULL,
            batch_id TEXT NOT NULL,
            local_path TEXT NOT NULL UNIQUE,
            sha256 TEXT NOT NULL,
            rows INTEGER NOT NULL,
            source_file_id INTEGER,
            schema_version INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(source_file_id) REFERENCES source_file(id)
        );

        CREATE TABLE IF NOT EXISTS validation_run (
            id INTEGER PRIMARY KEY,
            run_type TEXT NOT NULL,
            status TEXT NOT NULL,
            details_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_source_file_batch ON source_file(batch_id, dataset_kind);
        CREATE INDEX IF NOT EXISTS idx_artifact_batch ON dataset_artifact(batch_id, layer);
        """
    )
    source_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(source_file)").fetchall()
    }
    if "sha256" not in source_columns:
        connection.execute("ALTER TABLE source_file ADD COLUMN sha256 TEXT NOT NULL DEFAULT ''")
    connection.execute(
        "INSERT OR REPLACE INTO schema_metadata(key, value) VALUES ('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
    connection.commit()
    return connection


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def register_source_file(
    connection: sqlite3.Connection,
    *,
    dataset_kind: str,
    batch_id: str,
    source_url: str,
    local_path: Path,
    size_bytes: int,
    md5: str,
    sha256: str,
    rows: int,
    field_count: int,
) -> int:
    now = datetime.now(UTC).isoformat()
    connection.execute(
        """
        INSERT INTO source_file(
            dataset_kind, batch_id, source_url, local_path, size_bytes,
            md5, sha256, rows, field_count, observed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(local_path) DO UPDATE SET
            size_bytes=excluded.size_bytes,
            md5=excluded.md5,
            sha256=excluded.sha256,
            rows=excluded.rows,
            field_count=excluded.field_count,
            observed_at=excluded.observed_at
        """,
        (
            dataset_kind,
            batch_id,
            source_url,
            str(local_path),
            size_bytes,
            md5,
            sha256,
            rows,
            field_count,
            now,
        ),
    )
    row = connection.execute(
        "SELECT id FROM source_file WHERE local_path = ?", (str(local_path),)
    ).fetchone()
    connection.commit()
    return int(row[0])


def register_artifact(
    connection: sqlite3.Connection,
    *,
    layer: str,
    dataset_name: str,
    batch_id: str,
    local_path: Path,
    rows: int,
    source_file_id: int | None,
    schema_version: int = 1,
) -> None:
    connection.execute(
        """
        INSERT INTO dataset_artifact(
            layer, dataset_name, batch_id, local_path, sha256, rows,
            source_file_id, schema_version, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(local_path) DO UPDATE SET
            sha256=excluded.sha256,
            rows=excluded.rows,
            source_file_id=excluded.source_file_id,
            schema_version=excluded.schema_version,
            created_at=excluded.created_at
        """,
        (
            layer,
            dataset_name,
            batch_id,
            str(local_path),
            sha256_file(local_path),
            rows,
            source_file_id,
            schema_version,
            datetime.now(UTC).isoformat(),
        ),
    )
    connection.commit()


def record_validation(
    connection: sqlite3.Connection,
    *,
    run_type: str,
    status: str,
    details: dict[str, object],
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO validation_run(run_type, status, details_json, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (
            run_type,
            status,
            json.dumps(details, ensure_ascii=False, sort_keys=True),
            datetime.now(UTC).isoformat(),
        ),
    )
    connection.commit()
    return int(cursor.lastrowid)
