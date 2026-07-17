from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .runner import ExperimentResult
from .schema import ExperimentPlan, HypothesisSpec

_SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_meta (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS hypothesis (
    hypothesis_id TEXT PRIMARY KEY,
    claim_text TEXT NOT NULL,
    spec_json TEXT NOT NULL,
    plan_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'compiled',
    parent_hypothesis_id TEXT,
    FOREIGN KEY(parent_hypothesis_id) REFERENCES hypothesis(hypothesis_id)
);

CREATE TABLE IF NOT EXISTS experiment_run (
    run_id TEXT PRIMARY KEY,
    hypothesis_id TEXT NOT NULL,
    plan_hash TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    status TEXT NOT NULL,
    decision TEXT NOT NULL,
    result_json TEXT NOT NULL,
    FOREIGN KEY(hypothesis_id) REFERENCES hypothesis(hypothesis_id)
);

CREATE TABLE IF NOT EXISTS validation_metric (
    run_id TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    metric_value REAL NOT NULL,
    PRIMARY KEY(run_id, metric_name),
    FOREIGN KEY(run_id) REFERENCES experiment_run(run_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS robustness_check (
    run_id TEXT NOT NULL,
    check_type TEXT NOT NULL,
    repeat INTEGER NOT NULL,
    metrics_json TEXT NOT NULL,
    PRIMARY KEY(run_id, check_type, repeat),
    FOREIGN KEY(run_id) REFERENCES experiment_run(run_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_run_hypothesis ON experiment_run(hypothesis_id, started_at);
CREATE INDEX IF NOT EXISTS idx_hypothesis_status ON hypothesis(status);
"""


class HypothesisRegistry:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connection() as connection:
            connection.executescript(_SCHEMA)
            connection.execute("INSERT OR IGNORE INTO schema_meta(version) VALUES (1)")

    def register(self, spec: HypothesisSpec, plan: ExperimentPlan) -> None:
        with self.connection() as connection:
            connection.execute(
                """
                INSERT INTO hypothesis(
                    hypothesis_id, claim_text, spec_json, plan_hash, created_at, status
                ) VALUES (?, ?, ?, ?, ?, 'compiled')
                ON CONFLICT(hypothesis_id) DO UPDATE SET
                    claim_text=excluded.claim_text,
                    spec_json=excluded.spec_json,
                    plan_hash=excluded.plan_hash
                """,
                (
                    plan.hypothesis_id,
                    spec.claim,
                    spec.model_dump_json(exclude_none=True),
                    plan.plan_hash,
                    plan.compiled_at.isoformat(),
                ),
            )

    def save_result(self, result: ExperimentResult) -> None:
        metrics = {
            "coefficient": result.coefficient,
            "standard_error": result.standard_error,
            "t_value": result.t_value,
            "p_value": result.p_value,
            "q_value": result.q_value,
            "oos_r2": result.oos_r2,
            "fold_sign_agreement": result.fold_sign_agreement,
            "condition_number": result.condition_number,
        }
        with self.connection() as connection:
            connection.execute(
                """
                INSERT INTO experiment_run(
                    run_id, hypothesis_id, plan_hash, started_at, finished_at,
                    status, decision, result_json
                ) VALUES (?, ?, ?, ?, ?, 'completed', ?, ?)
                """,
                (
                    result.run_id,
                    result.hypothesis_id,
                    result.plan_hash,
                    result.started_at.isoformat(),
                    result.finished_at.isoformat(),
                    result.decision.value,
                    result.model_dump_json(),
                ),
            )
            connection.executemany(
                "INSERT INTO validation_metric(run_id, metric_name, metric_value) VALUES (?, ?, ?)",
                [(result.run_id, name, value) for name, value in metrics.items()],
            )
            connection.executemany(
                """
                INSERT INTO robustness_check(run_id, check_type, repeat, metrics_json)
                VALUES (?, ?, ?, ?)
                """,
                [
                    (
                        result.run_id,
                        item.placebo.value,
                        item.repeat,
                        json.dumps(
                            {"oos_r2": item.oos_r2, "coefficient": item.coefficient},
                            sort_keys=True,
                        ),
                    )
                    for item in result.placebos
                ],
            )
            connection.execute(
                "UPDATE hypothesis SET status=? WHERE hypothesis_id=?",
                (result.decision.value, result.hypothesis_id),
            )

    def get_hypothesis(self, hypothesis_id: str) -> dict[str, object] | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM hypothesis WHERE hypothesis_id=?", (hypothesis_id,)
            ).fetchone()
        return dict(row) if row else None

    def get_result(self, run_id: str) -> ExperimentResult | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT result_json FROM experiment_run WHERE run_id=?", (run_id,)
            ).fetchone()
        return ExperimentResult.model_validate_json(row[0]) if row else None
