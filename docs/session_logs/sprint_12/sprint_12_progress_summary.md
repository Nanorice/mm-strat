# Sprint 12 Progress Summary

*Based on handover notes, todo.md, and sprint_12_plan.md as of June 20, 2026.*

## ✅ What's Done

### 1. Model Evaluation & Selection (Phase 1 & 2)
- **Continuous Scoring:** Rebuilt the evaluation framework from discrete pass/fail bands into a continuous 100-point rubric, with business-implication verdicts (OK, WARNING, LIMITATION).
- **Full History Grid Comparison:** Evaluated 4 model variants (Binary vs 4-Class, Calibrated vs Uncalibrated) over the massive 21-year dataset (2001-2026).
- **Model Selection:** Successfully identified `m01_binary/v1 (Calibrated)` as the superior architecture (0.807 AUC, 0.02 ECE, 87% precision at T=0.6).

### 2. Dashboard Infra & UX
- **Slim Dashboard DB:** Carved a 783MB slim DB out of the 72GB main database (98% reduction) for efficient remote hosting.
- **Watchlist Activity:** Built the "Activity feed" and "Ticker history" tabs to track universe flips and exit events.
- **Data Flow Diagrams:** Embedded interactive Mermaid architecture diagrams directly into Page 5 via native Tabs.
- **Visuals:** Added Finviz hyperlink integrations and macro/5F history charts to the Today page.
- **Dashboard UI & Data Fixes:** Fixed UI flicker by localizing window controls, added Entry P(HR) to ticker history, and eliminated stale scores for active names.
- **Daily Rank Bump Chart:** Built the interactive cohort bump chart on the Today page using `daily_predictions.rank_within_day`, natively handling isolated days vs. contiguous streaks.

### 3. Pipeline Infrastructure & Data Integrity
- **View Cleanup:** Deleted dead alias `v_d1_trades`, retired `v_d2r_hydrated`, and established strict local vs remote DB parity contracts.
- **Phase-Key Registry:** Replaced the fragile positional phase IDs in the daily orchestrator with a stable-id phase registry (preventing phase renumbering bugs).
- **T3 Hole Bug Fixed:** Diagnosed a silent `INNER JOIN` trade-drop bug in `v_d1_candidates`. Fixed via self-healing pipeline checks, LEFT-JOIN guards, and a 12-quarter history backfill.

### 4. Parallel Scoring / Shadow Deployment (Phase 3)
- **Model Registry:** Extended to support setting a `status_flag='shadow'` model alongside the prod model.
- **Scoring Pipeline:** `ScoreEngine` and Orchestrator Phase 7.4 updated to score the shadow model nightly on the breakout cohort and write to a `shadow_divergence` verdict table.
- **Comparison Tooling:** Built `scripts/compare_shadow.py` to run historical rank-difference reports without needing to maintain parallel views.

### 5. Lifecycle-Tagged Daily Scoring (2026-06-19)
- **Structural fix:** Replaced the non-MECE status-gated Phase 7.4 split with **one** lifecycle-tagged scoring pass over `v_d3_lifecycle`. The held population is now re-scored daily and has genuine per-day rank history.
- **Carry-forward deleted:** `load_scored_watchlist` now joins strictly same-day (`prediction_date = price_date`).
- **Pipeline completeness:** Extended the t3 self-heal to force-materialize ACTIVE + recently-EXITED watchlist names. Backfilled 120,515 rows.

### 6. Remote Sync Automation (S4)
- **Fix:** Anchored `load_dotenv()` to the project root so it works regardless of CWD.
- **Automation:** Created `run_nightly_pipeline.ps1` and `register_nightly_task.ps1` to schedule the pipeline daily at 06:00 via Windows Task Scheduler.
- **Verified:** Real R2 upload succeeds unattended from Task Scheduler.

### 7. V2 Regression Model (m02) Spike
- **Infrastructure Built:** Created `m02_prototype_targets` (16.1M rows, forward 21d MFE/MAE/return targets), `t3_training_cache` table for fast training loads, and a strict Purged/Embargoed Time-Series CV framework (`m02_cv.py`).
- **Conclusive Diagnostic:** Trained 6 variants across a 5-year sweep. Discovered that the model's apparent edge in predicting MFE/MAE levels was entirely a mathematical artifact of the quantile loss function acting on volatility, not true predictive skill. Furthermore, its P50 directional return ranking failed to beat a raw volatility baseline in the recent 5 years.
- **Outcome:** Spike closed. The model is retired as a ranker. The hypothesis that "quantile predictions = skilled Take Profit / Stop Loss levels" was disproven. The ultimate test (calibrated vol bands vs. standard ATR multiples) has been deferred to a new unified "Strategy Arena" backtest goal.

---

## ⏳ What's Left (Sprint 13 Carry-over)

### 1. Unattended Runner + Spare-PC Builder (S4-FollowUp)
- **Deliverable 1 — Unattended (logged-off) runner:** Re-register the task with the **S4U** logon type from an elevated PowerShell so it runs even if logged off.
- **Deliverable 2 — Spare-PC builder migration:** Decide whether the nightly builder runs on the current dev box or the spare PC. If spare PC: migrate the DB, set up venv/R2 creds, and register the task there.

### 2. Strategy Arena Backtest (m02 Follow-up)
- **Goal:** Run the SEPA rule-based exits, standard $k \times ATR$ bands, and the m02 calibrated vol-bands through the same `walk_forward_backtest.py` harness using a Sharpe ratio gate. This is the definitive test to settle the exit policy and fully wrap up the m02 investigation.

### 3. P2 Backlog
- **Stale-ACTIVE Eviction:** Stale-price held names score NULL in lifecycle scoring but stay ACTIVE forever. Surface a ready-to-run deactivation prompt in the Pipeline Health page, gated on days-since-last-bar + error type.
- **Score Trajectory (Mode B):** Analyze daily prediction correlations with forward returns.
- **Feature Drift:** Finalize quarterly PSI reporting.

### 4. Documentation (T4)
- Refresh `docs/comprehensive_methodology.md` to document the new continuous model evaluation framework.
- Consolidate manual runbooks into `docs/manual_for_me.md`.