# Sprint 4 — Research Log

This is the linear train-of-thought for the sprint, tracking questions and their resolution.

## Thread A: Architecture & Feature Engineering
1. **How do we make the daily scanner faster?** → Migrated procedural logic in Python to DuckDB using `FeaturePipeline`, resulting in a ~17x speedup (60s to 3.6s). [sprint_4_summary.md](verdicts/sprint_4_summary.md)
2. **How do we eliminate survivorship bias?** → Built a Dynamic Universe Backfill engine (`src/universe_backfill.py`) to systematically record the historical composition of the market across up to 4,500 active/delisted companies.

## Thread B: Data Integrity
1. **How do we stop duplicate trade bleeding?** → Implemented a session-based state machine in `v_d1_candidates`, enforcing one prediction target per trend.
2. **Why do holding times look unrealistically long?** → Altered `v_d2r_hydrated` to abandon the 120-day blind window and stop exactly when C1-C9 filters fail. This drops median hold times to 24 days, mirroring genuine human SEPA execution.

---

## Open meta-questions
- **Execution Parity (CRITICAL)**: DuckDB assumes trades fill at `T+1 Open` (physical slippage), while Python `trade_simulator.py` assumes `T Close`. We must unify both platforms onto a single logic before ML deployment.
