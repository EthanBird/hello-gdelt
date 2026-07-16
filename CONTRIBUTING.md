# Contributing

## Development sequence

Do not begin model discovery or MCP mutation work before the M1 validation report records GO or an explicitly accepted CONDITIONAL GO.

## Local setup

```bash
python3.11 -m venv --copies .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/ruff check .
.venv/bin/pytest
```

## Branches and pull requests

- Use one bounded branch per Issue: `codex/<issue>-<topic>` or `feature/<issue>-<topic>`.
- Keep `main` reproducible and reviewable.
- Link the Issue, describe non-scope, and include exact verification commands.
- Data-contract or architecture changes require an ADR or an update to an accepted ADR.
- Never commit raw GDELT archives, Parquet data, SQLite databases, credentials, or machine-specific reports.

## Data changes

Every generated artifact must retain source identity, batch, checksum, schema version, mapping version, configuration version, code version, row count, and creation time. Unknown or ambiguous values remain explicit; they are never silently coerced.

## Definition of done

- Public contract or schema is documented.
- Normal, boundary, malformed-input, retry, and restart behavior is tested as applicable.
- The operation is deterministic or its nondeterminism is recorded.
- Resource and security limits are explicit.
- User-visible behavior and runbooks are updated.
- The PR includes reproducible evidence and no ground-truth language such as `true_risk`.
