# M4 smoke build — magnitude regressor WFO on the trades grain (mechanism REAL but PRO-CYCLICAL)

**Date:** 2026-07-08 · **Status:** ✅ SMOKE BUILT + RUN (11 WFO folds, trades grain) — acceptance
bar (bad-regime floor) settled cheaply; no expensive full-universe sweep needed.
**Answers:** meta-question **M4** (build phase). Design: `verdicts/2026-07-07_m4_magnitude_regressor_design.md`.
**Harness:** `docs/session_logs/sprint_14/scripts/m4_wfo_taillift.py` · **Results:**
`data/model_output_eda/m4_wfo/wfo_{champion,A,B}.csv` · **Fold models (NEW version, never touched
shipped v1):** `models/m01_prototype_wfo/v1/{target}_fold_YYYY_YYYY.json`.

---

## 0. What the design got wrong about the plumbing (verified against DB/artifacts, not prose)

The design said "re-cut the champion bar on `mfe_pct` = one-column swap on the existing multi-year
cache." **False.** Verified:
- `data/model_output_eda/multiyear/raw_full_*_fwd.parquet` carries **`fwd20` only** (close-to-close
  from `price_data`), + 10 EDA features. **No `mfe_pct`, not the training feature set.** It is the
  FULL-UNIVERSE population.
- `mfe_pct` lives on the **SEPA-TRADES grain**: `d2_training_cache` (= `v_d2_training`), 38,556
  breakout-trade rows, 2000–2026, `mfe_pct` fully populated (med 7.3, max 2262), 96/97
  `fs_m01_prototype` features present (missing `atr_pct_chg`, a case/derivation gap).
- **This IS m01_prototype's own training population** (`train_mfe_classifier.py`: `v_d2_training`,
  `mfe_pct IS NOT NULL`, target `create_mfe_labels(mfe_pct,[2,10,30])` 4-class softprob). So the
  trades grain is m01's home, not a compromise — M4 = the identical loader/features/rows, target swap.
- **Shipped prototype = `no_holdout_85_15_0`, test_samples=0** → it saw all 38k rows. In-sample
  scoring = inflated bar. **So the bar must be WALK-FORWARD** (expanding train, retrain per fold,
  score OOS fold). Champion AND M4 judged the same WFO way. (user-approved this path.)

Net: the "cheap cache re-slice" was actually a model-level WFO harness build — done this session.

---

## 1. Setup

- **Population:** trades grain (`d2_training_cache`, `mfe_pct IS NOT NULL`), 38,556 rows 2000–2026.
- **WFO:** expanding train, 2-year OOS test folds. 11 folds tested: 2005–07 … 2025–27. Pre-2005 too
  thin per-fold → seeds first train set.
- **Three targets** (all rank names by "expected tail", scored on OOS `mfe_pct`):
  - **champion** — 4-class softprob (`[2,10,30]`), score = P(class 3 = Elite). Same params as shipped.
  - **A** — winsorized-magnitude regressor (`reg:squarederror`, `mfe_pct` clipped p99). The design's
    "null control."
  - **B** — τ=0.90 quantile regressor (`reg:quantileerror`). The design's PRIMARY thesis.
- **Metrics** (M1's, on `mfe_pct`): tail-lift@k (top-1/5/10% share of Σmax(mfe−30,0) ÷ k) and
  **`cond_lift10`** = tail-lift within the top-decile of score = *does the score rank magnitude
  AMONG already-elite names?* — the M4 mechanism.

---

## 2. Result — the mechanism is real in good regimes, DEAD in crashes

### Good-to-middling years (7 folds, 2013–2026)
| target | lift@1% med | lift@10% med | **cond@top10 med** | cond <1× |
|---|--:|--:|--:|--:|
| champion | 4.51 | 3.49 | 1.29 | 3/7 |
| **A** | **6.97** | 3.48 | **2.08** | **1/7** |
| B | 4.27 | 3.36 | 1.39 | 3/7 |

→ **A (the "null control", NOT the thesis) wins the mechanism metric:** it ranks the tail within the
elite pool (cond 2.08) where the classifier can't (1.29). B (τ=0.90 quantile, the *designed primary*)
**ties the champion** — best_iter collapses to 0–3 in several folds, the quantile loss barely learns.
**Design's bet on WHICH target wins was wrong: the plain winsorized regressor beat the fancy quantile.**
lift@10% (broad basket) is a dead-heat for all three — the magnitude edge is specifically at the
EXTREME top / within-elite, exactly where a top-5 strategy lives ([[project_capital_deployment]]).

### The bad-regime floor — GFC fold 2007–2009 (M4's REAL acceptance bar)
| target | lift@1% | lift@10% | cond@top10 |
|---|--:|--:|--:|
| champion | **0.37** | 1.70 | 0.22 |
| A | **0.43** | 2.06 | **0.21** |
| B | 0.64 | 0.83 | 0.78 |

→ **ALL THREE below no-skill (lift<1×) in the 2007-09 fold.** A — the overall winner — is *just as weak
as the champion here* (cond 0.21). Tempting to call this "pro-cyclical, dies in the crash" (matches M1)
— **but that split is NOT rigorous, see the caveat below.**

⚠️ **The "good vs bad years" split is HAND-PICKED, post-hoc, CIRCULAR.** I labelled 2007-09 "bad"
because it was the only cond_lift10<1× fold — i.e. split BY the outcome I was measuring, not by an
independent regime label (which we don't have yet — [[project_regime_during_period_goal]]). Looking at
all 11 folds, cond_lift10 is just NOISY (A: 0.21–3.41): **two calm-year folds (2009-11 = 0.48,
2013-15 = 0.48) are nearly as weak as the GFC**, and 2015-17 (calm) is 3.41. So "edge in good regimes,
dies in crashes" is OVER-STATED — the honest read is *the metric swings a lot fold-to-fold; the single
worst fold happens to be the GFC, but I cannot yet attribute the weakness to regime vs noise.* A proper
regime label (the during-period-behaviour goal) is needed to test the pro-cyclicality claim non-circularly.

---

## 3. Verdict

**M4's mechanism shows up (A ranks tail within the elite pool, median cond_lift10 1.73 vs champion
1.29 over 11 folds) but is NOISY and NOT cleanly attributable to regime.**
- *Does conditional magnitude rank among elite names?* On the pooled median, **yes for target A** (1.73
  vs 1.29). But fold-to-fold it swings 0.21–3.41 and fails 3/11 folds — the edge is real-on-average,
  fragile-per-fold. The "only in good regimes" framing is not yet supportable (circular split, above).
- A plain winsorized-magnitude regressor (A) adds real within-elite tail ranking the 4-class
  classifier throws away, on average — but not reliably in every fold.
- The 2007-09 fold is <1× for all three, but (see caveat) I can't cleanly call that a regime effect.
- The τ=0.90 quantile thesis (B) is separately falsified — it ties the champion everywhere.

**This did NOT need the expensive 25-year full-universe re-score.** The design gated the bad-year
answer behind that sweep; but `d2_training_cache` (the table m01 already trains on) is small and fully
cached, so 4 more early-fold retrains (seconds) answered it directly. The full-universe sweep tests a
*different* population/outcome (`fwd20`, not the family's `mfe_pct`) — wrong instrument for this question.

---

## 4. What's next (if M4 is pursued — NOT auto-approved)

Blocked upstream: **we have no quantified good/bad regime label yet** ([[project_regime_during_period_goal]]),
so both the "is it pro-cyclical" question AND regime-reweighting are un-runnable — you can't weight by
a label you don't have (user, 2026-07-08 — reason to DEFER reweight).
1. **eval-stratify:** done here, but the split was circular (hand-picked GFC) — needs a real label first.
2. **reweight bad-year rows — DEFERRED** until the regime state-expression exists to weight by.
3. **Population: keep M4 on breakout events (`d2_training_cache`) — but for a MANDATE reason, not a
   data-availability one (2026-07-08).** First `d2_training_cache` (38.5k) IS the SEPA watchlist — matches
   `screener_watchlist` row-for-row, 99% inside `v_sepa_candidates`; the smoke already ran on the live
   rank/gate population, nothing to filter DOWN to. The real question (per [[feedback_target_invariant_enrich_dont_substitute]])
   is: *would EXPANDING to the wider daily pool (`v_sepa_candidates`, 126k) make M4 BETTER?* Answer: **no,
   and now PROVEN from the data (2026-07-08), not just argued by analogy.** The 88k extra rows
   (v_sepa minus d2) are the days a name is SEPA-eligible but NOT breaking out — and **100% of them fall
   AFTER the ticker's first breakout** (verified). They carry HIGHER forward return than breakout days
   (median return_20d 12.9% vs 8.2%, P(r20>30%) 11.7% vs 4.0%) — but that is POST-BREAKOUT SURVIVORSHIP/
   CONTINUATION (conditioned on the trend already surviving), NOT an exploitable fresh-entry signal.
   Training M4 on them would (a) teach "already-run names keep running" = a HOLDING/TIMING statement
   (m01_rank's job, found weak — [[project_m01_two_model_system]]), and (b) silently bias M4's target
   distribution upward with look-ahead-flavored survivor rows — an honest-looking wrong result the
   charter's result-honesty bar rejects ([[feedback_standards_charter]]). So keep M4 on the breakout-event
   grain. ⚠️ The wider pool lacking `mfe_pct` is NOT the reason (we'd ENRICH, never substitute
   `return_20d` — [[feedback_target_invariant_enrich_dont_substitute]]); the reason is the population is
   CONTAMINATED for a selection target. The one flip: a deliberate daily-ranked-watchlist PRODUCT (M5)
   is a different model built for that mandate — not M4 with continuation days dumped in.
4. Target C (`max(mfe−30,0)`, sparse) — skip; A already beat B, C is the sparser cousin of A. YAGNI.

## ⚠️ Caveats
- **lift@1% is high-variance** (A: 1.9–12.0 across folds; top-1% of ~3–4k = ~35 names, a few
  home-runs swing it). `cond_lift10` (median-based, 11 folds) is the robust read, not lift@1%.
- Everything is directional `mfe_pct` — **no exits/sizing/liquidity; MFE is optimistic** (a +400%→
  round-trip still books its peak). Not tradable P&L.
- Fold models write to `models/m01_prototype_wfo/v1/` — a NEW version, shipped
  `m01_prototype_2003_2026/v1` untouched. They are throwaway (regenerable in ~15s by re-running the
  harness), so **deleted at session end** — the durable evidence is `data/model_output_eda/m4_wfo/wfo_*.csv`
  + this verdict.
- id `m04_regressor` was the design's planned lane; **no `m04_regressor/` artifact was created** — the
  smoke ran under the WFO harness only. Promote to that id only if regime-conditioning revives it.
