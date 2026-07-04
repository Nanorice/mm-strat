# Goal A3 — m02_breakout as its own strategy (plan)

> **Purpose:** lay out tomorrow's build so it's obvious what to write and what NOT to.
> m02_breakout is a validated-OOS ignition ranker (P@50≈50%, IC +0.37) that has **never
> been backtested**. This plan evaluates it on the two jobs it was actually designed for —
> NOT the M01 top-3/SMA50 momentum-hold strategy (wrong test).
>
> Companion strategic frame: the "Heavily Manual Strategy Arena" TODO (strategy taxonomy,
> sizing/regime, M03's fate) — see §5. A3 is the concrete first tile of that larger board.

## 0. Two decisions that shrink the work

**(a) m02 end-state = ONE model trained on all periods, not walk-forward.**
The 5 WF folds were the *validation* geometry (they proved OOS edge: P@50≈50%, IC +0.37) — a
record, not a deliverable. The **deployable artifact is a single booster fit on all data**
(`2016 → present`). This is also what makes scoring trivial: **one booster, one clean pass over
the panel, no fold-routing, no leak bookkeeping.** Add a `--final` flag to
`scripts/train_breakout_model.py` that trains on `[train_start, test_end]` and saves
`models/m02_breakout/<run>/model.json` (+ `metadata.json` with the feature list). The WF path
stays for the validation summary; `--final` produces the thing we actually use.

> ponytail: `--final` is ~15 lines reusing the existing `load_matrix`/`_prep_cat`/`_XGB_PARAMS`.
> No new script. The WF eval already ran and is banked — we don't re-validate, we just fit-final.

**(b) "adapter" — the raw output is the score; there is no scorer class.**
The engine takes an injected `precomputed_scores` DataFrame (`date,ticker,prob_elite,
calibrated_score`) and bypasses `UniverseScorer` entirely — same slot m01_prototype uses
(`run_model_arena.py:66`). With the full-fit model (a), the score loader is a **~20-line pass**:
run `model.json` over the feature matrix → rename `breakout_proximity → prob_elite`,
`calibrated_score = prob_elite`. No WF fold-routing (that complexity is gone with (a)).

**Strategy vocabulary (rebalance/enter/exit/size) is model-agnostic — documented once in the
[backtester manual](../../architecture/backtester_manual.md), not here.** A3 only needs the ONE
strategy-type delta: a **short-hold exit** (M01's SMA50/252d is a long momentum hold = wrong job
for a breakout trade). See manual §5 (`exit_policy` switch) and §2 below.

## 1. Deliverables (tomorrow)

0. **`train_breakout_model.py --final`** — single all-period booster → `model.json` (decision a).
1. **`scripts/score_m02_breakout.py`** — ~20-line loader: `model.json` over the feature matrix →
   panel `date,ticker,prob_elite,calibrated_score`. Cache to
   `models/m02_breakout/<run>/score_panel.parquet`.
2. **Short-hold exit in the vectorized engine** (§2) — smallest change that adds the new exit
   without breaking the M01 path. One `assert`-based self-check.
3. **`scripts/run_m02_breakout_backtest.py`** — thin driver: load score panel → run engine
   under the two job configs (§3) → emit metrics + report to `models/m02_breakout_bt/`.
   Mirrors `run_model_arena.py` structure; do NOT fold m02 into the M01 arena.

## 2. The exit policy — the one real design choice

m02_breakout predicts *proximity to ignition*, so the trade thesis is "enter as it ignites,
capture the ignition move, get out." Candidate exits, in build order (ship the simplest that
shows signal, question the rest):

- **E1 — fixed N-day hold** (`max_hold_days = N`, N∈{5,10,21}; keep stop_loss, DROP SMA50).
  The laziest honest version of "short hold, exit shortly after breakout." Ship this first.
- **E2 — ATR trailing stop** — reuse `atr_14`; trail from entry. Tighter than SMA50, respects
  the short thesis. Only if E1 shows the entry has edge but the flat exit leaves money.
- **E3 — exit-on-breakout-confirmation** — exit when the SEPA watchlist entry actually fires
  (the event the score predicts). Cleanest test of "did the ignition happen," but needs the
  `sepa_watchlist` join in the exit path — more plumbing. Defer unless E1/E2 justify it.

> ponytail: build E1 only tomorrow. E2/E3 are add-when-E1-shows-edge, not up front.
> Implement as an `exit_policy` arg on the engine (`'sma'` default = current M01 behaviour,
> `'nday'` = new), NOT a new class — the M01 path stays byte-identical.

## 3. The two jobs → two backtest configs

**Job 1 — breakout trade (short hold).** Score panel drives selection; E1 exit.
`min_prob_elite` = a high proximity cut (sweep, e.g. top-decile of the score); short hold;
same sizing. Question answered: *does entering the top ignition-proximity names and holding
briefly beat random / beat M01 over the same window?*

**Job 2 — earlier-entry signal (head-start test).** This is a *timing* question, not a
strategy per se: for names that later enter the M01 watchlist, how many days earlier did
m02_breakout cross a high-proximity threshold? Measure the **lead time distribution** and the
forward return from the m02 signal date vs the M01 entry date. Mostly an analysis notebook /
script over the score panel + `sepa_watchlist`, not the trade engine. Cheaper than Job 1 —
consider doing it FIRST as a signal-quality gate before committing to the trade build.

> Lazy ordering: Job 2 (lead-time analysis) is a few joins and answers "is there even a
> head-start?" If the lead time is ~0 or the early signal doesn't precede return, Job 1's
> trade build isn't worth it. Do Job 2 → decide → then Job 1.

## 4. Reuse map (what already exists — do not rebuild)

- **Score injection slot:** `VectorizedSEPABacktest(precomputed_scores=...)` + `metrics()`.
- **Fold geometry / feature load:** `train_breakout_model.py::load_matrix/_prep_cat` +
  `src/evaluation/walk_forward.py::anchored_walk_forward`.
- **WFO gate (if Job 1 shows edge):** `run_strategy_wfo.py` already accepts injected scores —
  gate the m02 strategy OOS the same way M01 was.
- **Sizing overlay:** `src/backtest/macro_sizer.py` (VIX works, M03 no-op) — orthogonal, add last.
- **Metrics/equity:** honest bar-by-bar `equity_curve` — unchanged.

## 5. The bigger board (the "Heavily Manual Strategy Arena" TODO) — parked, framed

A3 is one tile. The strategic questions you raised, noted so they're not lost but NOT started:
- **Strategy taxonomy:** breakout (m02_breakout, short hold) vs swing vs long momentum-hold
  (m01). Each is a distinct (enter, exit, hold) tuple on the SAME engine — the exit_policy arg
  (§2) is the seam that lets them coexist.
- **Sizing / regime overlap with M03:** already partly answered — VIX-banded sizing adds value,
  **M03-banded is a no-op** (`run_sizing_experiment.py` finding). Open question *is M03 retired
  or replaced by the new macro params?* — decide as its own step, evidence already points to
  "M03 doesn't earn its keep as a sizing lever." Don't relitigate here.
- **"Not idiosyncratic — all tickers share the feature, how does this help?"** Correct and
  important: macro/regime sizing is a **portfolio-level exposure dial**, not a stock selector.
  It can only time *how much* capital is deployed, never *which* names. That's exactly why it
  belongs in the `exposure` series (sizing), not the score (selection) — the engine already
  separates them. This is the right mental model; A3 keeps them separate by construction.

## 6. Definition of done (A3)

- [ ] Leak-free m02_breakout score panel cached.
- [ ] Job 2 lead-time analysis → go/no-go on Job 1.
- [ ] (if go) E1 short-hold backtest vs M01 baseline over the common window, honest Sharpe.
- [ ] Verdict written to sprint summary A3: does m02_breakout earn a live slot, or park it?
