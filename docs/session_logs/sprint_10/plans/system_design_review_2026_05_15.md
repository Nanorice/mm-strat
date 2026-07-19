# System Design Review — Quantamental SEPA Framework

> Date: 2026-05-15
> Scope: High-level architectural review of the Quantamental SEPA pipeline as documented in `docs/comprehensive_methodology.md` (white paper) and `docs/manual_for_me.md` (source of truth).
> Purpose: Capture all design decisions, identified risks, and the agreed forward roadmap from the 2026-05-15 review session.
>
> **Codebase verification pass (2026-05-16):** Findings below have been cross-checked against `src/`. Two items revised — see §4.2 (M01 scalar) and §4.3 (Phase 7 bottleneck).

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Doc Reconciliation: Methodology vs Manual](#2-doc-reconciliation-methodology-vs-manual)
3. [Architectural Review — What Works](#3-architectural-review--what-works)
4. [Architectural Risks & Decisions Made](#4-architectural-risks--decisions-made)
5. [Regime v2 — Merging M03 with the 5-Factor Risk Model](#5-regime-v2--merging-m03-with-the-5-factor-risk-model)
6. [ML Roadmap — M01 Variants](#6-ml-roadmap--m01-variants)
7. [Pipeline Automation & Quality Gates](#7-pipeline-automation--quality-gates)
8. [Pipeline Phase Restructuring](#8-pipeline-phase-restructuring)
9. [Model Evaluation Framework — "Prod-Ready" Definition](#9-model-evaluation-framework--prod-ready-definition)
10. [Dashboard Roadmap](#10-dashboard-roadmap)
11. [Infrastructure: Scheduling & Storage](#11-infrastructure-scheduling--storage)
12. [Consolidated Action List](#12-consolidated-action-list)

---

## 1. Executive Summary

The pipeline architecture is fundamentally sound: phase-based DAG with criticality flags, append-only event logs for universe and session tracking, and a clean T1→T2→T3 cascade that respects cross-sectional vs time-series feature requirements. The review identified:

- **8 doc inconsistencies** between methodology and manual (manual is source of truth).
- **2 P0 documentation fixes** (M01 score scalar mapping; table naming).
- **1 phase to drop** (Phase 7 training cache materialisation — view-only is fast enough).
- **1 new critical phase** (Phase 1.5 Quality Gate).
- **1 regime model rebuild** (z-score wide table merging M03 + 5-factor, with veto-based gating).
- **2 new model variants** (M01-Watch, M01-Hold) to cover the trade lifecycle.
- **5 dashboard pages** for Phase 2 expansion.

Infrastructure stays local for now — scheduler migration does **not** require cloud storage migration.

---

## 2. Doc Reconciliation: Methodology vs Manual

Manual (`docs/manual_for_me.md`) is the source of truth. Methodology should be updated against it.

| # | Topic | Methodology says | Manual says | Action | Status (2026-05-16) |
|---|---|---|---|---|---|
| 1 | Phase 1.3 table | `shares_history` | `shares_outstanding` (in Phase 1.3 process); `shares_history` only in key-tables list | Codebase confirms: table = `shares_history`, column = `shares_outstanding`. | ✅ FIXED — manual Phase 1.3 + ASCII flow now say `shares_history`. |
| 2 | T3 fundamentals JOIN target | `LEFT JOIN to fundamentals` | `LEFT JOIN to fundamental_features` | Codebase confirms `fundamental_features` (`view_manager.py:477`, `universe_scorer.py:414`). | ✅ FIXED — methodology §4.2 updated. |
| 3 | Phase 8 alerts | Generic mention | Manual lists 5 alerts incl. T2/T3 coverage gap | Add coverage-gap alerts to methodology §10/§11. | ⏳ pending |
| 4 | Coverage-aware recompute | Not mentioned | "<99% tickers present" / missing breakout tickers triggers recompute | Document this retry behavior in methodology Phase 3 / Phase 5. | ⏳ pending |
| 5 | M03 regime category thresholds | Names regimes 0-4, no thresholds | References `regime_cat 0-4 from m03_score thresholds` — also no values | Codebase **does** have them at `src/pipeline/m03_regime.py:88-93` (`strong_bull=80, bull=60, neutral=40, bear=20`). Doc-only fix. | ✅ FIXED — methodology §5 has threshold table; manual references defaults. |
| 6 | Helper Libraries section | Absent | Full table of importable libraries | Add to methodology. | ⏳ pending |
| 7 | Backtest runtime gate | Omits `ScoreLookup` | Lists `ScoreLookup` as in-memory O(1) daily filter | Document in methodology §9. | ⏳ pending |
| 8 | Tech debt vs operational TODOs | Mixed in §14 | Manual cleanly separates "Open TODOs" (operational) from "Resolved" | Split methodology §14 into Tech Debt vs Roadmap. | ⏳ pending |

---

## 3. Architectural Review — What Works

| Area | Why structurally sound |
|---|---|
| Phase-based DAG with criticality flags | Clear HALT semantics. Non-critical phases can fail without corrupting source-of-truth tables. |
| T2/T3 split | Correct axis: T2 holds cross-sectional features that need full universe; T3 holds expensive time-series features on a 10× smaller population. |
| Append-only event logs (`screener_membership`, `sepa_watchlist`) | Enables point-in-time replay; avoids destructive state. |
| `screener_criteria_versions` table | Decouples policy from data. |
| `t1_macro` vs `macro_data` separation | Two consumers, two schemas. Correct. |
| Ticker lifecycle as first-class concern | Deactivate / Rename / Purge / Blacklist as separate verbs across affected tables. |
| Model registry with status flag + feature_version | Enables reproducibility and rollback. |

---

## 4. Architectural Risks & Decisions Made

### 4.1 Universe forking — RESOLVED as design intent

The three universe gates (`company_profiles.is_active`, `screener_membership`, `sepa_watchlist`) are an intentional cascade, not a contradiction. T3 inclusion is **monotonic-additive**: once a ticker enters T3, it stays with full history regardless of current SEPA state.

**Action:** Add one sentence to methodology §3.2 — *"T3 inclusion is monotonic-additive (once in, always in); current investability requires re-checking `screener_membership.is_active` at query time."*

### 4.2 Backtest M01 scalar — CORRECTED 2026-05-16

⚠️ **Original claim was inaccurate.** The backtest does **not** rank on `predict_proba()[:, 3]`. Codebase verification (`src/backtest/universe_scorer.py:307-321`):

```python
midpoints = np.array([1.0, 6.0, 20.0, 40.0])              # per-class MFE % midpoints
calibrated_score = (predict_proba(X) * midpoints).sum(axis=1)  # expected MFE in %
prob_elite = predict_proba(X)[:, 3]                        # stored as diagnostic only
```

- **Ranking signal**: `calibrated_score` (probability-weighted expected MFE).
- **Diagnostic only**: `prob_elite = predict_proba()[:, 3]`.
- **Trailing window**: 10-day rolling-cohort percentile (`trailing_pct`); the default `rank_by='trailing'` controls candidate ordering.

**Action:** Methodology §9.2 has been updated with the correct mapping. The original review claim, if propagated, would have silently changed backtest candidate selection — still the highest-leverage doc fix in the review.

### 4.3 Drop Phase 7 (`d2_training_cache`) — PARTIALLY STALE 2026-05-16

⚠️ **The wall-time premise is no longer accurate.** The `sl_exits` correlated subquery was rewritten 2026-05-14 (see `docs/session_logs/2026-05-14.md`) using the `price_with_next` CTE with `LEAD(date) OVER (PARTITION BY ticker ORDER BY date)` — the exact pattern this review recommended. See `src/managers/view_manager.py:580-597`.

**Therefore:**
- The 592s figure for Phase 7 predates the fix. Re-time Phase 7 before deciding to drop it.
- The "drop Phase 7" recommendation may still hold on staleness/freshness grounds (a cache that lags v_d2_training is silently divergent), but the wall-time argument needs new evidence.
- The third bullet ("still rewrite `sl_exits`") is **already done** — remove from the action list.

**Revised decisions:**
- Re-measure Phase 7 wall time on current code.
- If new wall time is acceptable (< 60s), retain Phase 7 (the 70× read speedup is a real win for repeat trainer/ablation runs).
- If still slow, drop Phase 7 OR find the new bottleneck.
- Either way, document the trainer/backtest data source: cache vs view must be explicit.

### 4.4 Asymmetric entry/exit triggers — RECOMMENDED FIX

Entry uses full `trend_ok` (C1-C9). Exit uses C1+C2+C6 only. Asymmetry is invisible in schema and lives in a CTE misnamed `trend_c8`. High drift risk.

**Action:** Materialise `trend_exit_ok` as its own column in `t2_screener_features`. Entry filters on `trend_ok`; exit filters on `trend_exit_ok`. Self-documenting.

### 4.5 `sepa_watchlist.update_daily()` non-idempotent — TO REVISIT

Currently guarded only by `pipeline_runs`. Acceptable short-term; revisit after scheduler migration where retry semantics matter more.

**Action:** Either rewrite as `INSERT ... ON CONFLICT DO NOTHING` or elevate the guard to a hard pre-condition check in the orchestrator.

### 4.6 `screener_watchlist` vs `sepa_watchlist` naming — RECOMMENDED RENAME

Near-identical names force a "Distinction from..." subsection in the docs. Rename `screener_watchlist` → `trade_dashboard_mv` (it's a materialised view of trades, not a watchlist).

### 4.7 Time-asymmetric joins — TO AUDIT

- `company_profiles.sector / industry` are *current* values, used in *historical* T2 ranks (`RS_Sector_Rank`). Reclassifications silently rewrite history on next backfill.
- Verify `v_d2_features` joins fundamentals on `filing_date`, not `period_end`.

**Action:** Add invariant audits (see §9 below).

---

## 5. Regime v2 — Merging M03 with the 5-Factor Risk Model

### 5.1 Problem
- M03 collapses Trend / Liquidity / Risk into a single scalar `m03_score`. Information loss at the gate.
- 5-factor risk model uses z-score normalization (the right format for combining heterogeneous signals).
- Backtest currently maps `m03_score → regime_cat 0-4` for entry gating + position sizing — equal-weighted vote across pillars by construction.

### 5.2 Proposed Architecture

```
                 ┌── Trend (M03 pillar — breadth)        ──┐
                 ├── Liquidity (M03 pillar — credit)      ──┤
Raw signals  ───▶├── Risk (M03 pillar — VIX driven)      ──┤  z-score    composite
                 ├── Factor 1..5 (5-factor model)         ──┤  per signal──▶  pillar
                 │                                            (rolling window)
                 │
                 └──▶  Per-pillar veto rules
                         (e.g. Risk_z < -2 ⇒ Strong Bear regardless)
```

### 5.3 Concrete Recommendations

1. **Wide z-score table** `t2_regime_signals` — one row per date, one column per raw signal as z-score. No premature aggregation.
2. **Two consumers downstream:**
   - **Regime category (gating)**: rule-based on z-scores with veto semantics. Example: `Strong Bear if (Risk_z < -2 OR Trend_z < -1.5)`.
   - **Position sizing scalar**: weighted z-score sum, separate from gating.
3. **Preserve unique M03 elements:**
   - **Breadth indicators** (rare in pure factor models, valuable for SEPA).
   - **Credit spreads** (leading indicator; complements VIX which is coincident).
   - **5d/20d delta of regime** — momentum-of-regime is itself predictive; keep as M01 features.
4. **Backwards compat:** keep `m03_score` as a derived view for one release cycle.

### 5.4 Z-Score Lookback Window — Critical Design Decision

**User question:** *"If we keep a 5-year rolling window, does the z-score lose memory of GFC? How do we know what happened in 2008 today?"*

**Answer:** Yes — a pure rolling 5y window forgets GFC, COVID, and any regime that fell out of scope. This is a real problem for tail-risk gating. Three options:

| Option | Description | Pro | Con |
|---|---|---|---|
| **A. Pure rolling N-year** (typical) | μ, σ from last 5y only | Adaptive to recent regimes | Forgets crises; z-scores compress during long calm periods (2017 VIX would look "normal" by 2022 standards) |
| **B. Expanding window** | μ, σ computed from inception (2000) to t-1 | Memory of all regimes preserved | Slow to adapt; Lehman + COVID fixed forever in baseline |
| **C. Hybrid (recommended)** | μ from rolling 5y (adapts), σ from full history (preserves tail memory) | Mean adapts to recent normal; tail magnitude preserved | Slightly non-standard; needs documenting |

**Recommended: Option C with a twist.** Use **expanding-window μ and σ from a fixed start date (e.g., 1998-01-01) as the "crisis-aware" baseline**, AND a parallel rolling-5y z-score as the "recent-regime" view. Store both. Use:
- **Expanding-window z-score** for *gating* (veto rules trigger on tail events relative to all history).
- **Rolling-window z-score** for *position sizing* (responsive to current regime).

This way, today's VIX of 25 is "moderately elevated by 2024 standards" (rolling) AND "well below GFC peak" (expanding). The dashboard shows both. The gating logic uses the expanding view so a Lehman-class shock still triggers a Strong Bear veto even after a long bull run.

**Implementation:** The wide table stores both `*_z_rolling5y` and `*_z_expanding` columns per signal. Cheap to compute, cheap to store. New signals added later use the same convention.

### 5.5 Action

Draft `docs/regime_v2_design.md` with the wide table schema, signal list (M03 pillars + 5-factor inputs), the dual z-score convention, and the veto rule set.

---

## 6. ML Roadmap — M01 Variants

Currently M01 answers only one question: *"Given a breakout today, will it deliver high MFE?"* That covers entry quality. Two more questions matter:

| Model | Question | Trigger Population | Label | Purpose |
|---|---|---|---|---|
| **M01-Setup** *(current)* | Given breakout today, will MFE be high? | `trend_ok ∧ breakout_ok` | 4-class MFE | Entry sizing |
| **M01-Watch** *(new)* | Given trend_ok today, will breakout occur within 5d? | `trend_ok ∧ ¬breakout_ok` | Binary or 3-class (no/soft/strong breakout in window) | Pre-position scanner / alerts |
| **M01-Hold** *(new)* | Given open position day N, has setup degraded? | Open `sepa_watchlist` sessions | Binary (SL hit within K days?) or regression on remaining MFE | Active management / discretionary exit |

### Recommendations
- All three train on the **same** `t3_sepa_features` table with different filter cuts. No schema changes.
- Add a `model_role` column to `models` registry (`SETUP` / `WATCH` / `HOLD`) so dashboard can pick the right model per ticker state.
- Don't overengineer as one multi-task model — different populations, different label noise, different deployment cadences.

---

## 7. Pipeline Automation & Quality Gates

### 7.1 Current Pain Points
- yfinance implicit rate limits → manual two-pass execution to achieve full T1 coverage.
- Audits are CLI-only, run after the fact, do not block downstream phases.
- Logs are line-based, hard to query.
- No structured retry semantics.

### 7.2 audit_t1_data_quality — Complete Check List

Every check that lives in `tools/audit_t1_data_quality.py`, grouped by section:

**1. Coverage**
- `company_profiles_tickers` — total tickers in universe seed (INFO)
- `{table}_coverage_pct` — % of CP tickers present in price_data / shares_history / fundamentals (WARN if <80% / <60% / <60%)
- `{table}_missing_from_cp` — active CP tickers with NO rows in downstream tables (WARN if >0)
- `{table}_orphan_tickers` — tickers in downstream table NOT in CP (warrants/preferred/rights → INFO; regular equities → WARN)

**2. Freshness**
- `price_data_max_date` — days since latest price row (WARN if >5 calendar days)
- `price_data_stale_tickers` — active tickers with no data in last 5 days (WARN if >5% of universe)
- `shares_history_max_date` — days since latest shares row (WARN if >30 days)
- `fundamentals_max_period_end` — latest period_end (WARN if older than 120 days ago)
- `fundamentals_future_period_end` — rows with period_end > today (WARN if >0)

**3. Fundamentals Completeness**
- `null_pct_{col}` for 13 key columns: `total_revenue`, `net_income`, `gross_profit`, `operating_income`, `ebit`, `ebitda`, `total_assets`, `stockholders_equity`, `operating_cash_flow`, `free_cash_flow`, `basic_eps`, `diluted_eps`, `filing_date` (WARN >15%, FAIL >50%)
- `source_{source}` — row/ticker counts per data source (INFO)
- `sparse_tickers_lt4_periods` — tickers with <4 quarterly periods (WARN if >10%)
- `avg_periods_per_ticker` — average periods per ticker (INFO)

**4. Price Data Integrity**
- `duplicate_ticker_date` — duplicate `(ticker, date)` keys (FAIL if >0)
- `null_or_zero_close` — NULL or non-positive close (FAIL if >0)
- `zero_volume_rows` — volume=0 rows (WARN if >1%)
- `extreme_price_moves_gt200pct` — single-day >200% moves (WARN if >100 rows)
- `extreme_movers_top20` — top 20 tickers by extreme move count (INFO)
- `tickers_with_gaps` — active tickers with >20% fewer rows than SPY in their date range (FAIL if >0)
- `gap_tickers_top20` — top gap tickers vs SPY (INFO)

**4b. Filing Date Integrity**
- `null_filing_date` — % rows missing filing_date (WARN if >30%)
- `filing_before_period_end` — filing_date < period_end (FAIL if >0)
- `filing_lt_30d_after_period` — filed <30 days after period_end (WARN if >0)
- `filing_gt_90d_after_period` — filed >90 days after period_end (WARN if >0)

**5. Macro Data (`t1_macro`) Integrity**
- `table_exists` — t1_macro table present (FAIL if missing)
- `max_date` — days since latest t1_macro row (WARN if >5 days)
- `null_{spy_close|qqq_close|vix_close}` — NULL critical columns (FAIL if >0)
- `date_gaps_vs_price_data` — trading days in price_data missing from t1_macro (FAIL if unexpected; INFO for known closures)

**6. Shares History Integrity**
- `duplicate_ticker_date` — duplicate `(ticker, date)` keys (FAIL if >0)
- `null_or_zero_shares` — NULL or non-positive shares_outstanding (WARN if >1%)

**Thresholds (defaults):**
```python
STALE_PRICE_DAYS = 5
STALE_SHARES_DAYS = 30
FUNDAMENTAL_NULL_WARN_PCT = 15.0
FUNDAMENTAL_NULL_FAIL_PCT = 50.0
MIN_PRICE_COVERAGE_PCT = 80.0
MIN_SHARES_COVERAGE_PCT = 60.0
MIN_FUND_COVERAGE_PCT = 60.0
```

### 7.3 Recommendations

1. **Self-healing T1.** Replace manual two-pass with: ingest → audit coverage → if <95% retry stale subset → audit again → if still <95% alert. Loop lives in orchestrator.
2. **Promote audits into the DAG (Phase 1.5 — see §8).** Auto-run `audit_t1_data_quality`; HALT on FAIL. Audits should block, not log.
3. **Fundamentals query check** belongs in Phase 1.5 — verify EPS / revenue null rates within bounds before Phase 3.
4. **Structured logging.** Move to JSON one-event-per-phase with `phase`, `duration_s`, `rows_in`, `rows_out`, `coverage_pct`, `warnings[]`. Dashboard can then query log stream.
5. **Scheduler.** `apscheduler` (in-process) or `prefect` (separate daemon, retry semantics, alerts). See §11.

---

## 8. Pipeline Phase Restructuring

### 8.1 Proposed Restructure

```
Phase 1 — T1 Ingestion (CRITICAL)
   ↓
Phase 1.5 — T1 Quality Gate (CRITICAL, NEW)
   ↓
Phase 2 — Screener Membership (CRITICAL)
   ↓
Phase 3 — T2 Features (CRITICAL)
   ↓
   ├── Phase 4  — Regime Scores (non-crit)   ┐ run in parallel
   └── Phase 4b — SEPA Watchlist (CRITICAL)  ┘
   ↓
Phase 5 — T3 Features (CRITICAL)
   ↓
Phase 6 — Views (non-crit)        ← Phase 7 dropped
   ↓
Phase 8 — Monitoring (always)
```

### 8.2 Changes Summary
- **Add Phase 1.5 Quality Gate** — auto-runs `audit_t1_data_quality.py` + fundamentals null check; FAIL halts pipeline.
- **Drop Phase 7** — `d2_training_cache` materialisation eliminated; trainer reads `v_d2_training` directly.
- **Phase 4 ∥ Phase 4b** — they have no dependency on each other; document and execute concurrently.

Net result: 8 phases → 8 phases (one added, one dropped), faster, with explicit quality gating.

---

## 9. Model Evaluation Framework — "Prod-Ready" Definition

A model is prod-ready when it passes **6 dimensions** of validation:

| Dimension | Question | Current | Gap |
|---|---|---|---|
| **Statistical fit** | Accuracy / F1 / calibration on holdout? | ✅ `ClassificationEvaluator` | none |
| **Temporal robustness** | Does performance hold on recent vs old data? | ⚠️ Single chronological split | Add **walk-forward CV** with N folds; report metrics per fold |
| **Regime conditional** | Does it work in bear / crisis periods? | ❌ | Slice metrics by `m03_regime_cat`; per-regime confusion matrix |
| **Economic value** | Does class-3 selection generate alpha after costs? | ⚠️ Backtest exists but not gated to promotion | Sharpe / max DD / hit-rate as part of promotion criteria |
| **Stability over time** | Do feature importances drift? Prediction distribution shift? | ❌ | **PSI (Population Stability Index)** on prediction distribution + top-10 features (train vs last-90d) |
| **Failure mode catalog** | What inputs make it wrong? | ❌ | Slice errors by sector / market cap / volatility / holding period; produce a "weakness card" |

### 9.1 `model_validation_report.md` Template (per model)

```
1. Headline metrics
2. Walk-forward CV: 5-fold rolling, last 5 years
3. Regime-conditional: precision/recall per regime_cat
4. Backtest: Sharpe, MDD, win rate, profit factor, regime breakdown
5. Stability:
   - PSI on top-10 features train vs last-90d
   - Prediction distribution drift chart
6. Weakness card:
   - Worst-performing sectors (top 3)
   - Worst-performing market cap buckets
   - Failure examples (5 trades model said class 3, got class 0)
7. Calibration: reliability diagram per class
8. SHAP: stability of top features across folds
9. Promotion checklist (gating rules):
   ☐ Walk-forward macro F1 > 0.25
   ☐ No regime where precision drops > 30% vs overall
   ☐ Backtest Sharpe > 0.8 in last 3 years
   ☐ Top-feature PSI < 0.2
   ☐ Manual review signed off
```

### 9.2 Promotion Gating
Tie this to `ModelRegistry.set_prod()` — should **refuse** if the report's promotion checklist isn't all green. Mechanically enforced, not vibes-based.

### 9.3 Invariant-Based Audits (additions to existing threshold audits)

- For every `(ticker, date)` in `t3_sepa_features`, that ticker had an open `sepa_watchlist` session at some point.
- For every active `sepa_watchlist` session, the ticker was in `screener_membership` on `entry_date`.
- No `t3_sepa_features` row exists for a date earlier than the ticker's first `price_data` row.
- `v_d2_features` joins fundamentals on `filing_date`, not `period_end`.

---

## 10. Dashboard Roadmap

Current single-pager is the right MVP. Phase 2 expansion uses Streamlit's multipage feature.

| Page | Purpose | Data Source | Key Visualisations |
|---|---|---|---|
| **1. Live Signal** *(current)* | What should I look at today? | `screener_watchlist`, `t2_regime_scores`, M01 inference | Active trades, regime header, M01 class distribution |
| **2. Pipeline Health** *(NEW — high priority)* | Did today's pipeline run cleanly? | `pipeline_runs`, audit reports, structured logs | Phase status timeline, coverage % per table, alerts feed, freshness gauges |
| **3. Ticker Deep Dive** *(NEW — high value)* | Why is ticker X scored Y? | `t3_sepa_features`, M01 SHAP, `ScreenerDiagnostics` | Per-day C1-C9 / B1-B2 matrix, feature time series, SHAP waterfall |
| **4. Model Lab** *(NEW)* | How is M01 performing? Should I retrain? | `models` registry, evaluation artifacts | Live precision/recall by regime, prediction drift, feature importance evolution, model diff |
| **5. Backtest Studio** *(NEW)* | How does the strategy hold up historically? | `data/backtest/`, regime data | Equity curve vs SPY, regime-conditional returns, trade explorer, drawdown |

### Build Order
1. Pipeline Health (operational visibility — needed before unattended scheduling).
2. Ticker Deep Dive (interpretability — manual sanity check before any trade).
3. Model Lab.
4. Backtest Studio.

---

## 11. Infrastructure: Scheduling & Storage

### 11.1 User Question: *"Once we move to a scheduler, do we also need to move data to cloud?"*

**Answer: No. They are independent decisions.**

### 11.2 Scheduling Options (local stays viable)

| Option | Where data lives | When it makes sense |
|---|---|---|
| **Windows Task Scheduler** | Local DuckDB | Solo, single machine, low ops overhead |
| **`apscheduler` daemon** | Local DuckDB | Want retry / cron in Python without OS dependency |
| **Prefect / Dagster (local)** | Local DuckDB | Want DAG visualisation, retry, alerting, structured run history |
| **Prefect / Dagster (cloud agent)** | Local DuckDB, scheduler in cloud | Want UI + alerts without running a daemon at home |

The scheduler only needs to *invoke* the pipeline. The pipeline can read/write a local DuckDB file regardless of where the scheduler runs. SSH/agent setups make this straightforward.

### 11.3 When to Move Data to Cloud (separate triggers)

You only need to migrate storage when **one or more** of these become true:

| Trigger | Symptom | Migration target |
|---|---|---|
| Multiple consumers / collaborators | More than one person needs read access; concurrent connection conflicts | DuckDB → MotherDuck / Postgres / cloud Parquet on S3+Athena |
| Compute exceeds local hardware | T3 backfill > 4h; can't fit feature matrix in RAM | Cloud VM (still local DuckDB on bigger box) or distributed (BigQuery / Snowflake) |
| Need 24/7 dashboard | Streamlit must serve when laptop is off | Cloud-hosted DB + cloud-hosted Streamlit (Streamlit Cloud, ECS) |
| Disaster recovery | Loss of laptop = loss of years of features | Cheapest: nightly DuckDB file backup to S3 / OneDrive. Doesn't require migrating compute. |
| Data > 100GB | DuckDB local file unwieldy; backups slow | Cloud object storage + columnar format |

### 11.4 Recommended Path

**Phase A (now → 6 months):** Stay local. Add Prefect (local) + nightly DuckDB file backup to OneDrive/S3. Get scheduling + DR for ~$0.

**Phase B (when collaborator joins or you want 24/7 dashboard):** MotherDuck (managed DuckDB, minimal code change — same SQL, just a different connection string). Streamlit Cloud points at MotherDuck.

**Phase C (only if T3 grows >50M rows or you need distributed compute):** BigQuery / Snowflake migration. Likely never needed for this scope.

The key insight: **DuckDB scales remarkably far on a single machine.** ~10M-row T3 with 144 columns is well within local-laptop territory. Don't migrate prematurely — the operational cost (network latency, auth, billing surprises) outweighs the benefits until you have a forcing function.

---

## 12. Consolidated Action List

| Priority | Action | Effort | Section | Status |
|---|---|---|---|---|
| P0 | Document M01 score = `calibrated_score = Σ proba × [1,6,20,40]` (NOT `proba[:, 3]`) + 10d trailing percentile | 1 line | §4.2 | ✅ DONE 2026-05-16 |
| P0 | Reconcile `shares_history` (table) vs `shares_outstanding` (column) across both docs | 30 min | §2 | ✅ DONE 2026-05-16 |
| P0 | Methodology §4.2: change fundamentals JOIN target to `fundamental_features` | 1 line | §2 | ✅ DONE 2026-05-16 |
| P0 | Document `m03_score → regime_cat` thresholds (currently undocumented in **docs only** — code config has them) | 1 hr | §2 | ✅ DONE 2026-05-16 |
| P1 | Re-time Phase 7; decide drop vs retain based on current wall time (correlated subquery already fixed 2026-05-14) | 1 hr measure + half day action | §4.3 | ✅ DONE 2026-05-16 — avg 58.8s; keep Phase 7 |
| P1 | Materialise `trend_exit_ok` column in T2; refactor exit logic to use it | half day | §4.4 | ⏳ pending |
| ~~P1~~ | ~~Rewrite `sl_exits` correlated subquery to `LEAD(date)` pattern~~ | ~~half day~~ | ~~§4.3~~ | ✅ DONE 2026-05-14 (session log) |
| P1 | Add Phase 1.5 Quality Gate; auto-retry T1 on coverage shortfall | 1-2 days | §7, §8 | ⏳ pending |
| P1 | Draft `docs/regime_v2_design.md` — wide z-score table, dual rolling/expanding lookback, veto rules | 1-2 days | §5 | ⏳ pending |
| P2 | Add invariant-based audits (universe contract checks) | 1 day | §9.3 | ⏳ pending |
| P2 | Rename `screener_watchlist` → `trade_dashboard_mv` | half day | §4.6 | ⏳ pending |
| P2 | Add M01-Watch and M01-Hold variants; add `model_role` column to registry | 1-2 weeks | §6 | ⏳ pending |
| P2 | Build `model_validation_report.md` template + promotion gating in `set_prod()` | 1 week | §9 | ⏳ pending |
| P2 | Migrate to structured JSON logging | 2-3 days | §7 | ⏳ pending |
| P3 | Streamlit multi-page: Pipeline Health → Ticker Deep Dive → Model Lab → Backtest Studio | 2-3 weeks | §10 | ⏳ pending |
| P3 | Migrate idempotency of `sepa_watchlist.update_daily()` to ON CONFLICT | half day | §4.5 | ⏳ pending |
| P3 | Add nightly DuckDB backup to OneDrive/S3 | 2 hr | §11 | ⏳ pending |
| P3 | Adopt Prefect (local) for scheduling | 1-2 days | §11 | ⏳ pending |
| P3 (doc) | Backfill methodology with sections #3, #4, #6, #7, #8 from §2 table (coverage alerts, coverage-aware recompute, Helper Libraries, ScoreLookup, tech-debt/roadmap split) | half day | §2 | ⏳ pending |

---

## Appendix: Open Questions for Future Sessions

1. **M03 → regime_cat thresholds:** What are the actual cutoffs? Need to be made explicit in code and documented.
2. **5-factor model details:** What are the 5 factors? Need full enumeration before merging into Regime v2.
3. **`v_d2_features` fundamentals JOIN key:** Verify whether it uses `filing_date` (correct) or `period_end` (leakage risk).
4. **Sector reclassification policy:** Snapshot sector/industry per date, or accept current-state-only? Affects historical XS rank stability.
5. **Backtest cost model:** Is slippage / commission baked in? Needed to validate "economic value" promotion criterion.

