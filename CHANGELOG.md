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
- Bounded, MD5-verified GDELT download and safe single-member ZIP extraction.
- GDELT field-count contracts for Events, EventMentions and GKG samples.
- Frozen 103-asset universe, 96 confirmatory hypothesis cells, data-source registry and licence matrix.
- Frozen global news–multi-market research protocol and M1 runbook.
- Registry drift tests for asset count, unique IDs, IANA timezones and locked hypothesis expansion.

### Fixed

- Replaced the non-IANA `Europe/Frankfurt` timezone with `Europe/Berlin` for ECB FX reference assets.

### Status

- M1 implementation is in progress on `research/global-news-market-v0.1`.
- Unit tests pass in the available runtime; real GDELT network and columnar-stack validation must still run on the target machine before a GO decision.
- No market-effect hypothesis or final report result is claimed yet.
