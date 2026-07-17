# Changelog

All notable project changes will be recorded in this file.

## [Unreleased]

### Added

- Initial mathematical modeling definition.
- Initial local-first engineering design.
- Initial pre-development validation checklist.
- Executable milestone roadmap and GitHub Issue backlog.
- Repository README, agent contract, issue template, and ignore rules.
- Python 3.11 package, dependency groups, CLI and GitHub Actions CI.
- Local M1 preflight with disk, dependency, SQLite WAL/FTS5 and runtime-path checks.
- Strict GDELT `lastupdate.txt` parser requiring aligned Events, EventMentions and GKG artifacts.
- Bounded, MD5/SHA-256-verified GDELT download and safe single-member ZIP extraction.
- GDELT field-count contracts for Events, EventMentions and GKG samples.
- Atomic, idempotent, partitioned ZSTD Bronze Parquet conversion with lineage manifests.
- Real GDELT sample workflow that validates one aligned trio through Parquet and DuckDB.
- Sanitized evidence receipt for the `20260717054500` Events/GKG/EventMentions trio.
- Transactional SQLite artifact manifest with conflict detection, restart states and attempt history.
- Frozen 103-asset universe, 96 confirmatory hypothesis cells, data-source registry and licence matrix.
- Frozen global news–multi-market research protocol, M1 runbook and live validation findings.
- Registry drift tests for asset count, unique IDs, IANA timezones and locked hypothesis expansion.

### Fixed

- Replaced the non-IANA `Europe/Frankfurt` timezone with `Europe/Berlin` for ECB FX reference assets.
- Preserved strict HTTPS verification while making legacy GDELT HTTP fallback explicit and auditable.
- Added first-party import classification and corrected postponed annotations for clean Ruff checks.

### Status

- The latest real 15-minute GDELT trio completed byte/MD5/SHA-256, ZIP CRC, 61/16/27-column, Parquet and DuckDB checks.
- The cloud engineering sample is `GO`; overall M1 remains `CONDITIONAL_GO` because GDELT HTTPS currently fails hostname validation, the CI disk is below 300GB, and the user's target machine has not completed the same gate.
- M2 restartable data-foundation work has begun under the accepted conditional gate.
- No market-effect hypothesis or final report result is claimed yet.
