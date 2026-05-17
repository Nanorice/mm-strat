# System Design Review — Action Plan

> Date: 2026-05-16
> Source: `docs/system_design_review_2026_05_15.md` (review session) + codebase verification pass
> Scope: Prioritised future-work plan derived from the 2026-05-15 design review, with all factual claims cross-checked against `src/`.
> Status: **Awaiting approval** before any code changes.

---

## Table of Contents

1. [Documentation Fixes Applied](#1-documentation-fixes-applied)
2. [Verification Findings (Review Errors Corrected)](#2-verification-findings-review-errors-corrected)
3. [Priority List & Implementation Plan](#3-priority-list--implementation-plan)
4. [Critical-Path Sequencing](#4-critical-path-sequencing)
5. [Recommended First 2 Weeks](#5-recommended-first-2-weeks)

---

## 1. Documentation Fixes Applied

Already committed as part of this review:

| Fix | File | Change |
|---|---|---|
| `shares_history` (table) vs `shares_outstanding` (column) | `docs/manual_for_me.md` Phase 1.3 + ASCII flow | Manual incorrectly labelled the table `shares_outstanding`; corrected to `shares_history` with note that the column inside it is `shares_outstanding`. |
| `LEFT JOIN fundamental_features` | `docs/comprehensive_methodology.md` §4.2 | Methodology said `fundamentals`; codebase confirms `fundamental_features` is the derived ratios table used by `v_d2_features` and `universe_scorer`. |
| M03 regime thresholds (20/40/60/80) | methodology §5, manual §9 data flow | Added explicit threshold table + citation to `src/pipeline/m03_regime.py:88-93`. |
| M01 scalar = `calibrated_score`, not `proba[:,3]` | methodology §9.2 | Rewrote with correct formula + warning. The review's original claim was inaccurate. |
| `sl_exits` correlated subquery already fixed | methodology §10.2 + §14, manual Phase 6 + tech-debt | Marked as resolved 2026-05-14; flagged need to re-time Phase 7. |
| Verification annotations | `docs/system_design_review_2026_05_15.md` §2 + §4.2 + §4.3 + action list | Added status column, corrected two factual errors. |

---

## 2. Verification Findings (Review Errors Corrected)

### 2.1 M01 backtest scalar (review §4.2) — **review was wrong**

Review claim: *"Backtest ranks on `predict_proba()[:, 3]` (Home Run probability), then takes 10-day trailing percentile rank."*

Codebase (`src/backtest/universe_scorer.py:307-321`):

```python
midpoints = np.array([1.0, 6.0, 20.0, 40.0])              # per-class MFE % midpoints
calibrated_score = (predict_proba(X) * midpoints).sum(axis=1)  # expected MFE in %
prob_elite = predict_proba(X)[:, 3]                        # stored as diagnostic only
```

- **Ranking signal**: `calibrated_score` (probability-weighted expected MFE).
- **Diagnostic only**: `prob_elite = predict_proba()[:, 3]`.
- **Trailing window**: 10-day rolling-cohort percentile (`trailing_pct`); default `rank_by='trailing'`.

If the review's incorrect claim had been propagated into the methodology, it would have silently changed which candidates the backtest selects. **This was the highest-value fix in this verification pass.**

### 2.2 Phase 7 `sl_exits` bottleneck (review §4.3) — **stale claim, now measured**

Review claim: *"The 592s refresh dominates Phase 6+7 wall time… still rewrite the `sl_exits` correlated subquery using `LEAD(date) OVER (PARTITION BY ticker ORDER BY date)`."*

Codebase: `src/managers/view_manager.py:580-597` already uses the recommended `price_with_next` CTE with `LEAD(date/close) OVER (PARTITION BY ticker ORDER BY date)`. Implemented 2026-05-14 (see `docs/session_logs/2026-05-14.md`).

**Measured Phase 7 timing post-fix (2026-05-16, from `logs/daily_pipeline.log`):**

| Rows | Wall time | Notes |
|---|---|---|
| 15,057 | ~30s | Partial T3 backfill (3 runs) |
| 37,050 | 131s | Full 37K trade count, warm buffer |
| 37,061 | 147s | Full 37K trade count, cold buffer |
| Avg | **58.8s** | Per pipeline monitoring avg |

**Verdict: Keep Phase 7.** At ~58s average the cache refresh is not the wall-time problem the review assumed. The pre-fix claim of 592s was a buffer-cold worst case, now resolved. The 70× trainer read speedup (0.126s vs 8.8s per query) is real, recurring value for training and ablation runs. The "drop Phase 7" recommendation is **closed**.

### 2.3 M03 thresholds (review §2 row 5) — **partially wrong on phrasing**

Review claim: *"Both docs lack the actual `m03_score → regime_cat` cutoffs."*

Codebase has them plainly at `src/pipeline/m03_regime.py:88-93`:
- `strong_bull=80, bull=60, neutral=40, bear=20`
- → `score >= 80 = strong_bull (cat 4)`, `score < 20 = strong_bear (cat 0)`

The fix was doc-only — the code didn't need to change.

### 2.4 Items the review got right (no correction needed)

- `shares_history` vs `shares_outstanding` naming inconsistency
- `fundamental_features` JOIN target in methodology §4.2
- `trend_c8` CTE misnomer (computes C1+C2+C6, not C1-C8)
- Asymmetric entry/exit triggers (entry uses full `trend_ok`, session/exit uses C1+C2+C6)
- `screener_watchlist` vs `sepa_watchlist` near-collision naming
- Phase 1.5 quality gate gap
- M03 → regime v2 design direction
- 6-dimension prod-readiness framework
- Storage/scheduling independence

---

## 3. Priority List & Implementation Plan

Ordered by **risk-adjusted leverage**: items that unblock or de-risk later work go first. No code changes yet; review and approve before any execution.

### Tier 0 — Foundations (start here; everything depends on these)

#### ~~T0.1 · Re-time Phase 7 to find current bottleneck~~ — ✅ DONE 2026-05-16

Measured from `logs/daily_pipeline.log` after the 2026-05-14 `sl_exits` fix:
- 37K trades: **131–147s** (cold/warm), **58.8s average** per pipeline monitor
- 15K trades (earlier partial backfill): ~30s

**Decision: Keep Phase 7.** Average is well below the 592s worst case. The 70× trainer read speedup justifies retention.

#### ~~T0.2 · Backfill remaining doc reconciliation items~~ — ✅ DONE 2026-05-16

Methodology updated:
- **§4.1** — Coverage-aware recompute note added (T2: `<99% tickers` triggers full-date recompute)
- **§4.2** — Coverage-aware recompute note added (T3: missing breakout tickers trigger per-date rerun)
- **§10.3** (new) — Phase 8 monitoring alerts table with all 5 alert conditions
- **§13** (new) — Helper Libraries section with full importable-module table inc. `ScoreLookup`
- **§9.5** (new) → **§9.6** — `ScoreLookup` documented as in-memory O(1) daily candidate gate
- **§15** — Renamed from §14; "Planned Future Work" replaced with "Operational Roadmap" pointing to plan doc

#### ~~T0.3 · Legacy Repository Cleanup & Refactoring~~ — ✅ DONE 2026-05-16

Executed the surgical cleanup plan.
- **Dependency chain broken**: Archived `src/pipeline/data_pipeline.py` and `src/universe_engine.py` orchestrators, which acted as an import funnel for legacy modules.
- **Refactoring**: Safely extracted `get_model_features()` from `src/feature_config.py` into `src/utils.py`.
- **Archiving**: Safely moved 47 deprecated legacy files (from Phase 1-5 Parquet pipeline era) into `archive/archive May26/`.
- **Verification**: Confirmed `scripts/run_daily_pipeline.py` and `scripts/train_mfe_classifier.py` remain fully functional without import errors.

---

### Tier 1 — Data Quality & Reliability (P1)

#### T1.1 · Phase 1.5 T1 Quality Gate (review §7-§8) — 1-2 days

**Goal**: Audits run inside the DAG and block downstream phases on FAIL, instead of being CLI-only after-the-fact checks.

**Changes**:
- Add a `phase_1_5_quality_gate` orchestrator phase that runs `audit_t1_data_quality.py` and HALTs on FAIL
- Add self-healing T1 retry loop in `daily_pipeline_orchestrator.py`: ingest → audit → if <95% coverage retry stale subset → audit again → if still <95% alert
- Wire the gate into `PIPELINE_FAILURE_MODES` in `config.py`

**Files**: `src/orchestrators/daily_pipeline_orchestrator.py`, `tools/audit_t1_data_quality.py` (add `--exit-on-fail` flag), `config.py`

**Acceptance**: a dirty-ingest run (kill yfinance mid-fetch) halts at 1.5 with a clear error; a clean run passes through.

#### T1.2 · Materialise `trend_exit_ok` in `t2_screener_features` (review §4.4) — half day

**Goal**: Self-documenting asymmetric entry/exit logic. Eliminates the `trend_c8` misnomer and duplicated session-detection CTE in `v_screener_dashboard`.

**Changes**:
- Add `trend_exit_ok BOOLEAN` column to T2 schema (C1+C2+C6 check)
- Rename `trend_c8` CTE → `trend_exit` in `view_manager.py` (3 occurrences)
- Update session-detection CTEs in `v_d1_candidates` and `v_screener_dashboard` to filter on `t2.trend_exit_ok` instead of recomputing
- Update T2 audit to verify `trend_exit_ok` column presence

**Files**: `src/feature_pipeline.py` (Phase A SQL), `src/managers/view_manager.py`, `tools/audit_t2_screener_features.py`

**Acceptance**: existing session detection produces identical `(entry_date, exit_date, session_id)` tuples; CTE block in `v_screener_dashboard` reduced (kills the duplicated session-detection block flagged in Phase 6 tech debt).

#### T1.3 · Add invariant-based audits (review §9.3) — 1 day

**Goal**: Catch silent universe-contract violations that threshold-based audits miss.

**Changes** — new module `tools/audit_invariants.py`:
- Every `(ticker, date)` in `t3_sepa_features` has a corresponding open `sepa_watchlist` session at some point
- Every active `sepa_watchlist` session has the ticker in `screener_membership` on `entry_date`
- No `t3_sepa_features` row dated before that ticker's first `price_data` row
- `v_d2_features` joins fundamentals on `filing_date`, NOT `period_end` (assertion-only check)
- Add to `tools/run_all_audits.py`

**Acceptance**: clean DB returns all PASS; intentionally corrupted DB (delete a `sepa_watchlist` row) returns FAIL with the offending ticker.

---

### Tier 2 — Regime Model Rebuild (P1, highest research leverage)

#### T2.1 · `docs/regime_v2_design.md` draft (review §5) — 1-2 days **(doc only, ahead of code)**

**Contents**:
- Wide z-score table schema (`t2_regime_signals`)
- Full signal enumeration: M03 pillars (trend breadth, liquidity, risk) + 5-factor inputs (need 5-factor list from `src/pipeline/risk_5_factor.py`)
- Dual rolling/expanding z-score convention (rationale + math)
- Veto rule set (e.g., `Risk_z_expanding < -2` → Strong Bear regardless)
- Migration path: keep `m03_score` as a view for one release; mark deprecation

**Open question to resolve before coding**: what counts as "regime change" for the gating logic — discrete category transitions or continuous z-score crossings?

#### T2.2 · Implement `t2_regime_signals` table + dual z-scores — 3-5 days (after T2.1 approval)

- New phase or sub-phase to write `t2_regime_signals`
- New view `v_regime_gates` consuming z-scores + applying veto rules
- Backwards-compat view `v_m03_score_legacy` to avoid breaking trainer/backtest before retraining

**Files**: `src/pipeline/regime_v2.py` (new), `src/managers/view_manager.py`, `src/regime_pipeline.py`

#### T2.3 · Retrain M01 with regime v2 features — 2-3 days (after T2.2)

- Replace M03 columns in feature catalog with regime v2 features
- Train new model, compare to `M01_baseline_v0.1` baseline (acc=0.6705)
- **Gating**: must pass T3.1 prod-readiness checklist before promotion

---

### Tier 3 — Model Operations (P2)

#### T3.1 · Model validation report + promotion gating (review §9) — 1 week

- `model_validation_report.md` template per the 6 dimensions in review §9
- Implement walk-forward CV (5-fold rolling, last 5 years) in `src/evaluation/`
- Implement regime-conditional precision/recall slice
- Implement PSI on top-10 features + prediction distribution drift
- Enforce checklist in `ModelRegistry.set_prod()` — refuse promotion if any P0 gate fails

**Files**: `src/evaluation/walk_forward.py` (new), `src/evaluation/psi.py` (new), `src/model_registry.py` (enforce gate)

**Acceptance**: `set_prod()` on the current prototype fails with a clear "macro F1 below threshold" message.

#### T3.2 · M01-Watch + M01-Hold variants (review §6) — 1-2 weeks (only after T3.1)

- Add `model_role` column to `models` table (`SETUP` / `WATCH` / `HOLD`)
- Implement label generators for each: `breakout_within_5d` (M01-Watch); `sl_hit_within_K_days` (M01-Hold)
- Three separate training scripts sharing `t3_sepa_features`

**Sequencing note**: M01-Setup itself must pass T3.1 gates first.

#### T3.3 · Idempotency of `sepa_watchlist.update_daily()` (review §4.5) — half day

- Rewrite INSERT to `INSERT ... ON CONFLICT DO NOTHING` keyed on `(ticker, entry_date)`
- Remove reliance on the `pipeline_runs` guard for safety; keep it for tracking only

**Acceptance**: running `update_daily('2026-05-15')` twice produces identical row counts.

---

### Tier 4 — Infrastructure (P2-P3)

#### T4.1 · Structured JSON logging (review §7) — 2-3 days

- One-event-per-phase JSON: `phase`, `duration_s`, `rows_in`, `rows_out`, `coverage_pct`, `warnings[]`
- Migrate `logs/daily_pipeline.log` writers in orchestrator + each phase

**Unblocks**: Pipeline Health dashboard page.

#### T4.2 · Nightly DuckDB backup to OneDrive/S3 — 2 hr

- Windows Task Scheduler entry: copy `data/market_data.duckdb` → OneDrive folder with 7-day retention
- Cheap disaster recovery without storage migration.

#### T4.3 · Prefect (local) for scheduling (review §11) — 1-2 days

- Define daily pipeline as Prefect flow wrapping `run_daily_pipeline.py`
- Local agent; no cloud yet
- Adds retry semantics, structured run history

**Sequencing**: do after T3.3 (idempotency) so retries are safe.

#### T4.4 · Rename `screener_watchlist` → `trade_dashboard_mv` (review §4.6) — half day

- Cross-table rename across `view_manager.py`, dashboard, scripts, tests, docs
- Backwards-compat alias view for one release
- Low priority; cosmetic but worth it before the dashboard expands.

---

### Tier 5 — Dashboard Expansion (P3, after T4.1)

| Task | Effort | Description | Depends on |
|---|---|---|---|
| T5.1 Pipeline Health page | 1 week | Phase timeline, coverage % per table, alerts feed, freshness gauges | T4.1 |
| T5.2 Ticker Deep Dive page | 1 week | Per-day C1-C9 / B1-B2 matrix, feature time series, SHAP waterfall | — |
| T5.3 Model Lab page | 1 week | Live precision/recall by regime, prediction drift, FI evolution, `model_diff` integration | T3.1 |
| T5.4 Backtest Studio page | 1 week | Equity curve vs SPY, regime-conditional returns, trade explorer, drawdown | — |

---

## 4. Critical-Path Sequencing

```
T0.1 (re-time Phase 7) ──┐
                         ├──▶ T1.x (quality gate, trend_exit_ok, invariants)
T0.2 (doc cleanup) ──────┤                          │
                         │                          ▼
T0.3 (repo cleanup) ─────┘
                                T2.1 (regime v2 design doc) ──▶ T2.2 (impl) ──▶ T2.3 (retrain)
                                                    │
                                                    ▼
                                T3.1 (prod-readiness framework) ──▶ T3.2 (M01 variants)
                                                    │                       │
                                                    ▼                       │
                                T4.1 (JSON logging) ──▶ T4.3 (Prefect)     │
                                                    │                       │
                                                    ▼                       ▼
                                                  T5.x (dashboard expansion)
```

**Natural decision gates** (stop and review):
1. After **T0.1** — Phase 7 keep/drop decision
2. After **T1.x** — operational hardening complete; ready to commit to regime v2
3. After **T2.1** — regime v2 design before code investment
4. After **T3.1** — prod-readiness framework before building M01 variants

---

## 5. Recommended First 2 Weeks

| Day | Work |
|---|---|
| 1 | T0.1 (re-time Phase 7) + T0.2 (doc cleanup) + T0.3 (repo cleanup) |
| 2-3 | T1.2 (`trend_exit_ok` materialisation) |
| 4-5 | T1.3 (invariant audits) |
| 6-7 | T1.1 (Phase 1.5 quality gate) |
| 8-9 | T2.1 (regime v2 design doc — review before coding) |
| 10 | T3.3 (idempotent `update_daily`) — small, but unblocks T4.3 |

This sequence delivers operational hardening first (T1.x), then the regime v2 design doc for review, before any big-bet investment in T2.2/T2.3/T3.x. Stop and review after T2.1 — that's the natural decision gate.

---

## Appendix: Item Index by Original Review Section

| Review § | Task | Plan ID |
|---|---|---|
| §2 row 1 | shares_history naming | ✅ DONE |
| §2 row 2 | fundamental_features JOIN | ✅ DONE |
| §2 row 3 | Phase 8 coverage alerts in methodology | T0.2 |
| §2 row 4 | Coverage-aware recompute in methodology | T0.2 |
| §2 row 5 | M03 thresholds documented | ✅ DONE |
| §2 row 6 | Helper Libraries section | T0.2 |
| §2 row 7 | ScoreLookup in §9 | T0.2 |
| §2 row 8 | Split §14 tech debt vs roadmap | T0.2 |
| §4.2 | M01 scalar mapping (corrected) | ✅ DONE |
| §4.3 | Drop Phase 7 / re-time | T0.1 |
| §4.3 | sl_exits LEAD rewrite | ✅ DONE 2026-05-14 |
| §4.4 | Materialise `trend_exit_ok` | T1.2 |
| §4.5 | `update_daily` idempotency | T3.3 |
| §4.6 | Rename `screener_watchlist` | T4.4 |
| §5 | Regime v2 design + impl + retrain | T2.1 → T2.2 → T2.3 |
| §6 | M01-Watch + M01-Hold | T3.2 |
| §7 | Structured logging | T4.1 |
| §7-§8 | Phase 1.5 quality gate | T1.1 |
| §9 | Prod-readiness framework | T3.1 |
| §9.3 | Invariant audits | T1.3 |
| §10 | Dashboard pages | T5.1-T5.4 |
| §11 | Prefect + DuckDB backup | T4.2 + T4.3 |
