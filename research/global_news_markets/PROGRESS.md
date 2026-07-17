# Global News Markets Research Progress

## 2026-07-17 — Foundation run 1

### Completed

- Created the dedicated `research/global-news-markets` branch from Hypothesis Lab v1.
- Added a Chinese preregistration protocol with frozen time splits, confirmation/exploration separation, model families, placebo design, hierarchical FDR, economic-significance gates and final-report acceptance criteria.
- Registered a 110-asset candidate universe across A-shares, Korean equities, Japanese equities, U.S. equities, CME futures, London benchmarks/proxies and FX.
- Added a machine-readable data-source registry and a publication/licence matrix.
- Preregistered the first 24 high-priority hypotheses toward the final 96-hypothesis registry.
- Implemented deterministic timezone/session alignment for XSHG, XKRX, XJPX, XNYS, XCME and XLON.
- Added support for pre-market, regular, post-market, midday-break, CME maintenance and closed states.
- Added reaction-start timestamps, cross-midnight CME trading dates, IANA DST handling, explicit holiday snapshots and early-close overrides.
- Added nine unit tests covering DST, SSE pre-market and lunch break, NYSE Friday post-market, CME Sunday sessions, maintenance, weekend closure, holidays and early closes.
- Added machine-readable Ruff and mypy CI diagnostics with short-lived workflow artifacts.
- Resolved inherited strict-lint and NumPy typing failures, and made the quality workflow run on research branches.

### Validation performed

- Isolated calendar test suite: `9 passed`.
- Python byte-code compilation of the new calendar module succeeded.
- GitHub Actions run `29556296797` passed all jobs.
- Python 3.11: Ruff, strict mypy, full pytest with coverage gate, package build and Hypothesis Lab demo all passed.
- Python 3.12: Ruff, full pytest with coverage gate, package build and Hypothesis Lab demo all passed.
- The legacy attention-study workflow also completed, but it is retained only as a regression check and is not the new research target.

### Known limitations

- Built-in calendar definitions contain framework trading hours but not yet complete versioned holiday/special-session snapshots.
- SSE/SZSE, CME, U.S. consolidated prices, intraday FX and LBMA official benchmarks require entitlement or further licence verification.
- JPX and SSE lunch breaks are represented; product-specific auction and night-session rules remain to be added.
- The first 24 hypotheses are a pipeline-validation tranche, not yet the full 96-hypothesis frozen registry.
- No market-price dataset has yet been committed or claimed as validated in this branch.

### Next highest-priority work

1. Add versioned official holiday/special-session snapshot ingestion and hashes.
2. Build GDELT finance entity aliases, theme definitions and source-domain geography classification.
3. Implement the first lawful daily-price provider and a nine-benchmark feasibility panel.
4. Add event-study and local-projection runners with clustered covariance and hierarchical FDR.
5. Replace the legacy attention-study CI job with the first global-news market feasibility workflow once the lawful price panel is ready.
