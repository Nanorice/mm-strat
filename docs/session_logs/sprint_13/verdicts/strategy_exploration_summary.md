# Strategy Exploration — Summary (Sprint 13, 2026-07-05)

> ⚠️⚠️ **POPULATION-INFLATED — the champion here is SUPERSEDED (2026-07-09).** This whole arena selected
> top-5 from the ~99% off-setup scored panel (no `trend_ok AND breakout_ok` gate at selection). On the
> corrected SEPA-gated population, minervini+progressive-fills beats even the re-derived honest sma across
> the start-date cone (%neg folds 25→5%, worst fold −1.30→−0.09). The `sl15×tpTight` champion below is
> retired. See `../../sprint_14/verdicts/2026-07-09_m2_minervini_vs_sma_gated_cone.md` +
> `../../sprint_14/plans/population_rectification_plan.md`. The *methodology* (kill selection red
> herrings, edge is in exits, gate on the cone) still stands — only the population and the champion config
> were wrong.
>
> **The question that drove the day:** is the M01 edge in *what* we pick (selection) or *how/when* we
> trade it (timing/exits)? We started from a clever rotation design and stripped it down by
> falsification until only the load-bearing mechanic remained. **Answer: the edge is in the EXITS.**
>
> Companion runnable cells: [strategy_exploration_cells.md](strategy_exploration_cells.md) /
> `notebooks/s13_rotation_strategy.ipynb`. Results analysis: [backtrader_analysis_cells.md](backtrader_analysis_cells.md).

---

## The journey at a glance — each step and its conclusion

Read top-to-bottom this is the whole arc; every row's detail is a section below. The through-line:
**kill the seductive selection ideas → find where the edge actually lives (exits) → prove it doesn't
overfit the fold split → then stress it on the axis the split-gate can't see (start-time).**

| # | Step | Conclusion (one line) |
|---|---|---|
| 0 | **Rotation prototype** (delayed entry + score-drop exit + $25k rebalance) | The starting "trade the signal cleverly" hypothesis. Everything below strips it away. |
| 1 | **Delayed entry** (E2, wait 1–5d for a pullback) | ❌ **FALSIFIED, monotone** (+405%→−32%). The alpha *is* the day-0 breakout; there is no paying pullback. |
| 2 | **Rotation / score-drop exit** (sell decaying scores) | ❌ **FALSIFIED** (−0.05). Fights A3 non-monotonicity — sells names that mean-revert up. Don't rotate on score. |
| 3 | **Persistence** (require sustained rank, not a spike) | ❌ **FALSIFIED** (−0.86). The signal is *fresh*, not smoothed. Same lesson as delay. |
| 4 | **Is the seed overfit?** (walk-forward OOS on E1) | ✅ **Not overfit** — IS ~2.0 → OOS 0.84. Fold decay is 2026-chop weakness, not curve-fit. |
| 5 | **Selection sweep (vectorized)** | ⚠️ **Rank-only** — the vec engine lacked a slot book + bear-gate, so its absolute Sharpes sign-flipped vs BackTrader. |
| 6 | **Fix the vec engine** (`regime_gate` + `max_concurrent_positions`) | The dominant gap was phantom concurrency (≤19 on a 5-slot book). Fixing it **reversed** the N-ranking — "widen N" was a dilution artifact. |
| 7 | **BackTrader confirm** (5-arm vec shortlist on the fidelity engine) | ✅ **Seed binary E1 top-5 wins outright** (0.87). Vec can't rank across signals — it can't see the 3-tranche TP. `skip_top` = a narrow DD tool only. |
| 8 | **Exit grid** (16 arms: stop width × TP timing × SMA) | The "stop" is a **profit-LOCK, not a loss-cut** (avg PnL *at stop* is positive). `atr_stop_mult` proved **inert** (dropped). The edge lives in the exits. |
| 9 | **Tier-3 interaction + OOS gate** (stop-width × TP-timing) | ✅ **NEW CHAMPION** `sl15×tpTight`: IS 1.10, **OOS-gated 1.47**. Each half *alone* loses to the seed; together they win — a marginal sweep would have missed it. |
| 10 | **Productionisation** (registry + OOS gate + shared runner) | The champion becomes a named, fingerprinted, regression-tested config — not a kwargs dict in a script. |
| 11 | **Start-time sweep** (locked champion × 53 rolling start dates) | ⚠️ **Regime ride** — 12m ann_return swings **−39%..+197%**, 17/53 Sharpe-negative. The fold-gate proved "not overfit to the split"; this proves "still fragile to *when* you start." |
| 12 | **Forward shadow book** (parity-gated `step()` engine) | The live check for a start-conditional edge is a **paper shadow**, not a number. Steps 1–5 shipped, parity green; nightly wiring deferred until a start date is chosen. |

**The one sentence:** *selection was a red herring; the edge is a wide-stop / early-partial exit
interaction that survives an honest OOS split but rides the market regime — so we trade it forward on
paper, gated, and size only after a friction re-run and a real forward quarter confirm it.*

---

## The champion we trade forward

| Component | Setting | Fingerprint |
|---|---|---|
| Signal | m01_binary, top-5 by `prob_elite` | `S0.top5` |
| Entry | immediate on qualify, day-0 (no delay) | `E1.d0` |
| Stop | **15% whole-position trailing** (ATR mult inert → dropped) | `X1.sl15` |
| Take-profit | **early T1 at +10%**, then staged (T2 +2ATR, T3 SMA50) | `Xt.t1_10` |
| Trend exit | decoupled SMA50 (close<SMA ⇒ out) | `X3.sma50` |
| Regime | M03 strong-bear (score<15) hard-liquidates | gate |

`E1.d0_X1.sl15_Xt.t1_10_X3.sma50_S0.top5` — IS **1.10 Sharpe / +861% / −45% DD**;
**OOS-gated 1.47 Sharpe / +245% / −28% DD** across 3 unseen rolling folds. Beats the prior seed on
every OOS metric, no IS→OOS collapse. Lives in `strategy_registry` as `champion` (single source of
truth); **not** written into `SEPAFlatV1` defaults (that class carries a different live default set —
overwriting would be a silent regression).

### What the numbers do and don't mean (read before believing them)

- **These are 2021–2026, $25k, microcap-heavy backtest numbers — NOT a forward forecast.** Universe
  skews small/illiquid (entry $5–20: ANVS/CRNC/PSNL). Slippage, borrow, capacity at size will erode
  this; +861% is a *ranking* signal, not a P&L promise.
- **The whole edge is ONE mechanic: the trailing stop is a profit-LOCK, not a loss-cut** — 90% of
  exits are the raised stop giving back a little on a winner (avg PnL *at stop* is positive). Ride
  breakouts, trail out. If that mechanic degrades (regime, liquidity), the edge degrades with it.
- **It is exit-driven and capacity-bound.** ~92–95% day-over-day name overlap; the 5-slot book, not
  the pick, is the binding constraint (rejection audit dominated by `no_slots`). "Rebalance less" is
  an exit lever, not a selection lever.
- **The OOS gate is 3 folds and 2024 was flat (+0.12).** Promising and honestly gated, NOT proven.
  Treat the live slot as **paper/small-size probation**, not an allocation.
- **⚠️ It is start-time dependent** (step 11): same 12-month hold, ann_return swings −39%..+197% by
  start month. The honest forward expectation is a *distribution over start dates*, not the +245%
  headline. Does not falsify the champion; reframes what "trade it" means.

---

## Reference: the fingerprint scheme

A strategy = **entry** + **stop (SL)** + **take-profit (TP)** + **selection**. Each component has a
stable **index** (E1, X1, …) and a **grid suffix** for its knob. The name *is* the definition and
parses back to engine kwargs (`strategy_registry.parse_fingerprint`).

`<Entry>_<Stop>_<TP>_<Selection>` — e.g. the champion `E1.d0_X1.sl15_Xt.t1_10_X3.sma50_S0.top5`

| Family | Index | Meaning | Grid suffix (examples) |
|---|---|---|---|
| **Entry** | `E1` | immediate on qualifying | `.d0` (delay 0d) |
| | `E2` | delayed + return-band | `.d3` `.d1` … + band `.b-5+15` |
| **Stop (SL)** | `X1` | wider-of(N·ATR, %) whole-position stop | `.sl10` `.sl15` |
| | `X4` | pure ATR stop (% floor disabled) | `.atr2` `.atr2.5` |
| **Take-profit** | `X3` | SMA/trend exit (decoupled) | `.sma50` `.sma20` |
| | `Xt` | 3-tranche targets (T1 +% / T2 +2ATR / T3 SMA) | `.t1_10` `.tranche` |
| | `X2` | score-drop / rotation exit | `.drop08` `.floor10` |
| **Selection** | `S0` | top-N by score | `.top5` |
| | `S1/S2/S4` | random from top-decile / quartile / all | `.rndD` `.rndQ` `.rndA` |
| | `S3a/S3b` | trailing-avg / cohort-pct persistence | `.avg10` `.pct10` |
| | `S5` | bottom-N (anti-signal control) | `.bot` |
| | `skipK` | drop the top-K ranked before slot-fill | `.skip2` |

---

## Steps 1–4 — the selection/timing ideas, falsified

**Window:** 2021-01→2026-05 (incl. 2022 bear), $25k, top-5 equal-weight, m01_binary unless noted.
Proto rows are the 2025-10→2026-05 bull window (regime-flattered — *illustrative only*).

| Fingerprint | What it tests | Signal | Sharpe | Total ret | maxDD | Verdict |
|---|---|---|--:|--:|--:|---|
| `E1.d0_X1.sl10_X3.sma50_S0.top` | **the seed** (pre-exit-grid baseline) | binary | **0.86** (WFO OOS **0.84**) | +404.8% | 50.8% | ✅ baseline — later beaten by the champion |
| `E2.d3.b-5+15_…_X2.drop08_…` | rotation (delay+score-drop) | binary | −0.05 | −31.9% | 63.8% | ❌ falsified |
| `E2.d1.b-15+30_…` | delay 1d only | binary | 0.13 | −5.0% | 71.4% | ❌ delay kills it |
| `E2.d2/d3/d5…` | delay 2/3/5d | binary | 0.07 / 0.03 / −0.04 | −17 / −23 / −32% | ~73% | ❌ monotone decay |
| `…_S3a.avg10` | trailing-avg persistence | proto | −0.86 | −23% | 37.7% | ❌ wants fresh score |
| `…_S5.bot` | bottom-N anti-signal | proto | −0.81 | −6% | 95.1% | ✅ correctly bad (control) |
| `…_S0.top` | top-N (incumbent sorter) | proto | 1.01 | +25% | 21.3% | baseline |
| `…_S1/S2/S4.rnd*` | random top-decile/quartile/all ×8 | proto | −0.08 / 0.44 / 0.50 | — | — | ⚠️ tail-polluted; ≈ topN |

**Conclusions:**
1. **Rotation / score-drop exit — FALSIFIED.** E2 < E1 on every window and year incl. 2022 bear. The
   `score_drop` exit fights A3 non-monotonicity (sells names that mean-revert up); churns ~48% of
   E2's exits for no offsetting edge.
2. **Delayed entry — FALSIFIED, monotone.** +405% (0d) → −5% (1d) → −32% (5d). Immediate entry
   captures the 2022/2023 ignition breakouts; any delay turns those exact years deeply negative and
   blows maxDD to ~73%. **The alpha is the day-0 breakout — there is no paying pullback.**
3. **Persistence — FALSIFIED.** Smoothing the score destroys the edge (−0.86). The signal is *fresh*,
   not sustained — same lesson as delay.
4. **E1 seed is not overfit — WFO OOS 0.84.** IS ~2.0 → OOS 0.84, matching the known steady-state.
   Fold decay (2.27→0.69→−0.16) is 2026-chop weakness, not curve-fit.
5. **Turnover is exit-driven, not selection-driven.** ~92–95% day-over-day name overlap across *all*
   selection rules → "rebalance less" is an *exit* lever, not a *pick* lever. **This is the first
   signpost that the edge is in the exits.**

## Steps 5–6 — the vectorized selection sweep, and why its first answer was wrong

Ran the selection family on the fast vectorized engine (both signals, matched 2021–2026 horizon).
Scores cached to `data/score_cache/{binary,proto_cali}_2021_2026.parquet`; results in
`data/selection_sweep/` (`summary.parquet`, `summary_fixed.parquet`, per-run `trades/*.parquet`).

**⚠️ The first run's absolute Sharpes were a sign-flip, not an error bar** (`gap_check_*.json`):
E1 binary read **0.04 / −34.5%** on vec vs **0.86 / +405%** on BackTrader. Two engine bugs, fixed in
`vectorized_backtest.py`:

1. **`regime_gate`** (M03 strong-bear → block entries + zero return). *Minor:* E1 Sharpe 0.03→0.07.
2. **`max_concurrent_positions`** (greedy slot-book). **The dominant gap** — without it, top-N *new*
   entries/day × ~25-day holds → **up to 19 concurrent** on a nominal 5-slot book; the equity curve
   pro-rata-diluted winners to nothing. With `cap=5`, E1 binary recovers to +0.34 / +37% / −55%.
   Exits are path-independent, so the greedy pass is exact. Test:
   `test_capacity_gate_blocks_over_subscription`.

**The fix reordered the findings — the old "widen N to 8–10" was a dilution artifact**
(`summary_fixed.parquet`, absolute signs now trustworthy):

| signal | arm | N | Sharpe | ret | maxDD | read |
|---|---|--:|--:|--:|--:|---|
| binary | topN | **5** | **0.34** | +37% | −55% | binary peaks at N=5 |
| binary | topN | 8 / 10 / 15 | 0.29 / 0.30 / −0.38 | — | — | wider = worse (N=15 negative) |
| **proto_cali** | **cap_skip2** | **10** | **0.80** | +217% | **−32%** | vec winner — skip top-2, hold wide |
| proto_cali | topN | 3 | 0.85 | +478% | −52% | return-chasing outlier, uninvestable DD |

**Conclusions:** binary is a weak signal for this strategy that peaks at N=5; `cap_skip2` (skip the
spent top-2) is real *only* on the wide-spread proto (p99 0.60), neutral on compressed binary (p99
0.29) — the A3 tail-pollution edge exists only where ranks actually separate. **Vec is a valid
*within-signal* screen; it cannot rank across signals** (next step shows why).

## Step 7 — BackTrader confirm: the seed beats the vec winner

Ran the 5-arm shortlist through BackTrader (`run_strategy_confirm.py`, parallel,
`data/selection_sweep/backtrader_confirm/`). A1 reproduced the prior E1 champion exactly (0.871 vs
known 0.86) → **harness is faithful.**

| Rank | arm | Sharpe | ret | maxDD | vec said |
|---|---|--:|--:|--:|--:|
| **1** | **A1 binary top-5 (seed)** | **0.87** | +418% | 50.8% | 0.34 |
| 2 | A2 proto top-5 | 0.59 | +170% | **80.9%** (worst) | 0.43 |
| 3 | A4 proto skip-2 @ N=10 (vec winner) | 0.59 | +141% | **45.5%** (best) | 0.80 |
| 4/5 | A5 proto skip-2 @ N=8 / A3 proto top-10 | 0.54 / 0.51 | +121 / +112% | 46.8 / 57.7% | 0.76 / 0.51 |

**Conclusions:**
1. **The binary seed wins outright** (0.87, not close). Vec over-ranked proto because it **lacks the
   3-tranche staged TP** — binary's edge IS the staged profit-take on day-0 breakouts, visible only to
   the fidelity engine. That residual was the whole vec↔BackTrader gap.
2. **`selection_skip_top` is a DRAWDOWN tool, not a return tool** — on proto, skip-2 vs plain top-10
   is 0.59 vs 0.51 Sharpe AND maxDD 45.5% vs 57.7%. Shipped/tested as a candidate DD lever, no-op on
   binary.
3. **Lesson: vec ranks *within* a signal, never *across* signals/exit-styles.** Take those to BackTrader.

## Step 8 — exit grid: the edge is a trailing profit-lock

16 arms off the seed (`--grid exit`, `data/selection_sweep/exit_grid/`; every trade + rejection
cached). **Nothing beat the seed here (0.87)** — but the grid was diagnostic:

| arm | Sharpe | note |
|---|--:|---|
| **G0 seed** | **0.87** | local optimum |
| G_atr2p5 / G_atr3 | 0.86 | **byte-identical to seed → ATR-mult is INERT** |
| G_tp_t1atr2 / G_tp_tight | 0.79 / 0.76 | tighter TP → win-rate 42%, not more Sharpe |
| G_sl15 | 0.75 | widest stop — credible, higher win-rate (**flagged for Tier 3**) |
| G_tp_gated | 0.67 | decoupled SMA beats gated (confirms E1 spec) |
| G_sl12 / G_sl08 | 0.60 / 0.53 | 8% whipsaws |
| G_x4_atr2/2p5 | −0.31 | **INVALID — harness bug** (2% floor mis-expressed X4); discard |

**Conclusions:**
1. **`atr_stop_mult` is INERT** — the seed's stop is effectively a pure % trailing stop (the 10% floor
   always beats 2.5–3× of a ~14-day ATR). **Dropped it** — one fewer knob.
2. **The "stop" is a trailing PROFIT-LOCK, not a loss-cut** — avg PnL *at stop-exit* is **positive**
   (+2.4% at 10%). 90% of exits are the raised stop giving a little back on a winner, not −10%
   disasters. **This is the engine of the edge.** Stop width trades give-back vs whipsaw.
3. **Decoupled SMA > tranche-gated** (0.87 vs 0.67) — confirms the E1 spec.

## Step 9 — Tier-3 interaction + OOS gate: the new champion

Stop-width × TP-timing, 6 arms (`data/selection_sweep/tier3_grid/`) — **the interaction the marginal
exit grid missed:**

| arm | IS Sharpe | ret | maxDD |
|---|--:|--:|--:|
| **T3_sl15_tpTight** (15% stop × +10% T1) | **1.10** | **+861%** | 45% |
| T3_sl10_tpDflt (old seed) | 0.87 | +418% | 51% |

**`sl15` alone was 0.75 and `tpTight` alone was 0.76 — both individually WORSE than the seed. Together,
1.10.** Mechanism: the **wide 15% stop** lets winners breathe (fewer whipsaws); the **early +10% T1**
banks the first pop before the wide stop gives it back. Complementary — the tight TP de-risks the wide
stop's give-back. *This is the whole case for interaction grids: a marginal sweep discards both halves.*

**OOS gate — real, not overfit** (`data/selection_sweep/wfo_gate/`; fixed config, rolling
2yr-train/1yr-test BackTrader folds — a TRUE gate, NOT `run_strategy_wfo.py` which re-optimizes on the
vec engine that lacks tranche TP):

| config | agg OOS Sharpe | OOS ret | OOS maxDD | 2024 fold (the hard one) |
|---|--:|--:|--:|--:|
| **T3_sl15_tpTight (winner)** | **1.47** | +245% | **−28%** | +0.12 / −4% |
| T3_sl10_tpDflt (old seed) | 1.28 | +172% | −36% | **−0.54 / −21%** |

- **No IS→OOS collapse** (OOS 1.47 ≥ IS 1.10) — opposite of the 1.22→−0.17 overfit precedent.
- **Winner beats the seed on EVERY OOS metric** on identical unseen folds.
- The edge concentrates in the **weak 2024 fold** (winner −4% vs seed −21%) — more robust in the bad
  year, not just juicing good ones. Not a lottery: top-5 trades = 34% of PnL, positive every IS year.

**➡️ NEW CHAMPION** `E1.d0_X1.sl15_Xt.t1_10_X3.sma50_S0.top5`, supersedes the sl10/tpDflt seed.

## Step 10 — productionisation (Phases 1–3)

The champion becomes a first-class object rather than a kwargs dict in a script. Full plan:
`docs/architecture/backtest_productionisation_plan.md`. Shipped: **`strategy_registry`** (named,
fingerprinted, regression-tested configs — single source of truth), **`run_oos_gate.py`** (the fixed-
config promotion gate; re-gating the champion reproduces 1.47/+245%/−28% exactly), **`population_runner`**
(the parallel run-and-persist path with the rejection audit). Array/confirm/sweep CLIs are thin
wrappers over it.

## Step 11 — start-time & horizon robustness: the champion is a regime ride

The OOS gate answered "overfit to the *fold split*?" (no). It did **not** answer "does the edge survive
*when* you start?" So we ran the **locked** champion over a grid of `(start, end)` windows —
`run_starttime_sweep.py`, `data/selection_sweep/starttime/champion/{rolling,horizon,matrix}/`. Fair,
window-length-invariant metrics (`ann_return`/`sharpe`/`maxDD`, never raw total_return). *(Bug fixed en
route: the sweep's parallel path submitted an unpicklable local closure — only serial `--smoke` worked;
`_run_cell` lifted to module level.)*

**`rolling` — the decisive read (53 cells, fixed 12-month horizon, monthly starts):**

| metric | value |
|---|---|
| ann_return spread | **−39.4% .. +196.6%** (median 21.6%, IQR 61.2%) |
| Sharpe spread | **−0.88 .. +2.45** (median 0.68) |
| Sharpe-negative cells | **17 / 53** |
| pattern | regime-clustered — 2021 & 2025 starts win big, mid-2022 starts lose |

Same holding period, only the start *month* differs → outcome is dominated by **what regime you start
into**, not stock-picking skill. `horizon` (fixed start, growing end) confirms from the other axis:
ann_return mean-reverts 517% (6m, 2021 melt-up) → ~35–55% (36–48m), Sharpe settling ~0.9–1.2. `matrix`
(84 cells) reinforces "wide + path-dependent" but its short cells annualize into nonsense (+138853%),
so **`rolling` is canonical**, not `matrix`.

**Conclusions:**
1. **The edge is a beta/regime ride** — a long-only momentum-breakout book that makes money *in*
   bull/ignition regimes and bleeds *in* bears. The M03 gate caps the bleeding but can't manufacture an
   edge in a chop/bear start.
2. **The honest forward expectation is a distribution, not the +245% headline** — whoever operates the
   book starts on *one* date, one draw from a −39%..+197% cone. The monitor must present start-time-
   conditional confidence, never a single P&L.
3. **Not a falsification** — the champion still beats the seed OOS on identical folds; the sweep
   measures an orthogonal risk (start-luck) the fold-gate never touched. It raises the bar for "trust
   it": pair with the friction re-run (Tier A.2) and a real forward quarter before sizing.

## Step 12 — forward shadow book (the monitor this demands)

Because the edge is start-conditional, the live check is a **paper shadow**, not a re-derived number.
`run_shadow_book.py --strategy champion --start-date <inception>` replays the champion start→today (a
pure function of scores/prices/regime — replay beats fragile state serialization) and persists what it
*would* do to `shadow_book` (open positions, keyed by `book_id`) + `shadow_action` (append-only
enter/target/stop/trend). It's a synchronous **next-open** mirror of the BackTrader engine
(`src/backtest/forward_engine.py`), gated by `tests/test_forward_parity.py` (entry overlap > 0.85).

Steps 1–5 shipped, parity green. **Step 6 (nightly orchestrator on `sh019`) deferred by design — no
inception date chosen yet** (the start-time sweep exists to inform that choice). Intended daily
mechanism: pick a date → one-time backfill (= this replay) → register `(book_id, strategy, start_date)`
→ nightly detects the row and steps only the new day incrementally. **Grids are exploration-only; the
daily pipeline never runs a grid.** Full spec: plan doc §Phase 4.

---

## Path forward — ranked by how much each changes our confidence

### Tier A — de-risk before scaling capital (do these first)
1. **Forward paper-trade the champion for a quarter.** Highest-value step — the OOS gate is 3 historical
   folds; a live forward quarter on unseen 2026-H2 is the real out-of-sample. **The rails exist**
   (`run_shadow_book.py`, registry-sourced, parity-gated). Remaining: pick a start date, then Step 6 —
   wire the nightly (`sh019`, supervised) + add `shadow_book`/`shadow_action` to `build_dashboard_db`
   MANIFEST. NOT a `SEPAFlatV1` edit.
2. **Model realistic frictions at size.** Current run is flat 0.1% commission + 0.1% slippage on a
   microcap universe — optimistic. Re-run with a liquidity floor (drop names below $X ADV), slippage
   scaled to spread, a capacity ceiling. Survives a $5–10M ADV floor → tradeable; evaporates → it was a
   microcap-illiquidity artifact.
3. **Widen the OOS gate.** 3 folds is thin, 2024 flat. Add an *anchored*-train variant + a 2026-inclusive
   fold; report a fold-Sharpe distribution (`run_oos_gate.py --strategy champion --anchored`). *Partly
   done — the start-time rolling grid already gives a start-conditional Sharpe distribution.*

### Tier B — understand the edge better (parallel)
4. **Stress the trailing-stop mechanic directly.** The whole edge is the profit-lock stop; we've only
   tested its *width*, not its *trailing dynamics* (breakeven-raise trigger, trail distance as f(ATR) vs
   fixed %, ratchet step). Highest-upside remaining exit dimension.
5. **Decompose the +861% by cohort.** A handful of 2021/2025 ignition names, or broad? Per-trade parquet
   supports it. If 3–4 names carry it, capacity risk is worse than the 34% top-5 concentration suggests.
6. **Test the champion on a liquid-only universe** (large/mid). If M01+this-exit-stack works on liquid
   names — even at lower Sharpe — that's the *actually scalable* strategy, more important than the
   microcap +861%.

### Tier C — deferred / optional
7. **`selection_skip_top`** — shipped/tested; proto-specific DD lever, no-op on binary. Revisit only if
   a proto-signal strategy is stood up (best OOS arm 0.59, below binary).
8. **`G_x4` harness bug** — pure-ATR X4 mis-expresses the stop (2% floor → cap → −69%). Fix or delete
   before any pure-ATR-trail test (overlaps item 4).
9. **Second uncorrelated sleeve** — everything here is one long-only momentum-breakout book. A real
   arena needs a second, differently-conditioned sleeve (mean-reversion? liquid-large?) before
   "portfolio of strategies" is meaningful.

**Honest bottom line:** a *candidate* worth a forward paper-quarter and a friction re-run — not a proven
money-maker. The exploration did its job: killed the selection red herrings, found the exit interaction,
gated it once, and measured its start-time fragility. The remaining risk is universe/liquidity realism
(and start-date luck) — Tier A's job to settle before any real allocation.
