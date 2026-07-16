# AGENTS.md

## Project contract

This repository builds a local-first GDELT computable-world research system. Treat GDELT as a media-observation stream, not ground truth.

## Non-negotiable rules

- Read `README.md` and the relevant files under `docs/` before changing scope or architecture.
- Do not call an indicator `true_risk`, `actual_policy_intent`, or an equivalent ground-truth claim.
- Do not introduce Kafka, Spark, Flink, Kubernetes, Airflow, or another service-heavy platform into V1 without an accepted ADR.
- Do not let an LLM execute arbitrary SQL/Python, access arbitrary paths, mutate production parameters, or bypass resource limits.
- Preserve temporal causality in every experiment. No future data may enter features, parameter selection, labels, or evidence.
- Every generated dataset must record source identity, source time, schema version, mapping version, config version, and code version.
- Unknown or ambiguous entity mappings must remain visible; never silently coerce them.
- Prefer deterministic, idempotent, restartable ETL.
- Keep services bound to `127.0.0.1` by default.
- Treat `data/` as runtime state. Do not commit raw downloads, Parquet datasets, SQLite databases, secrets, credentials, or local reports containing machine details.

## Development order

Do not begin model or MCP implementation before the pre-development validation milestone has produced a GO or explicitly accepted CONDITIONAL GO report.

## Definition of done

A change is not complete without tests for normal, boundary, and failure behavior; documented contracts; reproducible acceptance evidence; and updated user-facing documentation when behavior changes.
