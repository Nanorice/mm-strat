# Goal B: Minervini Stage Classifier Plan (v2)

> **STATUS: Phase 3 done — HARD GATE FALSIFIED. Outcome: keep primitives as candidate features,
> feature-set inclusion DEFERRED (own study). No wiring.** Code: `src/features/trend_segments.py`,
> `scripts/validate_market_stage.py`, `scripts/falsify_stage_gate.py`,
> `tests/test_trend_segments.py`. Cache: `stage_gate_panel.parquet` (7.4M rows;
> `falsify_stage_gate.py --from-cache` to re-report). See PHASE 3 VERDICT below.

## PHASE 3 VERDICT — the stage GATE is falsified (full-N, 2,711 watchlist tickers)

Forward-return test on population B (SEPA watchlist rows), 5/20/60d, from `price_data` with
adjacency guard. **Stage 2 vs Stage 3/4 spread: 5d −0.02%, 20d +0.05%, 60d +0.65%.** No
short-term edge; the only real separation is a weak 65bps at 60d — far too small to justify a
hard entry gate that discards trades.

**The ranking INVERTS the Minervini prior.** By 60d mean forward return on the watchlist:
**Stage 1 (+5.2%, n=2040) ≈ Stage 4 (+6.5%, n=344) > Stage 2 (+1.9%) > Stage 3 (+1.2%).**
On an already-selected watchlist, fresh bases (1) and washout bounces (4) outrun mid-advance
names (2) over ~3 months — mean reversion beats momentum *within this pre-filtered set*. This is
why an "avoid Stage 3/4" gate backfires: Stage 4 here is a bounce, not a falling knife (the gate
fires late because Stage 3/4 require `NOT trend_ok`, i.e. the template is already broken).

Stage 1 vs 3 (the flagged weak seam): indistinct at 5d, DISTINCT at 20/60d (Stage 1 clearly
better). They do separate at longer horizons — no collapse needed, but the split only pays off
long-horizon.

**DECISION (user):** kill the hard gate; keep `market_stage` + `slope_63d` + `slope_r2_63d` +
`prior_slope_sign` as **candidate model features** (esp. M02 breakout-timing, where a soft
weighted signal can exploit the weak long-horizon structure without discarding trades).
**Feature-set inclusion is DEFERRED to its own study** — not wired now. If any of these ever
enters an M01/M02 feature set, the `COLUMN_CASE_MAP` casing guard (Phase 3 note) applies.

> **v2 revision note.** Original plan proposed a from-scratch rule module. Review found the
> Minervini Stage-2 trend template is *already materialized* as `trend_ok` in
> `src/feature_pipeline.py` (~L398). This revision (a) reuses `trend_ok` instead of
> re-deriving it, (b) adds a **piecewise-linear / swing-pivot "graph" method** to solve the
> path-dependent Stage 1↔3 problem that a snapshot CASE statement cannot, and (c) scopes
> flag/wedge pattern detection as an explicit stretch phase reusing the same pivot layer.

## Objective
Classify the market structure of candidate tickers into Minervini's 4 Stages (Stage 1: Basing,
Stage 2: Advancing, Stage 3: Top Area, Stage 4: Declining) to act as a **strategy entry gate**:
deploy only on early/mid Stage 2, strictly avoid late Stage 3 / Stage 4 — regardless of the
M01/M02 score.

**Reframed as a falsifiable test, not an assumed win:** we do not yet have evidence that M01/M02
score high on Stage 3/4 names (the models are momentum/breakout-trained and may already avoid
them). The deliverable must answer: *does an explicit stage gate remove trades the score would
have kept, and do those removed trades have worse forward returns?* If not, we kill the gate.

## Why a "graph" (shape-of-series) method, not just SMA snapshot rules
Stages 2 and 4 are cleanly separable by the SMA stack (Stage 2 = `trend_ok`; Stage 4 = its
downtrend inverse). **Stages 1 and 3 are not** — both show a flat 200-SMA and price chopping the
50-SMA. Minervini distinguishes them by *what came before*: Stage 1 follows a decline, Stage 3
follows an advance. That is **path-dependent** and a per-row CASE statement structurally cannot
separate them.

The fix is a **piecewise-linear trend segmentation** over log-price: reduce each ticker's path to
a small set of straight segments (via swing pivots / PIP), then read the *slope sequence*. A flat
segment **preceded by an up segment** is a top (Stage 3); **preceded by a down segment** is a base
(Stage 1). This is the "graph shape" a technician reads, but stays in the tabular/feature layer —
interpretable, auditable, and cheap. No chart rendering, no CNN, no fabricated image labels.

## Deliverables
1. **Swing-pivot / segmentation layer** (`src/features/trend_segments.py` or SQL) — reusable
   pivot + rolling-slope + R² primitives. *This is the new core; it is also the prerequisite for
   Phase 4 pattern work.*
2. **Stage classifier** — SQL view / column `market_stage ∈ {1,2,3,4}` combining `trend_ok`
   (Stage 2), its inverse (Stage 4), and the segment-slope lookback (Stage 1 vs 3).
3. **Backtest integration** — `market_stage` as a mandatory gate in the vectorized engine /
   Strategy Arena.
4. **Exploratory report** — stage distribution across the SEPA watchlist + forward-return profile
   per stage; falsification test (gated-vs-rejected trade returns).

## Implementation Plan

### Phase 0: Reuse audit (½ day)
- Confirm `trend_ok` semantics (`src/feature_pipeline.py` ~L398) and its threshold choices.
  **Note:** shipped `trend_ok` uses `close > high_52w * 0.85` (within 15% of high); original plan
  said 25%. Adopt the shipped 0.85 definition — do **not** create a second inconsistent one.
- Inventory available inputs already materialized: `sma_50/150/200`, `sma_200_lag20`,
  `price_vs_sma_*`, `dist_from_52w_high/low`, `volatility_20d`, `atr_*`. No new base features
  needed for Stages 2/4.

### Phase 1: Swing-pivot / segmentation primitives (the "graph" method)
Build over data you already have (`price_data` for the raw path; never `shift(-1)` on gappy t3).
- **Swing pivots (ZigZag):** mark local highs/lows using an ATR- or %-threshold so we ignore
  noise wiggles. Reuse `atr_14` / `volatility_20d` for the threshold.
- **Rolling log-price slope + R²** over a ~63d window: slope sign = direction; R² = trend
  cleanliness (proxy for the Stage-3 "choppiness / distribution" the original plan hand-waved).
- **Prior-leg direction:** the path-dependent term that separates Stage 1 from Stage 3.

Output primitives: `pivot_high`, `pivot_low`, `slope_63d`, `slope_r2_63d`, `prior_slope_sign`.

> **AS-BUILT (Phase 1 done — [src/features/trend_segments.py](../../../src/features/trend_segments.py)).**
> `prior_slope_sign` was **redefined** from "slope sign at last pivot" to **sign of the ~1yr
> (252d) log-price change**. Why: a base that drifts flat never reverses sharply, so a
> pivot-anchored prior is undefined exactly when we need it (verified — synthetic drift-flat
> base yielded zero pivots). The long-lookback change is always defined once ~1yr of history
> exists and is independent of base length. Pivots stay in the module for Phase 4, not for this
> term. Path uses `close` not `adj_close` (100% NULL); ATR threshold falls back to 2% on t3's
> ~8.6% null days. Covered by `tests/test_trend_segments.py`.

### Phase 2: Stage classification logic
Compose `market_stage` from the primitives — no new heavy logic. **As-built rule** (function
`compute_market_stage`; NOT wired to orchestrator/materialized table — standalone for evaluation):

| Stage | As-built rule |
|---|---|
| **2 Advancing** | `trend_ok = TRUE` (existing full trend template) |
| **3 Top** | `NOT trend_ok` **and** `prior_slope_sign > 0` (came from an advance) — regardless of current slope |
| **4 Declining** | `NOT trend_ok` **and** `prior_slope_sign < 0` **and** `slope_63d < 0` |
| **1 Base** | `NOT trend_ok` **and** `prior_slope_sign < 0` **and** `slope_63d >= 0` |
| *NULL* | `prior_slope_sign` undefined (first ~1yr warmup) — do not guess |

> **DECISION — asymmetric, not a symmetric 2×2.** The original sketch keyed both Stage 1 and
> Stage 3 off the (prior × current) slope pair. As-built, **prior-up always → Stage 3, never
> Stage 1.** The stage cycle is directional (1→2→3→4→1): a name cannot go advance→base without
> first topping and declining, so a non-`trend_ok` row that *came from an advance* is a top,
> period. Stage 1 is reachable only from a prior decline. A synthetic flat-top test caught the
> symmetric version mislabelling a top as a base — the single most dangerous error for an entry
> gate. `slope_63d` sign now only splits the prior-**down** side (still-falling 4 vs turning 1).

> **VALIDATION SO FAR (8-ticker sample 2018–2025, `scripts/validate_market_stage.py`).**
> All internal cross-checks pass: trend_ok contradictions = 0; breakout rate peaks in Stage 2
> (28% vs 9–12%); independent `m03_pillar_trend` ranks monotone **4 (51) < 3 (65) ≈ 1 (67) <
> 2 (76)**; distribution 13/26/41/21% (non-degenerate). 3/3 hand-picked sanity labels correct
> incl. GME Feb-2021 top-vs-base.
> **⚠️ Weak seam:** Stage 1 vs 3 are the *least distinct* pair (m03 67 vs 65; breakout 11% vs
> 12%). Separated, but barely. Phase 3's forward-return test must adjudicate whether the split
> earns its keep.

If Stage 1↔3 separation proves unreliable in the Phase 3 forward-return test, **collapse to a
3-state** `{downtrend / neutral / uptrend}` classifier and say so explicitly — do not ship a
mislabelled top-as-base.

### Phase 3: Validation & backtest integration (the falsification test)
- Sanity-check against known historical stage charts. **Mechanism ready:**
  `scripts/validate_market_stage.py --labels labels.csv` (columns `ticker,date,expected_stage`)
  scores predicted-vs-expected. No external ground-truth stage dataset exists (Minervini/Weinstein
  stages are discretionary; 3rd-party "stage" indicators are the same SMA-stack heuristic → circular).
  Forward return is the real arbiter; hand labels + TradingView eyeballing are the sanity layer.
- Compute `market_stage` across the candidate universe; report the stage distribution.
- **Falsification test:** split current candidate trades into *gated (Stage 1/2)* vs
  *rejected (Stage 3/4)* and compare **forward-return distributions in the vectorized backtest**.
  The gate is justified only if rejected trades are materially worse. (Precision@50 alone conflates
  "filter helps" with "model was already fine" — use the WFO/optimizer infra, e.g.
  `scripts/run_strategy_wfo.py` / the Optuna optimizer, to gate overfit.)
- If justified, wire `market_stage` into the parameter optimizer for final strategy evaluation.
- **Casing guard:** if `market_stage` ever becomes an M01 model feature it MUST be added to
  `COLUMN_CASE_MAP` in `view_manager.py` (prior XS-rank casing bug). If it stays a backtest-only
  gate, keep it out of the model feature set entirely.

### Phase 4 (STRETCH): Flag / wedge / triangle detection — reuses the pivot layer
Same swing-pivot layer, extended: fit **separate trendlines to swing-highs and swing-lows** over a
5–30d window, then classify by the (upper-slope, lower-slope) pair:
- Bull flag: parallel, both down, after a sharp "flagpole" up-move.
- Falling wedge: both down, converging (lower steeper). Rising wedge / triangles: sign+convergence variants.

**Explicitly gated, not assumed.** Classical geometric pattern detection is low-precision and
prone to look-ahead bias (only "seeing" the flag after the pole; peeking at the breakout to
confirm). Ship a detector ONLY behind the same forward-return test as Phase 3 — the detected
pattern must precede excess return before it enters the strategy. Treat as exploratory; do not
block Goal B on it.

*(Deferred entirely: chart-image CNNs / Elliott-wave counting. They fabricate labels, discard
clean numeric features, and produce a black-box gate — wrong trade-off for a discipline filter.
Revisit only if the shape-of-series approach demonstrably fails, as its own sprint.)*
