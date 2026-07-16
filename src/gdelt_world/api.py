from __future__ import annotations

import sqlite3
from pathlib import Path

import duckdb
from fastapi import FastAPI

from gdelt_world import __version__


def create_app(data_root: Path | None = None) -> FastAPI:
    root = data_root or Path("data")
    app = FastAPI(title="Hello GDELT", version=__version__)

    @app.get("/health")
    def health() -> dict[str, object]:
        control = root / "control" / "world_control.sqlite"
        sqlite_ok = True
        schema_version: str | None = None
        if control.exists():
            try:
                connection = sqlite3.connect(f"file:{control}?mode=ro", uri=True)
                row = connection.execute(
                    "SELECT value FROM schema_metadata WHERE key='schema_version'"
                ).fetchone()
                schema_version = row[0] if row else None
                connection.close()
            except sqlite3.Error:
                sqlite_ok = False
        return {
            "status": "ok" if sqlite_ok else "degraded",
            "version": __version__,
            "control_database": "present" if control.exists() else "not_initialized",
            "control_schema_version": schema_version,
            "duckdb_version": duckdb.__version__,
        }

    return app


app = create_app()
