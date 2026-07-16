# Changelog

All notable project changes will be recorded in this file.

## [Unreleased]

### Added

- Initial mathematical modeling definition.
- Initial local-first engineering design.
- Initial pre-development validation checklist.
- Executable milestone roadmap and GitHub Issue backlog.
- Repository README, agent contract, issue template, and ignore rules.
- Python 3.11/3.12 project scaffold and CLI.
- HTTPS-first GDELT source probe with explicit HTTP fallback.
- Atomic download with official size/MD5, local SHA-256, ZIP safety, and field checks.
- Latest-complete-batch fallback using a ranged masterfilelist tail request.
- Typed Bronze/Silver/Gold minimal pipeline using PyArrow and DuckDB.
- SQLite WAL control plane with source/artifact lineage and validation runs.
- Local-only FastAPI health endpoint.
- Automated lint, schema, downloader, pipeline, idempotence, SQLite, DuckDB and API tests.

### Fixed

- Prevented mixed GDELT batches when the newest GKG object is listed but unavailable.
- Fixed DuckDB session-timezone conversion by pinning pipeline validation to UTC.
- Enforced stable Silver deduplication keys and idempotent artifact registration.

### Status

- M1 validation foundation is implemented on the development branch; model implementation is not claimed.
