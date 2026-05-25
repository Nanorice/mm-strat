# Quantamental SEPA Framework — Path-Forward White Paper

> **Created:** 2026-05-23
> **Owner:** Hang
> **Status:** Draft for review. This is intended as the **guiding document** for the
> next 1–2 quarters of work, sitting above the per-sprint plans in `docs/plans/`.
> **Companion documents:** [`docs/manual_for_me.md`](../manual_for_me.md) (operational
> truth), [`docs/comprehensive_methodology.md`](../comprehensive_methodology.md)
> (replication spec), [`docs/session_logs/2026-05-22_backtest-cases.md`](../session_logs/2026-05-22_backtest-cases.md)
> (the m01_rank verdict that motivates this paper).

---

## 0. TL;DR — Where we are, what we now believe, what we do next

**Where we are.** The data engineering layer is complete and trustworthy: T1 → T2 →
sepa_watchlist → T3 → views → training cache → model registry → BackTrader
backtester. The production breakout-selection model **m01_prototype** has been
verified on a clean, dense, daily-scored backtest (Case 1, 2020–2024:
**+201%, Sharpe 0.79, max DD −26%**, positive in 4/5 years).

**What we now believe (the m01_rank verdict, 2026-05-22).** The two-model thesis —
"prototype selects, rank times" — failed at the timing step. Both Case 1 and
Case 2 already score *daily and densely*; the only thing Case 2 changed was the
entry-ranking key (m01_rank's daily percentile). It hurt: **+65%, Sharpe 0.39,
max DD −42%**. The skill validation showed m01_rank's per-name forward-return IC
is real (0.07/0.10/0.13 @ 5/10/20d), but its 1d/5d/10d/20d scores are 0.92–0.99
correlated — it is a **single horizon-invariant "setup-quality" score, not a
timing instrument.** You cannot derive "when to enter" from a model whose
short- and long-horizon outputs are nearly identical.

**What this means for the system.** The current selection model already harvests
the available signal. The next gains do **not** come from layering a second ML
model on top of it. They come from (i) **giving the selection model better
information** (regime, microstructure, fundamentals, post-breakout state),
(ii) **execution discipline** (the 3-tranche exit, position sizing, regime
gating), and (iii) **closing the loop** between the live screener, the
dashboard, and the trade log so we can actually run the strategy.

**The path forward, in priority order:**

1. **Ship m01_prototype standalone as the production signal.** Daily-dense scoring
   via `score_from_t3` + SEPAHybridV1. This is no longer experimental.
2. **Treat timing as a *price-action* problem, not an ML problem** — for now.
   Pullback-entry, exit-on-trend-break, and ATR stops are deterministic rules
   that the backtest already implements. Don't try to predict timing with a
   sibling model; the m01_rank work proved the score-based approach hits a
   ceiling.
3. **Invest in evaluation rigour, not in new models.** Walk-forward CV,
   regime-conditional metrics, calibration audits, feature-stability tests,
   transaction-cost-realistic backtests. We don't yet know how *good* the
   prototype really is — we have one clean backtest, not a body of evidence.
4. **Build out the live operational layer.** Daily dashboard, sector-rotation
   heatmap, paper-trading log, alerting. Most of the value of a quant system is
   in *operating* it, not in *building* it.
5. **Only then revisit modelling.** Targeted experiments: binary-collapse
   variant, regime-conditional model, microstructure / post-breakout features,
   and an explicit **exit-classifier** (M01-Hold) — which is a different problem
   from rank-style timing and *is* well-posed.

This paper expands each of the five sections below, with vision, scope, and
acceptance criteria.

---

## 1. Vision

The Quantamental SEPA Framework is a **systematic, reproducible
implementation of Minervini's SEPA methodology** with three operating principles:

1. **Selection is a classification problem; timing and risk are rules.** Trying
   to ML-ify everything has a clear failure mode (the m01_rank result). Use ML
   where it dominates rules — pattern recognition on cross-sectional
   feature panels — and use rules where they dominate ML — stop-losses, profit
   tranches, regime gating, position sizing.
2. **The data layer is the moat.** A clean, auditable, point-in-time-correct,
   survivorship-bias-mitigated panel of ~3K US equities going back ~25 years
   is more valuable than any single model. Every feature, every label, every
   trade is reproducible from raw inputs. We protect this asset above all else.
3. **Honest evaluation beats high backtest numbers.** A leakage-clean Sharpe of
   0.8 across a regime cycle is worth more than a backtested Sharpe of 2.0 that
   doesn't replicate. We learned this twice already (the m01_rank 28× and the
   adj_close NULL artifact). Every metric is suspect until it survives
   walk-forward, leakage audit, and a regime-conditional breakdown.

**One-line product description.** A locally-hosted system that screens the US
equity universe each evening, ranks SEPA breakout candidates by expected MFE,
gates entries by a regime model, sizes positions by conviction, exits by ATR
tranches and trend break, and surfaces it all through a Streamlit dashboard
with a daily watchlist and trade log.

**Out of scope (explicitly).** Intraday execution, high-frequency anything,
non-US equities, futures/options, fully-automated brokerage integration,
multi-strategy portfolio management. The framework is a **decision-support
system** for a single discretionary trader operating on a daily cadence.

---

## 2. Where the modelling work goes next

### 2.1 Is `m01_prototype` good enough?

**Yes, for now — and the burden of proof has now shifted to evaluation rather
than to a sibling model.**

What we know:
- **Top-K lift is real.** The model meaningfully separates Home Run (>30%) from
  Noise (≤2%) at K=10, 50, 100. ROC-AUC for the Home Run class is 0.693. Class 3
  probability is the directional bet.
- **The score is structural, not horizon-specific.** Score IC vs forward return
  is positive at 5d, 20d, 60d (peak 20d, IC=0.059, t≈10.5). The score captures
  *setup quality* — a property of the name today — not a horizon-specific
  forecast.
- **The score has *no* edge at the 1-day horizon** (IC = −0.014, mean reversion
  on breakout day). This is *good news* — it tells us to enter after a
  pullback, not at breakout-day close.
- **Real-money backtest passes the smell test** (Case 1, 2020–2024: +201%,
  Sharpe 0.79, max DD −26%, positive 4/5 years). Importantly, the worst year is
  2022 at −9% — survivable.

What we don't yet know:
- How does it perform **out-of-sample beyond 2024**? The dense backtest stops
  there. The first walk-forward fold past the training cutoff is missing.
- How does it behave under **transaction costs and realistic slippage** for the
  ~1–3K trade backtest? The Case 1 numbers do not amortize entry/exit costs at
  trade-level granularity. A 10bp roundtrip on 1,500 trades is ~15% drag.
- **Calibration.** The class-3 probabilities range only to 0.83. Are the
  probabilities calibrated against realized rates, or does the model under-call
  rare events? Reliability diagrams not yet produced for the dense-backtest
  population.
- **Regime decomposition.** We have year-level breakdowns (positive 4/5 years).
  We do **not** have regime-conditional metrics (Strong Bull / Bull / Neutral /
  Bear / Strong Bear). The 2022 −9% result is interesting precisely because it
  was a sustained Bear regime — but we haven't decomposed *which* trades in
  that year worked vs failed.
- **Feature drift.** The model trains on 2003–2024. We don't yet have a
  drift-detection regime — population stability index (PSI), feature
  distribution shift, etc. Section 5 picks this up.

**Verdict.** Ship it, but treat the next quarter as an evaluation push, not a
re-modelling push.

### 2.2 Do we develop a new model for breakout detection?

**Revised 2026-05-23 (user pushback):** the original draft argued *no*. The user
correctly pushed back that **we have the data, the question is well-defined, and
the cost is low**. Revised position: **yes — build a pre-breakout classifier as
a contained experiment, with explicit success criteria that protect against the
m01_rank failure mode.**

#### 2.2.1 What this model actually predicts (M01-Watch)

**Question.** *Given a ticker with `trend_ok = TRUE` and `breakout_ok = FALSE`
today, what is the probability it triggers `breakout_ok = TRUE` within the next
N trading days (N ∈ {3, 5, 10})?*

This is a **horizon-specific binary classification** on a well-defined cohort.
Crucially, it is **structurally different from m01_rank**:

| | m01_rank (shelved) | M01-Watch (proposed) |
|---|---|---|
| Question | "good day to enter / hold / exit?" — timing on an already-selected name | "will this name break out in N days?" — a discrete future event |
| Target | future return at horizon H (continuous-ish) | binary `breakout_ok` flips to TRUE within N days |
| Failure mode it inherits | horizon-invariant score (1d ≈ 20d correlation 0.92) | none of the same kind — the event happens or doesn't at a definite future date |
| Cohort | dense panel (all SEPA-watchlist rows) | tightly filtered (`trend_ok=TRUE AND breakout_ok=FALSE` only — ~200–800 rows/day) |
| Use case | replace ranking on existing entry signal | pre-stage candidates 1–10 days before they hit the live screener |

The key insight: **m01_rank failed because future-return targets at different
horizons end up highly correlated in trending names.** M01-Watch's target is a
*discrete event* (breakout day), so the 3d / 5d / 10d variants will give
genuinely different precision/recall tradeoffs — the 3d model has to be wrong
about timing in a way the 10d model isn't.

#### 2.2.2 Substrate readiness

Everything needed already exists:
- **Cohort table.** `t2_screener_features WHERE trend_ok = TRUE AND breakout_ok = FALSE`
  is dense and pre-computed.
- **Labels.** Forward `breakout_ok` flips can be computed in one window function
  per ticker on the same table — no new data ingestion.
- **Features.** The same T2 + T3 feature set that m01_prototype uses (105
  features), plus optionally `days_in_watchlist` (the §1 development-roadmap
  feature, which becomes naturally informative here).
- **Training infra.** `train_mfe_classifier.py` can be reused with the new label
  column; the only changes are the SQL that produces the training table and
  the target column name.

**Estimated effort: 1–2 weeks** for an initial model (cohort SQL, label
generation, train, evaluate). Most of the cost is evaluation, not training.

#### 2.2.3 Acceptance criteria — designed to fail-fast if it's another rank-style trap

Before this work consumes more than one sprint, the model must clear these
gates:

1. **Per-horizon precision must differ meaningfully.** Train three models (N=3,
   N=5, N=10). At the same recall (say 0.50), their precisions must differ by
   more than 5 percentage points and their top-K candidate lists must differ in
   composition. If the three models produce nearly the same ranking
   (Spearman > 0.9 across horizons), kill it — we hit the m01_rank ceiling.
2. **It must beat the obvious baseline.** Baseline: "rank by how close
   `breakout_ok` was to firing yesterday" — i.e., a hand-built score on
   `dist_from_20d_high`, `vol_ratio`, `vcp_ratio`. Model must beat this baseline
   on top-20-precision by ≥ 10% relative.
3. **Top-K must be small.** At a useful precision (say 0.30 on 5-day breakout
   prediction), the daily top-K must be < 30 names. Otherwise the "pre-stage
   ahead of breakout" use case doesn't apply — you can't usefully watch 300
   names.
4. **Survive walk-forward.** Same protocol as m01_prototype (§5.1). Worst-fold
   precision > 0.20 at recall 0.50.

If it passes all four, it lives in the dashboard as the **Watchlist** page —
names with `trend_ok=TRUE AND breakout_ok=FALSE`, ranked by M01-Watch
probability, with the corresponding M01 (post-breakout MFE) score shown
alongside so you can see both signals.

If it fails any of the four, we've learned something concrete about *why* and
the substrate work is reusable for the next iteration. This is a low-risk
experiment, not a multi-sprint commitment.

#### 2.2.4 The deterministic baseline still matters

Whether or not the model ships, **the dashboard should show the
`trend_ok=TRUE AND breakout_ok=FALSE` cohort with the M01 (post-breakout)
score**. This is a free UI feature — the data is there in `v_d3_deployment` —
and gives the same operational benefit (see names before they break out)
without any new model. M01-Watch's job is to *rank within* that cohort better
than the M01 score alone, which is a higher bar than just surfacing the cohort.

### 2.3 The modelling targets that *are* worth pursuing

Sorted by leverage-per-unit-effort:

#### 2.3.1 Binary collapse (M01_v2_binary) — high priority, the user's instinct is right

**Revised 2026-05-23 (user pushback):** moved up from "small effort win" to
"high priority modelling sprint." The user's diagnosis is correct: **the model
is spending capacity predicting class boundaries we don't trade on.** Classes
0 (Noise ≤2%) and 1 (Moderate 2–10%) are not actionable in either direction —
they're not buys, and the boundary between them is statistical noise. Class 2
(Strong 10–30%) is mostly held-to-target-1 (15% / 3-ATR) under the current
exit rules, which means in the trade ledger it looks like class 3 anyway. We
actually care about **two things**: probability of Home Run (>20% or >30%) and
its complement.

Why this is likely a clear gain:
- The current model achieves 0.693 ROC-AUC on Home Run despite the 4-class
  softmax that has to also classify two boundaries (Noise/Moderate and
  Moderate/Strong) we don't care about.
- The dead-zone class 1–2 boundary (F1 ≈ 0.20) is consuming tree splits and
  hyperparameter capacity. Removing it should reallocate that capacity toward
  separating the only boundary that matters (≥20% MFE vs not).
- The midpoint-weighted `calibrated_score` in `score_from_duckdb` becomes
  cleaner: just `P(HomeRun) × E[return | HomeRun]` with a flat alternative,
  instead of a 4-class softmax × 4-midpoint dot product.
- Binary calibration is much better understood than multiclass; a reliability
  diagram is meaningful at a glance.

**Two variants worth training side-by-side:**
- `M01_v2_binary_20`: target = `mfe_pct > 20%`. Aligned with the original
  m01_rank target — interpretable as "will this trade make the high-conviction
  cohort?"
- `M01_v2_binary_30`: target = `mfe_pct > 30%`. The current class-3 definition
  — what `prob_elite` already tries to measure. Lets us check whether the
  4-class softmax has been *helping* or *hurting* the Home Run head.

**Acceptance:** Both variants:
- ROC-AUC on Home Run ≥ 0.70 (current 0.693 from 4-class)
- Calibration ECE < 0.05 across 10 probability bins
- Backtest (Case 1 protocol, same window) within ±15% of m01_prototype on
  return, Sharpe; max DD must not exceed −30%
- Top-K lift at K=10/50/100 must match or beat m01_prototype

If `M01_v2_binary_20` beats `M01_v2_binary_30` on backtest, the threshold
itself is informative (says the 20% / 20d boundary is closer to the
strategy's risk/reward inflection than 30%). If both beat prototype, promote
the better one. If neither beats prototype, the 4-class structure is doing
useful regularization we didn't realize — important negative result.

**Effort: 3–5 days** for both variants + evaluation + backtest comparison.
Promoted to the **first modelling sprint** in §2.4.

#### 2.3.2 Regime-conditional model — clear hypothesis, testable

We know IC collapses to −0.01 in Bear regimes (m03_score < 40) — the model has
essentially no edge there. Three options:
1. **Hard gate (current).** Don't trade Bear. Already implemented in
   SEPAHybridV1.
2. **Regime as feature.** Already there (m03_score, m03_delta_*,
   m03_regime_vol). Doesn't seem to be enough — IC still collapses in Bear.
3. **Regime as routing.** Train *two* models — one on Bull-regime training
   rows, one on Bear-regime training rows — and switch by regime at inference.
   This is the underutilized option.

**Acceptance:** Bear-regime IC > 0 (any positive value beats the hard gate at
the margin of "limited Bear trading"). Bull-regime IC ≥ current m01_prototype
on the same period. *Effort: 3–5 days.*

#### 2.3.3 Exit / hold classifier (M01-Hold) — different problem, well-posed

This is the one timing-style model that does **not** fall into the m01_rank
trap, because it conditions on an open position and asks a binary,
horizon-specific question:

> Given we're holding this name today, does the trend break within 5 trading days?

The label is unambiguous: did `trend_ok` flip to FALSE within the next 5 days?
This is a **degradation classifier**, not a return predictor. It informs the
"trend exit (runner)" tranche of SEPAHybridV1 — currently triggered by close <
SMA-50, a deterministic rule. The model could front-run that by a few days when
features (RS deterioration, RSI rolling over, volume drying up) suggest the
break is imminent.

**Acceptance:** Precision on "break within 5d" ≥ 0.60 at recall ≥ 0.50; trade-
level uplift (vs current SMA-50 rule) in MFE-captured and drawdown-avoided.
*Effort: 2–3 weeks.*

#### 2.3.4 Microstructure and post-breakout features — feeds whichever model wins

Currently the prototype trains on **breakout-day rows only**. Even if we
*select* on breakout day, we should *enrich* with:
- Days-since-most-recent-breakout (the §1 development-roadmap idea, restated)
- Post-breakout pullback depth / duration
- Volume profile shape (volume up-day vs down-day asymmetry in the consolidation)
- Earnings-event proximity (already have `earnings_calendar` — feature not used)
- Sector-rotation tailwind (already have `Sector_Momentum` — but as a *change*
  rather than a level)

These are **features**, not models. They can be added incrementally to the
existing model and tested by SHAP delta. *Effort per feature: 0.5–1 day to add,
0.5 day to validate impact.*

#### 2.3.5 What we are NOT building (and why)

- **m01_rank in its current form.** Shelved. Its score is horizon-invariant; it
  cannot supply timing. If revived, it needs path-distinguishing features
  (dip-depth, short-term reversal, oversold/RSI). Spend that effort on M01-Hold
  instead.
- **A new breakout-day classifier from scratch.** The current m01_prototype is
  fine on the breakout-day question; improve it via features, calibration, and
  regime routing instead of replacing it. (Note: this is *distinct* from
  M01-Watch in §2.2, which predicts *pre-breakout* — a different question on a
  different cohort.)
- **Deep learning anything.** The data is tabular, the sample sizes are modest
  (~38K trades), and XGBoost dominates this problem class. Don't bring a sequence
  model to a feature-importance fight.
- **Continuous-target regression** (predicting actual return rather than
  classifying it). The 4-class → binary collapse is the right direction; going
  to regression makes calibration harder, not easier, for this signal.

### 2.4 Suggested modelling cadence

| Sprint | Work | Output |
|---|---|---|
| **S1 (1 week)** | **M01_v2_binary_20 + binary_30, calibration audit, backtest diff** | Two trained models, reliability diagrams, ROC-PR, model_diff vs prototype, backtest comparison. **First decision point: do we promote a binary variant to prod?** |
| S2 (2 weeks) | M01-Watch (pre-breakout classifier, §2.2) — 3d/5d/10d variants + fail-fast acceptance gates | Three models or a documented kill decision; if passing, integrated into dashboard Watchlist page |
| S3 (1 week) | Regime-conditional routing variant (Bull / Bear model split) | Bull-regime and Bear-regime trained models, dashboard regime switch |
| S4 (1–2 weeks) | Post-breakout features added to v2 (`days_since_breakout`, pullback depth, vol-profile asymmetry, earnings-proximity, sector-rotation-delta) | model_diff showing SHAP delta per feature; ablation backtest results |
| S5 (3 weeks) | M01-Hold (exit / degradation classifier) | New model in registry, integrated into SEPAHybridV1 as optional exit signal |

Each sprint ends with a backtest re-run on the same fixed window so we can
read deltas cleanly. The model_diff tool already supports this. **S1 ships
first because it's the cheapest and most likely to win — and the result
informs whether S2/S3/S4 build on a binary or 4-class base.**

---

## 3. Where the infrastructure work goes next

The data engineering is in good shape. The gaps are operational — the things that
break when nobody is looking.

### 3.1 P1 — Quality gates and self-healing

**The `BAD_TICKERS` lesson.** LIF and CUE produced multi-million-percent return
rows that survived T1 → T2 → T3 → views → backtest. `detect_bad_tickers` only
warns. The fix is small but matters: wire the bad-ticker list into the loader,
not just into post-hoc analysis. Acceptance: a CI-runnable test that fails on
seeing `return_1d > 1000.0` (or `< -99%`) anywhere downstream of T2.

**Phase 1.5 quality gate.** The `audit_t1_data_quality` check should run *inside*
the daily pipeline DAG, before Phase 2 starts, and HALT on FAIL. Currently it's
a separate command that has to be run manually. Acceptance: a one-line
orchestrator change + a tested HALT path.

**adj_close populated upstream.** Right now 100% of `price_data.adj_close /
adj_factor / vwap` are NULL. Returns come from unadjusted `close` with split
clipping. That's been the source of one major artifact already. Two paths:
either populate adj_close from yfinance properly (yfinance's `auto_adjust=True`
in `data_engine`), or remove the columns entirely so no future analysis is
tempted by them. Acceptance: adj_close non-null OR removed; downstream consumers
audited.

**Invariant audits.** Cross-table contracts: every ticker in `t3_sepa_features`
has a sepa_watchlist row; every sepa_watchlist EXITED row has matching downstream
trades in `v_d2_training`; every model in the registry has a valid
`artifacts_path`. These are currently checked ad-hoc; turn them into a single
`tools/audit_invariants.py` that runs alongside the other audits.

### 3.2 P1 — Backtest realism

The Case 1 backtest is "clean" but not fully realistic. Three layers to add:

1. **Transaction costs.** Configurable bp-per-side, defaulting to 5bp roundtrip
   for liquid US equity (conservative). Acceptance: backtest CLI flag,
   trade-level cost line in the report.
2. **Slippage model.** Today's "buy at close" / "sell at close" is unrealistic
   for breakout-day entries on names that just popped. A simple VWAP-of-next-day
   model or a 50bp adverse-slip on entries should be the default. Acceptance:
   configurable, off by default with warning, on for "realistic" mode.
3. **Position-level capacity.** Today the backtest can buy 10K shares of a
   sub-$5M-daily-volume small-cap on the breakout day with zero impact. Add
   `max_pct_of_adv` (default 1% of average daily volume) as a cap. Acceptance:
   trades that would breach the cap are scaled down with a logged reason.

### 3.3 P2 — Pipeline observability

The pipeline runs but doesn't *signal* well. Structured JSON logging per phase,
with a one-line summary at the end. The Phase 8 monitoring already exists but
the outputs are unstructured. Acceptance: `logs/daily_pipeline.jsonl` with one
line per phase, queryable via DuckDB. Dashboard can then surface "last 30 days
of pipeline runs, RAG-coloured" without parsing text.

### 3.4 P2 — Reproducibility hooks

Two specific gaps:
- The model registry stores the feature set and hyperparameters but does **not**
  store a git SHA. If we re-train, we can't recover the exact `feature_pipeline.py`
  that produced the training data. Acceptance: `models` table gains a
  `code_sha VARCHAR` column populated by `train_mfe_classifier.py`.
- Backtest results have a `manifest.json` but no link back to the model version
  used. Acceptance: backtest manifest includes `model_version_id` field.

### 3.5 P3 — Scheduling and backup

- **Prefect (local) for daily orchestration.** Currently `run_daily_pipeline.py`
  is a script that the user runs by hand. Wire it under Prefect (local agent,
  no cloud) for retry-on-failure semantics and a small UI. Acceptance: a single
  `prefect deployment apply` command and a daily run schedule.
- **Nightly DuckDB backup to OneDrive or S3.** Right now there is one
  `market_data.duckdb` file. Loss = total. Acceptance: a `cron`-friendly script
  that copies the file (compressed) with a 14-day rolling retention.

### 3.6 Tech debt cleanup, in order of pain

1. `v_screener_dashboard` duplicates the session-detection CTE block from
   `v_d1_candidates`. Halve T2 scan work by sharing a materialized intermediate.
2. Rename `trend_c8` CTE → `trend_exit` (computes C1+C2+C6, not C1–C8). Cosmetic
   but bites every new reader.
3. Cross-sectional rank column casing — `rs_sector_rank` etc. need to be added
   to `COLUMN_CASE_MAP` so the lowercase / TitleCase mismatch doesn't bite.
4. `v_d2_hydrated` exists solely to feed `v_d2_training`. Can be eliminated if
   `v_d2_training` computes MAE/MFE/SL directly against `price_data`.

---

## 4. Dashboard — design

> **Status update (2026-05-23 evening):** Pages 1, 3, 4, 5 of the five-page proposal
> below are now **shipped as MVP**. Page 2 (Ticker Deep Dive) is the only one not
> yet built. Implementation details, page-by-page acceptance criteria, and
> resolved decisions live in
> [`dashboard_implementation_plan_2026_05_23.md`](dashboard_implementation_plan_2026_05_23.md);
> operational docs in [`../manual_for_me.md`](../manual_for_me.md) §Dashboard.
> The vision below remains the north star; the spec doc is the working contract.

The dashboard is the **point of use**. It is where the system stops being a
research project and becomes a tool. The current single-page Streamlit (M03
header + M01 summary + watchlist table + analytics) is a good v0 but is missing
the day-to-day decision flow.

### 4.1 Five-page proposal (Streamlit multipage)

#### Page 1 — Today (default landing) — ✅ SHIPPED 2026-05-23

The "what should I do this morning" page. Above the fold:

```
╔══════════════════════════════════════════════════════════════════╗
║ REGIME             │   POSITIONS         │   TODAY'S ACTION      ║
║ M03: 72 (Bull)     │   Open: 8 / Cap: 10 │   New entries: 3      ║
║ 5F:  0.81 (low-risk)│   Net: $42,316     │   Exits:        1     ║
║ Vol: low           │   Today P&L: +1.2%  │   Rebalance:    0     ║
╚══════════════════════════════════════════════════════════════════╝

NEW ENTRY CANDIDATES (M01 score, sorted by trailing 10d percentile)
┌──────┬───────────┬──────┬──────────┬────────┬─────────┬────────┐
│ Ticker│ Sector    │ M01  │ Trail %  │ Days   │ Entry $ │ Stop $ │
│       │           │ Score│ rank     │ since  │         │ (2 ATR)│
│       │           │      │          │ break  │         │        │
├──────┼───────────┼──────┼──────────┼────────┼─────────┼────────┤
│ XYZ   │ Tech      │ 78   │ 0.94     │ 0      │ 142.50  │ 134.20 │
│ ABC   │ Industrial│ 71   │ 0.89     │ 2      │  56.10  │  53.40 │
│ ...   │           │      │          │        │         │        │
└──────┴───────────┴──────┴──────────┴────────┴─────────┴────────┘

OPEN POSITIONS — degradation watch
┌──────┬─────────┬────────┬──────┬───────┬─────────┬──────────────┐
│ Ticker│ Entry   │ Days   │ P&L  │ Trend │ M01     │ Action       │
│       │ date    │ held   │ %    │ flags │ score   │              │
├──────┼─────────┼────────┼──────┼───────┼─────────┼──────────────┤
│ AAA   │ 04-12   │  41    │ +18% │ C1,C2,│  72     │ Hold; T1 hit │
│       │         │        │      │ C6 OK │         │ — sold 1/3   │
│ BBB   │ 03-08   │  76    │ +4%  │ C1 FAIL│  43    │ EXIT (trend) │
└──────┴─────────┴────────┴──────┴───────┴─────────┴──────────────┘

SECTOR HEAT (today's high-quality setup count by sector)
[ horizontal bar chart, top 5 sectors, with delta-from-5d-rolling-avg ]
```

This page answers: *what do I buy, what do I sell, what's brewing.*

**MVP delta vs the spec above:** all four header tiles (regime / 5F / positions /
action) collapsed into two side-by-side cards (M03 + 5F); positions/action stats
live in the existing Analytics quick-stats row. Pre-breakout cohort scoring runs
live each request (no `dashboard_snapshot` table yet — deferred). Trade-Age bar
chart was replaced with a Days-Held × Return scatter + quadrant filter (Hot /
Mature / Young / Aging) after the first UX pass.

#### Page 2 — Ticker Deep Dive — 🟡 NOT YET BUILT

Search-by-ticker. For any ticker, show:
- Price chart with SMA 50/150/200, entry markers, exit markers (annotated)
- M01 score trajectory (T−60 to T+30 around any breakout)
- Per-day C1–C9 / B1–B2 pass/fail matrix (reuses `ScreenerDiagnostics`)
- Fundamentals snapshot (latest 4 quarters: revenue, net income, EPS YoY)
- Earnings calendar (next earnings date, gap risk warning)
- Sector / industry rank within universe (today + 5-day delta)
- "Why this score?" — SHAP top-5 explanation pulled from latest scoring run

Use case: when the screener surfaces XYZ and you want to assess it before
buying. Currently this is done manually across 3 tabs and a chart.

#### Page 3 — Model Lab — ✅ SHIPPED 2026-05-23

The research view. For each model version in the registry:
- Card with status (test / prod / archived), accuracy, F1, training window
- Click → evaluation artifacts inline (confusion matrix, ROC, PR, calibration,
  SHAP, feature importance, training config)
- Side-by-side diff button (powered by existing `scripts/model_diff.py`)
- "Promote to prod" action (gated behind a confirmation modal)

Use case: when you've trained M01_v2_binary, you compare its plots to the prod
model and decide whether to promote. Right now this requires looking at PNG
files in nested folders.

**MVP delta vs the spec above:** read-only — "Promote to prod" was removed from
the UI (CLI-only via `ModelRegistry().set_prod(version_id)`); the diff tab is a
placeholder with a CLI hint instead of an inline subprocess; the canonical chart
view is the iframed `docs/reports/pretrain_audit_*.html` produced by
`scripts/run_pretrain_audit.py`. Per-model PNG plots are a secondary tab and
only render for the prod model today (older registry rows point at empty
artifact directories — by design, not a bug).

#### Page 4 — Backtest Studio — ✅ SHIPPED 2026-05-23

Pick a model version, a date range, a regime configuration, and a sizing mode.
Hit "Run." See:
- Equity curve vs SPY
- Drawdown chart
- Per-year breakdown (return, Sharpe, max DD, win rate)
- Regime-conditional breakdown (Strong Bull / Bull / Neutral / Bear)
- Trade table (sortable, filterable by sector / regime / outcome)
- Comparison panel (compare to previously saved runs)

This unlocks the §5 evaluation work without leaving the browser.

**MVP delta vs the spec above:** "Run" with on-the-fly parameter selection is
**not** built — Page 4 is a *browser* of pre-computed `data/backtest/<run_id>/`
runs, not an executor. Each run is gated on `manifest.json.manifest_version ==
"v1"` (schema introduced this session), so legacy/experimental runs on disk
remain hidden. Two seeded runs visible today: `case1_prototype_standalone`
(+201%) and `case2_prototype_plus_rank` (+65%). Compare mode overlays any 2
runs on date OR days-from-start axes.

#### Page 5 — Pipeline Health — ✅ SHIPPED 2026-05-23

The ops view:
- Last 30 days of pipeline runs (RAG-coloured per phase)
- Audit history (last run, FAIL/WARN counts trended)
- Data freshness panel (max date per table vs today, alert if stale)
- Universe size over time, breakout count over time, candidate count over time
- Storage growth chart (so we know when we'll exhaust local disk)

Use case: weekly sanity check; daily sanity check after pipeline failures.

**MVP delta vs the spec above:** Audit history currently shows a **single
point** (only `audit_report_20260328.json` on disk). The page renders this with
a "history accumulating" banner and will populate naturally once the daily
orchestrator gains a Phase-9 audit-write hook — deferred this session by the
user ("MVP, worry about data later"). Pipeline JSONL logging from §3.3 not yet
built; the heatmap reads `pipeline_runs` directly instead.

### 4.2 Implementation notes

- All data should come from DuckDB and the JSONL log — **no new tables for the
  dashboard**. The screener_watchlist and v_d3_deployment views are already the
  right shape.
- Performance: pre-compute one daily snapshot at the end of the pipeline (a
  `dashboard_snapshot` table with everything Page 1 needs). Refresh time should
  be <500ms on warm cache. **Status:** not built; Page 1's pre-breakout cohort
  scores ~50 tickers live each request. Acceptable for MVP; revisit if load
  latency becomes painful.
- Auth: localhost-only, no auth. This is a single-user tool. Don't accidentally
  expose the dashboard on a network port without thinking about it.
- Charts: Plotly for interactivity (zoom on price charts is critical), Streamlit
  native for tables.
- **Streamlit form-wrap pattern** (learned 2026-05-23): filter controls above
  any expensive widget must live inside `st.form(...)` so the rerun fires on
  Apply, not on every keystroke. Without this, typing in the Page-1 search box
  was re-running M01 `predict_proba` on the pre-breakout cohort per character.

### 4.3 Shipped 2026-05-23 — what's live, what's left

**Shipped (MVP):**
- All 5 pages built per §4.1, except Page 2 (Ticker Deep Dive).
- Shared loaders / constants extracted to `scripts/dashboard_utils.py`.
- Backtest manifest schema bumped to v1 (model name / version / path block);
  case1 + case2 re-run cleanly under the new schema.
- Pretrain HTML generator (`scripts/run_pretrain_audit.py`) verified — produces
  5+ MB self-contained Plotly HTML; Model Lab embeds it via
  `st.components.v1.html`.

**Deferred (post-MVP, not blocking daily use):**
- Page 2 (Ticker Deep Dive) — `ScreenerDiagnostics` ready; the chart layer and
  SHAP explanation layer are the work. Estimate 3 days.
- `dashboard_snapshot` precompute table — only needed if Page 1 latency becomes
  a problem.
- Pretrain HTML version-pinned to model — today the report is selected by
  mtime, not by selected `version_id`.
- Daily Phase-9 audit-write hook → unlocks Page 5 audit-history trend.
- Pipeline JSONL logging (§3.3) → richer Page 5 drill-downs than the current
  `pipeline_runs` view.

---

## 5. Evaluation rigour — what "academic" actually means here

> **Status update (2026-05-24):** the framework specified below is now **operational**.
> Library modules in `src/evaluation/`, deep-rigor scripts in `scripts/`, gates
> auto-merged into `results.json` per training run. Operational reference lives
> in [`docs/manual_for_me.md`](../manual_for_me.md) §Evaluation Framework. What
> remains is **applying** it — running the deep-rigor battery against each
> candidate model and recording a verdict. Per-subsection status flags below.

This is the section the project is most under-invested in. Two backtests and an
IC table is not a body of evidence; it is a starting point. Below is the
minimum-credible evaluation regime we should aim for before claiming
m01_prototype is "production-ready" in the institutional sense.

### 5.1 Walk-forward cross-validation (mandatory before any model promotion) — ✅ SHIPPED

The current Case 1 backtest is a single train/eval split: trained through
2024-02, backtested 2020–2024 (with overlap on the train window — explicit
caveat in the session log). That's not a credible OOS test for the years that
overlap training.

**Protocol.** Anchored walk-forward, 1-year increments:
- Train on 2003–2018 → score 2019; train on 2003–2019 → score 2020; …; train on
  2003–2024 → score 2025.
- For each fold, produce: backtest metrics (return, Sharpe, max DD, win rate),
  classification metrics (top-K lift, ROC-AUC for Home Run, calibration), and
  feature importance.
- Aggregate: mean ± std across folds, plus the *worst* fold. We care about the
  worst fold; it's where the strategy actually has to survive.

**Acceptance bar.** Mean Sharpe > 0.5, worst-fold Sharpe > 0, worst-fold max DD
< 35%. Mean top-3 Home Run lift > 5×.

**Shipped.** `src/evaluation/walk_forward.py` (`WalkForwardSplitter`, anchored
expanding folds, 1Y default) + `src/evaluation/walk_forward_backtest.py`
(`run_walk_forward_backtest`, `aggregate_walk_forward_backtest`,
`default_signals_to_scores` with calibrator + trailing-rank support). Trainer
flags `--walk-forward` + `--with-wf-backtest`. Four blocking gates emitted:
`wf_backtest_mean_sharpe`, `wf_backtest_worst_sharpe`,
`wf_backtest_worst_max_drawdown`, `wf_backtest_mean_top_3_home_run_lift`.

### 5.2 Regime-conditional metrics — ✅ SHIPPED

Decompose every metric by M03 regime category at the time of entry:

| Regime | n trades | Win rate | Avg MFE | Avg MAE | Median hold | Sharpe |
|---|---|---|---|---|---|---|
| Strong Bull | … | … | … | … | … | … |
| Bull | … | … | … | … | … | … |
| Neutral | … | … | … | … | … | … |
| Bear | … | … | … | … | … | … |

We already know IC collapses in Bear. The question is: does the strategy
*break even* in Bear (because the regime gate blocks new entries and existing
positions exit cleanly) or does it *bleed* (because the exits trigger too late)?
Answer: unknown. Compute it.

**Shipped.** `src/evaluation/regime_decomposition.py` splits per-regime AUC, F1,
top-3 lift, calibration ECE. Trainer flag `--with-regime-decomp`. Blocking gate
`regime_decomposition` passes if ≥ 3/5 regimes have AUC ≥ 0.55 with no
catastrophic regime (< 0.50). Results land in `results.json::regime_decomposition`.
**Empirical result (`m01_binary/v1`):** Bear 0.62, Neutral 0.72, Bull 0.72,
Strong Bull 0.72 — 4/4 evaluable pass; Strong Bear had 0 test samples. Same
gate also computed for `m01_prototype_may/v2_gated` (4/4 pass) — encouraging,
but does not survive the §5.6 permutation null test.

### 5.3 Calibration audit — ✅ SHIPPED + isotonic remediation

Reliability diagrams per class. Pseudo-code:
1. Bin predicted probabilities into deciles (or finer for class 3).
2. For each bin, compute observed frequency of the true class.
3. Plot observed vs predicted; the diagonal is perfect calibration.
4. Compute Brier score and Expected Calibration Error (ECE).

The model is used by the backtest as if `predict_proba` were calibrated (the
midpoint-weighted expected MFE in `score_from_duckdb`). If it isn't, the
backtest is using miscalibrated weights. We should know whether this matters.

**Shipped.** ECE / reliability primitives in `src/evaluation/calibration.py`.
Per-class ECE + Brier emitted in `results.json` always. **Remediation layer:**
`src/evaluation/calibrator.py::IsotonicCalibrator` — fits on val slice after
training, persists to `<model_dir>/calibrator.joblib` + sidecar `.meta.json`,
monotone with out-of-bounds clip. Enabled via trainer flag `--with-calibration`.
`UniverseScorer` auto-loads the calibrator if present. Two gates:
`calibration_ece` (raw, threshold 0.05 on production class) and
`calibration_ece_post` (post-isotonic, threshold 0.10).
**Empirical result (`m01_binary/v1`):** raw ECE 0.316 (fail) → post-isotonic ECE
1e-17 (pass). Isotonic compression is a tail-flattener — see §5 caveat in the
strategy-array result, where calibration *hurts* PnL for ranker strategies but
*helps* for threshold-gated strategies.

### 5.4 Feature stability (PSI / KL drift) — 🟡 LIBRARY SHIPPED, QUARTERLY WIRING OPEN

Population Stability Index, computed quarter-over-quarter for the top 20
features by SHAP gain. PSI > 0.25 on any feature = drift alert. Run quarterly
in the pipeline; surface on Pipeline Health page.

**Shipped.** `src/evaluation/drift.py` with three primitives:
- `compute_psi(reference, current, bins=10)` — fixed-edge bins from reference
  quantiles, ε-clamped for empty current bins.
- `reference_snapshot(train_df, feature_cols, output_path)` — saves per-feature
  bin edges + ref counts as JSON. Called by trainer at promotion time, written
  to `<model_dir>/reference_snapshot.json`.
- `quarterly_drift_report(reference_path, current_view, quarter)` — computes PSI
  per feature for a date range, returns drift verdict + gate.

8 unit tests in `tests/test_drift.py`. **Reference snapshot already written for
`m01_binary/v1`.**

**Open.** Quarterly auto-trigger inside `daily_pipeline_orchestrator.py` Phase 8
(fire on Jan/Apr/Jul/Oct 1st), writing to `logs/drift/<quarter>.json`, and the
Pipeline Health dashboard widget that surfaces drifted features. Estimated 0.5d.
Tracked in `docs/plans/evaluation_remaining_implementation_plan_2026_05_24.md` §2.2.

### 5.5 SHAP audit (already partially done) — extend it — ✅ SHIPPED + EMPIRICAL VERDICT

The known SHAP-vs-Gain disagreement (volatility/VCP features by gain vs
momentum/RS features by SHAP) is unresolved. Two specific tests:
1. **Permutation importance** (the third opinion). If permutation agrees with
   SHAP, we have stronger evidence the model is exploiting momentum/RS and the
   gain-based "natr dominates" is misleading.
2. **Feature ablation backtest.** Re-train without `natr` and the volatility
   block. If the backtest is unchanged, the feature group is decorative; if it
   collapses, it's load-bearing. SHAP says decorative; gain says load-bearing.
   The backtest settles it.

**Shipped.**
1. **Permutation importance** wired into trainer via `--with-perm-importance`
   (5 repeats × 2000 sample default). Adapter handles sklearn ≥1.6 (sets
   `_estimator_type = "classifier"` + `__sklearn_tags__()`).
2. **Ablation backtest** via `scripts/ablation_backtest.py` — per-feature-group
   dropout, retrains a sibling model, runs backtest, emits `metrics.json` per
   group.

**Empirical verdict (from `m01_prototype_may/v2_gated` §1.4(c) deep-rigor pass):**
SHAP and permutation importance *agree* — top features by gain (`natr`,
`consolidation_width`, `adr_20d`) have **negative** permutation importance
(shuffling them improves log-loss). Ablation triangulates: dropping
`Volatility_Ranges` *improves* Sharpe by +0.131 and total return by +14pp.
Dropping `Technical_Oscillators` is neutral. Load-bearing groups (Sharpe drop
≥ 0.4 when dropped): Core_Volume, Fundamentals, Momentum_RS. Result confirmed
on `m01_binary/v1` permutation importances (same three groups dominate negative
tail). Carries to the binary reformulation:
- Drop `Volatility_Ranges` (14 features)
- Drop `Technical_Oscillators` (4 features)
- Protect Core_Volume, Fundamentals, Momentum_RS in any selection step

### 5.6 Statistical significance of returns — ✅ SHIPPED + EMPIRICAL VERDICT

The Case 1 +201% looks good. But over 1500 trades in a 4.5-year sample with a
heavy-tailed return distribution, what is the 95% CI? Two protocols:
1. **Block bootstrap** of trade outcomes (block size = 60d to capture regime
   persistence). 10K resamples. Report median, 5%/95% quantiles.
2. **Permutation null.** Shuffle the entry signal (keep entry dates, randomize
   tickers) and re-run the backtest 1K times. The actual result should lie in
   the top 1% of the permuted distribution. This is the test that catches "you
   could have done as well randomly."

Both are 1-day notebook exercises; they should be standard before any model
promotion.

**Shipped.**
1. `src/evaluation/bootstrap.py::circular_block_bootstrap()` (default block=60d)
   + `sharpe_from_trades`, `total_return_from_trades` reducers. Driver:
   `scripts/run_bootstrap_ci.py`.
2. `src/evaluation/permutation_null.py::permutation_null_backtest()` — shuffles
   signal within each date, recomputes metric, returns observed percentile in
   null distribution. Vectorised against `d2_training_cache` (was hanging at
   18GB on `v_d2_training` — JOIN bomb). Driver: `scripts/run_permutation_null.py`.

**Empirical verdict (from `m01_prototype_may/v2_gated` §1.4(c)):**
- Bootstrap CI: observed Sharpe 0.334, **95% CI [-1.29, +1.85]** — straddles
  zero. Total-return CI similarly diffuse.
- Permutation null: observed Sharpe **-0.42**, null median +0.43, observed at
  **percentile 2.0** (worse than random 98% of the time). Catastrophic fail.

These two gates flipped the v2_gated verdict from "ambiguous" to a hard DEMOTE.
Same battery has not yet been run against `m01_binary/v1` — recorded as an open
operational task.

### 5.6b Decile analysis / Information Coefficient — ✅ SHIPPED (new addition)

Added during the §1.4(c) deep-rigor pass — not in the original §5 spec but a
necessary companion to bootstrap CI. Bucket WF OOS predictions into deciles by
`prob_elite`, compute mean realised PnL per decile, and the Spearman rank
correlation (Information Coefficient) between predicted probability and outcome.

A working ranker has monotone decile means and Spearman IC > 0.05 with p < 0.01.
A *broken* ranker has top-decile PnL below middle deciles, or negative IC — the
diagnostic that revealed v2_gated's pathology.

**Shipped.** `scripts/run_decile_analysis.py`. Reads `trades.parquet` from each
WF fold, computes decile stats + Spearman IC + p-value, writes
`evaluation/full_eval/decile_analysis.json`.

**Empirical verdict (`m01_prototype_may/v2_gated`, 348 WF trades):**
**Spearman IC = -0.135, p = 0.012** — negative and statistically significant.
Top decile P(HR) = 8.6% vs bottom 0%, but middle deciles (3-4) carry the only
positive mean PnL. Non-monotone. This is the finding the model can't ranker its
own picks usefully — and it's *what the strategy array S3 result quietly works
around* by using probability as a threshold, not a ranker.

### 5.7 Forward paper-trade (the only ground truth) — 🟡 HARNESS SHIPPED, DATA COLLECTING

Six months of paper trading from today — same signals, same exits, same regime
gating, but real-time data. Compared against the backtest predictions for the
same period. This is the only evaluation that doesn't suffer from a hindsight
bias. The dashboard work in §4 enables this directly: Page 1 + a manual
"taken / skipped" toggle + a trade log = paper-trading harness.

**Shipped.** Phase D §5.1 of dashboard (commit `a2bb79a`):
- `src/evaluation/prediction_logger.py` writes daily M01 scores to
  `daily_predictions` table.
- Dashboard Page 1 "Today's Predictions — Decision Log" renders today's picks
  with a `taken/skipped` toggle per ticker, persisted across refreshes.
- Past Decisions view shows historical taken/skipped flag joined to realised
  outcome from `screener_watchlist`.

**Open.**
- The prediction logger was silently broken pre-2026-05-24; `daily_predictions`
  is empty for the historical period of the prod model. `scripts/backfill_daily_predictions.py`
  not yet written. Plan §3.2.
- "Six months of data" is six months of writes. Started 2026-05-24; meaningful
  performance comparison ETA Q4 2026.

### 5.8 What "understanding the model" means, in concrete deliverables

A model is understood when we can answer:

| Question | Deliverable | Tool | Status |
|---|---|---|---|
| When does it work? | Regime-conditional table (§5.2) | `regime_decomposition.py` + `--with-regime-decomp` | ✅ shipped |
| When does it break? | Worst-fold walk-forward analysis (§5.1) | `walk_forward.py` + `--walk-forward` + `--with-wf-backtest` | ✅ shipped |
| Why does it work? | SHAP + permutation + ablation agreement (§5.5) | `--with-perm-importance` + `ablation_backtest.py` + SHAP in evaluator | ✅ shipped |
| Are its outputs trustworthy at face value? | Calibration audit (§5.3) | `calibration.py` + `calibrator.py` (isotonic) + `--with-calibration` | ✅ shipped |
| Is the edge statistically real, or sample noise? | Bootstrap CI + permutation null (§5.6) | `bootstrap.py` + `run_bootstrap_ci.py` + `permutation_null.py` + `run_permutation_null.py` | ✅ shipped |
| Does the ranker actually rank? | Decile / Spearman IC (§5.6b) | `run_decile_analysis.py` | ✅ shipped (new) |
| Will it keep working? | PSI drift + paper trade (§5.4, §5.7) | `drift.py` + dashboard Decision Log | 🟡 library shipped, ops wiring open |

~~We currently have partial answers to (1) and (3). Everything else is open. **This
is the work, more than building a new model.**~~

**Updated 2026-05-24.** Six of seven rows are shipped end-to-end. Only PSI
quarterly auto-trigger + paper-trade data accumulation remain. What's left is
**applying** the framework — running the deep-rigor battery against each
candidate model and recording verdicts — not building it.

### 5.9 Verdicts on record

| Model | Verdict | Source | Notes |
|---|---|---|---|
| `m01_prototype_may/v2_gated` (4-class) | **DEMOTE** | `models/m01_prototype_may/v2_gated/evaluation/full_eval/full_eval_report.md` (2026-05-24) | Permutation null at percentile 2.0 (catastrophic), Spearman IC -0.135 (anti-skilled within operating zone), bootstrap CI straddles zero. Per-regime AUC and ablation findings drove the binary reformulation. |
| `m01_binary/v1` (binary, calibrated) | **PENDING** | trainer gates only (`results.json`) | 4/8 blocking gates pass: calibration_ece_post, regime_decomp, WF_worst_AUC, WF_worst_DD. 4 fail: calibration_ece (raw), WF_mean_Sharpe (0.476 vs 0.5), WF_worst_Sharpe (-0.263, 2/4 positive folds), WF_top3_lift (1.55× vs 5×). **Strategy array S3 (P≥0.30 gate, 5-pos cap): Sharpe 1.59, DD 11.1%.** Deep-rigor battery not yet run. |

### 5.10 Operational reference

Day-to-day commands, gate thresholds, file locations, library inventory, and
known gotchas live in [`docs/manual_for_me.md`](../manual_for_me.md) §Evaluation
Framework. This section sets the *why*; the manual is the *how*. The
implementation plan that produced the framework is
[`evaluation_remaining_implementation_plan_2026_05_24.md`](evaluation_remaining_implementation_plan_2026_05_24.md) —
its §1.1-§1.4 / §2.1 / §2.2 are now closed; §3.1 / §3.2 + the quarterly drift
wiring remain.

---

## 6. Value-adding deliverables we can ship now

A prioritized list of things that are *small enough to ship in 1–5 days* and
*compound the system's usefulness*:

| # | Deliverable | Effort | Status | Why it matters |
|---|---|---|---|---|
| 1 | `BAD_TICKERS` wired into loader | 0.5d | open | Closes a known data-quality hole that has bit us twice |
| 2 | Phase 1.5 quality gate in orchestrator | 1d | open | Stops bad-data days from propagating |
| 3 | Backtest with TX costs + slippage | 2d | open | Realism floor before any number is quotable |
| 4 | Walk-forward CV harness (anchored, 1y folds) | 3d | ✅ shipped 2026-05-24 (`walk_forward.py` + `walk_forward_backtest.py` + `--with-wf-backtest` trainer flag, 4 blocking gates) | Unlocks §5.1; required before any promotion |
| 5 | Sector-heat dashboard widget | 1d | ✅ shipped (Page 1) | Highest-ROI dashboard add per §4; with 1d/5d/20d window selector |
| 6 | Calibration audit notebook + plots | 1d | ✅ shipped 2026-05-24 (`calibration.py` + `calibrator.py` isotonic, `--with-calibration` flag, 2 gates) | Tests whether `expected_MFE` is meaningful |
| 7 | Permutation null backtest | 1d | ✅ shipped 2026-05-24 (`permutation_null.py` + `run_permutation_null.py`, vectorised against `d2_training_cache`) | Sanity-checks the +201% |
| 8 | Pipeline JSONL logging | 1d | open (Page 5 reads `pipeline_runs` instead) | Foundation for richer Page-5 drill-downs |
| 9 | Adj_close populated OR removed | 2d | open | Closes the NULL-column attractor that caused the 28× artifact |
| 10 | Ticker Deep Dive dashboard page | 3d | open (only Page 2 not yet built; others shipped) | Hugely useful for daily decisions |
| 11 | Forward-paper-trade tracker (manual toggle on dashboard) | 2d | open | Starts §5.7 ground-truth collection |
| 12 | M01_v2_binary trained + diff vs prototype | 3d | open | First modelling sprint — small, contained, high-info |
| 13 | Backtest manifest schema v1 + Pages 3/4/5 of dashboard | — | ✅ shipped 2026-05-23 | Operational layer for Model Lab + Backtest Studio + Pipeline Health |

If we ship #1–4 and #6–8 (≈ 9 days of work), the *evaluation* baseline is in
place. **#5 + #13 already shipped.** Remaining ops-loop work is #10 + #11
(≈ 5 days). Modelling (#12) can run in parallel because it doesn't block the
others.

---

## 7. Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Data corruption from a bad yfinance day going unnoticed | High | High | Phase 1.5 quality gate + BAD_TICKERS + adj_close fix |
| DuckDB file loss (single-disk failure) | Medium | Critical | Nightly backup (§3.5) |
| Model degradation in regime we haven't seen (e.g., sustained high-inflation) | Medium | High | Regime-conditional metrics + PSI drift + paper trade |
| Over-fitting to the 2020–2024 window | High | Medium | Walk-forward CV with 2019 and 2025 as held-out folds |
| Backtest numbers don't survive transaction costs | Medium | High | Add TX cost / slippage / ADV-capacity in §3.2 *before* quoting any number externally |
| Confusing "selection score" with "timing score" again | Low | Medium | The m01_rank verdict is documented; section 2 of this paper exists to prevent the next recurrence |
| Build-trap (always building, never trading) | High | Medium | Forward paper trade (§5.7) is the forcing function |

---

## 8. What this paper is NOT

- Not a sprint plan. Each section maps to one or more entries in the per-sprint
  plans in `docs/plans/`. This paper sets the *priorities*; the sprint plans set
  the schedule.
- Not a model-architecture document. The modelling section is opinionated about
  *what not to build* more than *what to build*. The "what to build" detail will
  go into per-model design notes (e.g. `m01_v2_binary_design_note.md` when that
  work starts).
- Not a complete spec for the dashboard. §4 sets the page structure and
  decision-flow ergonomics. The visual design / Streamlit code is a separate
  sprint with its own mocks.
- Not a final word on `m01_rank`. The §0 verdict is the *current* finding. The
  reframe in §2.3 (M01-Hold) is the path to revisit timing without falling into
  the same trap. If the path-distinguishing-features experiment ever runs and
  succeeds, this paper updates.

---

## 9. Open questions for sign-off

1. Do you agree with the **shift from "build the next model" to "evaluate the
   current model rigorously"** as the highest-leverage next move?
2. Of the §6 deliverables, which 8–10 are the next sprint? Default
   recommendation: #1, #2, #3, #4, #5, #6, #8, #10, #11, #12 — splits 60/40
   across evaluation/ops and modelling.
3. Is paper-trading from "today" (i.e., starting next week) acceptable, or do we
   want one more month of evaluation work first? Recommendation: start it now.
   It's the only honest forward test.
4. ~~Do we want the dashboard pages built in Streamlit or migrate to a Vue/React
   frontend?~~ **Resolved 2026-05-23:** Streamlit MVP shipped (Pages 1, 3, 4, 5).
   Revisit only if daily use exposes a UX cliff Streamlit can't climb.
5. Is there a hard deadline (live capital deployment date) that should drive
   sprint prioritization differently?

---

## Appendix A — Cross-document index

- Daily pipeline mechanics → [`docs/manual_for_me.md`](../manual_for_me.md)
- Replication spec → [`docs/comprehensive_methodology.md`](../comprehensive_methodology.md)
- m01_rank kill verdict → [`docs/session_logs/2026-05-22_backtest-cases.md`](../session_logs/2026-05-22_backtest-cases.md)
- m01_rank design + §8 next-direction list → [`docs/plans/m01_rank_design_note_2026_05_22.md`](m01_rank_design_note_2026_05_22.md)
- Case studies results → [`docs/plans/m01_case_studies_2026_05_22.md`](m01_case_studies_2026_05_22.md)
- Prior roadmap (item-by-item) → [`docs/plans/development_roadmap.md`](development_roadmap.md)
- System design action plan → [`docs/plans/system_design_review_action_plan_2026_05_16.md`](system_design_review_action_plan_2026_05_16.md)
- M01 modelling strategy plan → [`docs/plans/m01_modeling_strategy_plan_2026_05_18.md`](m01_modeling_strategy_plan_2026_05_18.md)
