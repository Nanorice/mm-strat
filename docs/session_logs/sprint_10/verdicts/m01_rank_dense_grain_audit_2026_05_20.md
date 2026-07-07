# m01_rank — Dense-Grain Infra Audit & Strategy Fix

**Created:** 2026-05-20
**Owner:** Hang
**Trigger:** Post-G6 review of m01_rank revealed 28× backtest return / 44% per-trade — implausibly amplified. Root cause: dense-grain training data (~250 rows/ticker/year) inflates the importance of slow-moving features (`adr_20d`, `low_52w`) because the same near-duplicate `(X, y)` pair is replicated dozens of times per SEPA episode.

## 🎯 Framing (User Decision 2026-05-20)

`m01_rank` is **intentionally dense-grain**. Its purpose is to monitor how a
ticker's score *evolves* day-by-day — not to make a one-shot decision per
breakout episode. Retraining on event-grain would defeat the model's purpose.

Therefore the question is **not** "should we resample the training data?"
The question is:

> **Does our existing analytics / training / backtesting infrastructure correctly handle dense panel data, or does it implicitly assume one-row-per-event?**

Every piece of infra used in G0–G6 needs to be re-examined under this lens.

## 🧭 Strategy Definition (User Decision 2026-05-20)

Backtest strategy for dense-grain models:

- **Daily rebalance to top-K**, BUT
- A name is only eligible to enter if it has **persisted in top-K for ≥3 consecutive days**
- **Weekly rotation** acceptable as an alternative cadence
- This replaces the cookbook's `consec=3 → buy → hold-until-signal-breaks` logic, which conflated entry persistence with hold duration

## 📋 Scope of Work

### Phase 1: Audit — Which pieces of infra silently assume event-grain?

- [ ] **1.1 — Walk-forward AUC (G3)**
  - Does `walk_forward_score()` give each ticker-episode equal weight, or does it weight by row count?
  - If row-count: 2022 fold's 0.79 AUC is dominated by whichever tickers had the longest qualifying runs in 2022.
  - **Test:** group AUC by ticker first, then average across tickers. Compare to current per-row AUC.

- [ ] **1.2 — IC / Spearman computation (G3)**
  - Same question. Spearman across 3.4M rows treats each row independently.
  - **Test:** compute IC per (ticker, episode) → average across episodes. Sanity-check magnitude.

- [ ] **1.3 — SHAP / feature importance (G5)**
  - `adr_20d` SHAP 5× any other feature: is this real economic signal or label-mass concentration?
  - **Test:** subsample to 1 row per (ticker, 20-day-block) → retrain → recompute SHAP. If `adr_20d` drops to peer-level, it confirms duplication artifact.

- [ ] **1.4 — Score persistence metric (G4)**
  - 0.94 per-ticker persistence is currently flagged as a feature of m01_rank.
  - Is this *because* the model is well-calibrated for slow regime detection, or *because* features themselves barely move day-to-day?
  - **Test:** compute persistence on a permuted-feature null model. If null persistence is also ~0.9, the metric is uninformative.

- [ ] **1.5 — `compute_redundancy` (G3 infra)**
  - Rank-then-Pearson on 200k-row sample. Does the sample treat dense rows IID?
  - Likely fine (correlations between features don't depend on label duplication), but verify the sample is stratified across tickers, not date-blocks.

- [ ] **1.6 — `v_d2_training` / `d2_training_cache`**
  - Confirm this view returns dense rows (it should — that's the design).
  - Confirm there's no implicit dedup logic that would silently drop rows.

### Phase 2: Backtest engine rewrite

- [ ] **2.1 — Replace `portfolio_backtest` Cell 20 logic**
  - Current: `consec=3` gates entry, hold-until-signal-breaks, no re-entry while open.
  - New: daily rebalance to top-K with 3-day persistence filter for entry.
  - Open question: **exit rule?** Options:
    - (a) Exit when ticker falls out of top-K (any day)
    - (b) Exit when ticker falls out of top-K for 3 consecutive days (symmetric with entry)
    - (c) Exit on calendar (e.g., 20 trading days), regardless of score
  - **Recommendation:** (b) — symmetric persistence eliminates score-flicker churn.

- [ ] **2.2 — Weekly rotation variant**
  - User mentioned weekly rotation as an alternative. Implement as a `rebalance_freq='W'` parameter.
  - Compare daily vs weekly on the same fold to see if churn or returns differ meaningfully.

- [ ] **2.3 — Slot accounting & business-day timedelta**
  - Carry forward the fixes already drafted in `m01_rank_notebook_cookbook.md`:
    - `assert max_concurrent <= top_k`
    - Business-day timedelta (not calendar)
    - Per-slot annualization

- [ ] **2.4 — Leakage stress tests** (from prior handover, still applicable)
  - Shuffled-target backtest → nav_sharpe should drop to ~0
  - 5-day-lagged-feature AUC → should drop modestly but stay positive

### Phase 3: Re-run G3–G6 with audited infra

- [ ] **3.1 — Re-run G3** with ticker-grouped AUC/IC alongside per-row metrics.
- [ ] **3.2 — Re-run G4** with null-model baseline for persistence.
- [ ] **3.3 — Re-run G5** with episode-subsampled SHAP comparison.
- [ ] **3.4 — Re-run G6** with new backtest engine (daily rebalance + 3-day persistence).
- [ ] **3.5 — Document** which G-gate metrics changed materially and why.

### Phase 4: Methodology doc update

- [ ] **4.1 — Add "Dense vs Event Grain" section** to `docs/model_development_methodology.md`
  - When to use each, what metrics need adjustment under each.
  - Default G3/G4/G5 gates assume event-grain. Dense-grain models need ticker-grouped variants.

- [ ] **4.2 — Update `m01_rank_notebook_cookbook.md`**
  - Replace Cell 20 backtest with dense-grain version.
  - Add ticker-grouped AUC/IC cells.

## ❓ Open Questions

1. **Exit rule symmetry** (2.1): symmetric 3-day-out filter, or asymmetric (any-day exit)?
2. **K in top-K**: cookbook used `top_k=3`. Is that still the target, or should K scale with breadth?
3. **Persistence window**: 3 days fixed, or should it be a swept parameter alongside K?
4. **Weekly rotation cadence**: every Monday open, or rolling 5-day window with daily eligibility check?
5. **Null model for 1.4**: permute features within ticker (preserves per-ticker structure) or globally (breaks all signal)?

## 🚫 Out of Scope (Explicit)

- **Do NOT retrain `m01_rank` on event-grain.** Dense-grain is the design intent.
- **Do NOT change `t3_sepa_features` schema or row construction.** The data is correct; the consumers may not be.
- **`m01_breakout`** (event-grain successor) — deferred. Same methodology, different target construction.

## 📦 Carried Forward From Prior Handovers

- `src/evaluation/feature_signal.py:compute_redundancy` patch — committed ✅
- 8-gate methodology + cookbook docs — committed ✅
- Pretrain HTML report work (2026-05-18) — still uncommitted, separate concern
- `notebooks/data/market_data.duckdb` stub cleanup if present

## ✅ Definition of Done

- All Phase 1 audit items have a written finding (PASS / FIX-NEEDED / IRRELEVANT).
- New backtest engine merged into Cell 20 with daily + weekly rotation modes.
- G3–G6 re-run produces ticker-grouped metrics alongside per-row metrics.
- A single-paragraph verdict in this file: **"Is m01_rank's signal real once dense-grain artifacts are controlled for?"** With evidence.
- Methodology doc has dense-vs-event-grain guidance for future models.
