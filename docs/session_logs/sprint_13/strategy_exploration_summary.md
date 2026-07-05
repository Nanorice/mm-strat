# Strategy Exploration — Session Summary (2026-07-05)

> One question drove the day: **is the M01 edge in *what* we pick (selection) or *how/when* we
> trade it (timing/exits)?** We started from a rotation design (delayed entry + score-drop exit +
> rebalance under a $25k cap) and stripped it down through falsification. Companion runnable cells:
> [strategy_exploration_cells.md](strategy_exploration_cells.md) / `notebooks/s13_rotation_strategy.ipynb`.
> Results analysis cells: [backtrader_analysis_cells.md](backtrader_analysis_cells.md).

---

## TL;DR — what we concluded, and what we trade forward

**The edge is in the EXITS, not the selection.** Every selection idea we tried (delay, persistence,
score-drop rotation, wider N, skip-the-tip, proto vs binary) either falsified or failed to beat the
plain top-5-by-score baseline. What *did* move the needle was the **exit stack** — specifically a
wide trailing stop paired with an early partial profit-take, which we found via a stop×TP
*interaction* grid and then validated out-of-sample.

**The strategy we trade forward (the new champion):**

| Component | Setting | Fingerprint |
|---|---|---|
| Signal | m01_binary, top-5 by `prob_elite` | `S0.top5` |
| Entry | immediate on qualify, day-0 (no delay) | `E1.d0` |
| Stop | **15% whole-position trailing** (ATR mult inert → dropped) | `X1.sl15` |
| Take-profit | **early T1 at +10%**, then staged (T2 +2ATR, T3 SMA50) | `Xt.t1_10` |
| Trend exit | decoupled SMA50 (close<SMA ⇒ out) | `X3.sma50` |
| Regime | M03 strong-bear (score<15) hard-liquidates | gate |

`E1.d0_X1.sl15_Xt.t1_10_X3.sma50_S0.top5`. In-sample 1.10 Sharpe / +861% / −45% DD;
**out-of-sample-gated 1.47 Sharpe / +245% / −28% DD** across 3 unseen rolling folds — beats the
prior seed on every OOS metric, no IS→OOS collapse.

**What this realistically means (read before believing the numbers):**
- **These are 2021–2026, $25k, microcap-heavy backtest numbers — NOT a forward return forecast.**
  The universe skews small/illiquid (entry prices $5–20, e.g. ANVS/CRNC/PSNL). Slippage, borrow,
  and capacity at real size will erode this; +861% is a *ranking* signal, not a P&L promise.
- **The whole edge rests on ONE mechanic: the trailing stop is a profit-LOCK, not a loss-cut** —
  90% of exits are the raised stop giving back a little on a winner (avg PnL *at stop* is positive).
  The strategy rides breakouts and trails out. If that mechanic degrades (regime, liquidity), the
  edge degrades with it.
- **It is exit-driven and capacity-bound.** ~92–95% day-over-day name overlap; the 5-slot book,
  not the pick, is the binding constraint (rejection audit is dominated by `no_slots`). "Trade
  fewer/rebalance less" is an exit lever, not a selection lever.
- **The OOS gate is 3 folds and 2024 was flat (+0.12).** This is "promising and honestly gated,"
  NOT "proven." One good gate ≠ a live track record. Treat the live slot as a **paper/small-size
  probation**, not a full allocation.

**Immediate trading posture:** promote the new champion to the live SEPAFlatV1 config
(`max_stop_pct=0.15, min_target1_pct=0.10, sma_exit_independent=True, entry_top_n=5`), drop the
inert `atr_stop_mult`, and run it **paper/small-size for a forward quarter** before any real capital
scaling. See *Path forward* at the bottom.

---

## Strategy fingerprint scheme

A strategy = **entry** + **stop (SL)** + **take-profit (TP)** + **selection** components. Each
component has a stable **index** (E1, X1, …) and a **grid suffix** describing its knob. The name
*is* the definition and parses back to engine kwargs.

`<Entry>_<Stop>_<TP>_<Selection>` — e.g. `E1.d0_X1.sl10_X3.sma50_S0.top`

| Family | Index | Meaning | Grid suffix (examples) |
|---|---|---|---|
| **Entry** | `E1` | immediate on qualifying | `.d0` (delay 0d) |
| | `E2` | delayed + return-band | `.d3` `.d1` … + band `.b-5+15` |
| **Stop (SL)** | `X1` | wider-of(2·ATR, %) whole-position stop | `.sl10` `.sl15` |
| | `X4` | pure ATR stop (% floor disabled) | `.atr2` `.atr2.5` |
| **Take-profit (TP)** | `X3` | SMA/trend exit (decoupled) | `.sma50` `.sma20` |
| | `Xt` | 3-tranche targets (+15% / +2ATR / SMA) | `.tranche` |
| | `X2` | score-drop / rotation exit | `.drop08` `.floor10` |
| **Selection** | `S0` | top-N by daily score | `.top` |
| | `S1/S2/S4` | random from top-decile / quartile / all | `.rndD` `.rndQ` `.rndA` |
| | `S3a/S3b` | trailing-avg score / cohort-pct persistence | `.avg10` `.pct10` |
| | `S5` | bottom-N (anti-signal control) | `.bot` |

> **E1 (the survivor)** in full: `E1.d0_X1.sl10_X3.sma50_S0.top` — immediate entry, 10% whole stop,
> decoupled SMA50 trend exit, staged TP, top-5 by score. Everything else below was tested against it.

## Fingerprint × performance — the master table

**Signal:** m01_binary unless noted. **Window:** 2021-01→2026-05 (incl. 2022 bear). **$25k, top-5 equal-weight.**
Prototype rows are the 2025-10→2026-05 bull window (regime-flattered — *illustrative only*).

| Fingerprint | What it tests | Signal | Sharpe | Total ret | maxDD | Verdict |
|---|---|---|--:|--:|--:|---|
| `E1.d0_X1.sl10_X3.sma50_S0.top` | **the survivor** | binary | **0.86** (WFO OOS **0.84**) | +404.8% | 50.8% | ✅ **LIVE SLOT** |
| `E2.d3.b-5+15_X1.sl10_X2.drop08_S0.top` | rotation (delay+score-drop) | binary | −0.05 | −31.9% | 63.8% | ❌ falsified |
| `E2.d1.b-15+30_X1.sl10_X3.sma50_S0.top` | delay 1d only | binary | 0.13 | −5.0% | 71.4% | ❌ delay kills it |
| `E2.d2…` / `E2.d3…` / `E2.d5…` | delay 2/3/5d | binary | 0.07 / 0.03 / −0.04 | −17% / −23% / −32% | ~73% | ❌ monotone decay |
| `…_S3a.avg10` | trailing-avg persistence | proto | −0.86 | −23% | 37.7% | ❌ wants fresh score |
| `…_S5.bot` | bottom-N anti-signal | proto | −0.81 | −6% | 95.1% | ✅ correctly bad |
| `…_S0.top` | top-N (incumbent) | proto | 1.01 | +25% | 21.3% | baseline |
| `…_S1.rndD` | random top-decile ×8 | proto | −0.08 ± 0.90 | −2±17% | — | ⚠️ tail polluted |
| `…_S2.rndQ` | random top-quartile ×8 | proto | 0.44 ± 0.66 | +6±11% | — | — |
| `…_S4.rndA` | random from all ×8 | proto | 0.50 ± 0.77 | +7±10% | — | ⚠️ ≈ quartile (bull) |
| `…_S*` | **selection on binary** | binary | *(running)* | | | ⏳ **verdict pending** |

## What each experiment concluded

1. **Rotation / score-drop exit — FALSIFIED.** E2 < E1 on both windows and every year incl. the
   2022 bear. The `score_drop` exit fights the A3 non-monotonicity (sells names that mean-revert up);
   `trend`+`score_drop` churn ~48% of E2's exits for no offsetting edge.
2. **Delayed entry — FALSIFIED, monotone.** +405% (0d) → −5% (1d) → −32% (5d). Immediate entry
   captures the 2022/2023 ignition breakouts; any delay turns those exact years deeply negative and
   blows maxDD to ~73%. **The alpha is the day-0 breakout — there is no paying pullback.**
3. **E1 is not overfit — WFO OOS Sharpe 0.84.** IS ~2.0 → OOS 0.84, matching the known steady-state.
   Fold decay (2.27→0.69→−0.16) is the 2026-chop weakness, not overfit.
4. **Persistence (trailing-avg score) — FALSIFIED.** Smoothing the score destroys the edge (−0.86).
   Same lesson as delay: the signal is **fresh**, not sustained.
5. **Selection (gate vs sorter) — OPEN, binary pending.** Prototype hint: top-N (1.01) beats every
   random arm (sorter works at top-5), BUT the gate is non-monotone (rand-decile −0.08 < rand-all
   0.50) — the extreme tail is polluted. Likely a bull artifact; binary's bear is the verdict.
6. **Turnover is exit-driven, not selection-driven.** ~92-95% day-over-day name overlap across all
   selection rules → "rebalance less" is an *exit* lever, not a *pick* lever.

## Selection sweep — VECTORIZED (relative-only; absolute Sharpes UNUSABLE)

Ran the selection family on the fast vectorized engine, matched 2021–2026 horizon, both signals
(binary + `m01_prototype_cali`). **Results saved:** `data/selection_sweep/` (`summary.parquet` =
60 rows arm×signal×seed; `trades/*.parquet` per run; `gap_check_*.json`). Scores cached to
`data/score_cache/{binary,proto_cali}_2021_2026.parquet` (kills the 2-min re-score).

**⚠️ The engine gap is a sign-flip, not an error bar** (`gap_check_*.json`):

| E1 | vectorized | BackTrader | delta |
|---|--:|--:|--:|
| binary | Sharpe 0.04 / −34.5% | **0.86 / +405%** | −0.82 |
| proto_cali | −0.02 / −48.8% | 0.58 / +163% | −0.60 |

**Cause: vectorized has NO M03 bear-gate** — it holds through 2022 (maxDD −77%) where BackTrader
liquidates (regime 0). Plus no hard cash-blocking, first-entry dedup. So **absolute vectorized
numbers are meaningless for this strategy; only same-engine rank-order is valid.**

**Directional findings (survive the caveat — consistent across BOTH signals):**

| finding | binary | proto_cali |
|---|--:|--:|
| **N=5 too concentrated; N=8–10 best** | N8 0.27, N10 **0.47** vs N5 0.04 | N8 **0.55**, N10 0.41 vs N5 −0.02 |
| **cap_3to8 (skip top-2 picks)** | 0.05 (neutral) | **0.71 / +231% — best arm** |
| **gate works, sorter weak** | rand_decile 0.26 ≈ topN8 | rand arms ≈ topN, high variance |

1. **Widen N to ~8–10** — $25k/5 slots takes too much single-name risk. Real, actionable.
2. **Skip the top-2 ranked names (A3 tail-pollution CONFIRMED)** — the extreme tail is spent
   (score peaks decile 7, fades decile 10). Huge on the wide-spread 4-class proto (p99 0.596),
   muted on compressed binary (p99 0.289).
3. **Score is a gate, weak sorter** — random-from-top-decile ≈ exact top-5; being *in* the elite
   set matters more than the precise rank within it.

## The one pattern across all of it

Delay, persistence, and selection-sorter all point the same way: **this strategy wants the
immediate, fresh, top-ranked signal** — but held **wider (N=8–10)** and **not at the very tip**
(skip the spent top-2). E1-seed direction confirmed; N and tail-cap are the refinements to test.

## FIXED ENGINE — sweep re-run (2026-07-05 cont.)

The vec↔BackTrader gap was **misdiagnosed as bear-gate-only**. Two engine fixes landed in
`vectorized_backtest.py`:

1. **`regime_gate`** (M03 strong-bear, `m03_score < 15` → block entries + zero daily return).
   Matches `SEPAHybridV1`. **Minor** on E1: Sharpe 0.03→0.07, maxDD −77%→−73%.
2. **`max_concurrent_positions`** (greedy slot-book — admit an entry only when an earlier trade
   has exited). **This was the dominant gap.** Without it, top-N *new* entries/day × ~25-day
   holds → **up to 19 concurrent** on a nominal 5-slot book; `equity_curve` pro-rata-diluted the
   winners to nothing. With `cap=5`: concurrency hard-capped at 5, E1 binary recovers to
   **+0.34 / +37% / −55%** (was +0.07 / −29% / −73%). Exits are path-independent so the greedy
   pass is exact. Test: `test_capacity_gate_blocks_over_subscription`.

**The fix reorders the prior (broken-engine) selection findings — the old N-ranking was a
dilution artifact.** Absolute signs are now trustworthy (`data/selection_sweep/summary_fixed.parquet`):

| signal | arm | N | Sharpe | total ret | maxDD |
|---|---|--:|--:|--:|--:|
| binary | topN | **5** | **0.34** | +37% | −55% | ← binary best |
| binary | topN | 8 / 10 | 0.29 / 0.30 | +25% / +29% | −62% | modest |
| binary | topN | 3 / 15 | −0.06 / −0.38 | −52% / −44% | ~−70% | too tight / too diffuse |
| binary | cap_skip2 | 8 / 10 | 0.33 / −0.07 | +37% / −27% | −64% / −69% | ≈ topN (cap neutral on compressed) |
| proto_cali | topN | 3 | **0.85** | +478% | −52% | concentration lottery (uninvestable DD) |
| proto_cali | topN | 8 / 10 | 0.63 / 0.61 | +147% / +117% | −52% / −41% | peak of plain topN |
| **proto_cali** | **cap_skip2** | **10** | **0.80** | +217% | **−32%** | ✅ **best risk-adj — skip top-2, hold wide** |
| proto_cali | cap_skip2 | 8 | 0.76 | +225% | −43% | strong |

**Revised read (supersedes the broken-engine N-ranking above):**
- **"Widen N to 8–10" was a dilution artifact on binary** — with an honest slot book, binary
  peaks at **N=5**; N=15 goes negative. Binary is just a weak signal for this strategy.
- **cap_skip2 (skip the spent top-2) is real on proto_cali, neutral on binary** — confirms it's a
  *wide-spread-signal* fix (proto p99 0.60 has rank dispersion; binary p99 0.29 doesn't). The A3
  tail-pollution edge only exists where ranks actually separate.
- **proto_cali `cap_skip2 @ N=10` is the standout robust arm** — 0.80 Sharpe, +217%, and the
  **shallowest drawdown (−32%)** of any arm. Skip the tips, hold wide (10). This is the config to
  BackTrader-confirm.
- **N=3 proto (0.85/+478%)** is a return-chasing outlier — a few huge winners, −52% DD; not
  investable at $25k.

### Phase checkpoint (selection sweep complete)

1. ~~Fix the vectorized engine's bear-gate~~ ✅ + capacity book — done, signs trustworthy.
2. ~~Re-run the sweep~~ ✅ — N-ranking reversed, `cap_skip2 @ N=10` (proto) was the vec winner.
3. ~~BackTrader-confirm~~ ✅ — the vec winner did NOT beat the seed (below).

## BackTrader confirm — VERDICT (2026-07-05 cont.)

Ran the 5-arm population through BackTrader (`scripts/run_strategy_confirm.py`, parallel across
arms, `data/selection_sweep/backtrader_confirm/`). **A1 reproduced the prior E1 champion exactly
(0.871 / +418% vs the known 0.86 / +405%)** → harness is faithful, the comparison is trustworthy.

| Rank | arm | Sharpe | ret | maxDD | vec said |
|---|---|--:|--:|--:|--:|
| **1** | **A1 binary top-5 (SEED)** | **0.87** | **+418%** | 50.8% | 0.34 |
| 2 | A2 proto top-5 | 0.59 | +170% | **80.9%** | 0.43 |
| 3 | A4 proto skip-2 @ N=10 (vec winner) | 0.59 | +141% | **45.5%** | 0.80 |
| 4 | A5 proto skip-2 @ N=8 | 0.54 | +121% | 46.8% | 0.76 |
| 5 | A3 proto top-10 | 0.51 | +112% | 57.7% | 0.51 |

> **⚠️ Later superseded:** at this checkpoint the binary E1 seed (sl10/tpDflt) was the champion.
> The exit grid + Tier-3 interaction (below) then found a *better* config (sl15/tpTight) that beats
> this seed OOS. The seed remains the correct *pre-exit-grid* baseline; the TL;DR champion is final.

**1. The binary E1 seed beats the proto challengers — outright.** 0.87 Sharpe, +418%, not close.
The vec-favored `proto skip-2 @ N=10` lands mid-pack (0.59). Vec over-ranked proto because it
**lacks the 3-tranche staged TP** — binary's edge IS the staged profit-take on day-0 breakouts,
which only the fidelity engine captures. The residual vec↔BackTrader gap was this, as suspected.

**2. But `selection_skip_top` earns a real, narrower use — it's a DRAWDOWN tool, not a return
tool.** On proto: skip-2 (A4) vs plain top-10 (A3) → Sharpe 0.59 vs 0.51 AND **maxDD 45.5% vs
57.7%** (−12pts). Sharpest contrast: A2 (proto top-5) is the **worst-DD arm (80.9%)** while A4
(proto skip-2, hold wide) is the **best-DD arm (45.5%)** — same signal. Confirms A3 tail-pollution:
the very top proto names are spent/volatile; skipping them + widening N tames drawdown. The knob is
shipped (`selection_skip_top` on `SEPAHybridV1`, tested) — a candidate DD-control lever, not a
core selection change.

**3. Vec↔BackTrader — agree on sign, disagree on cross-signal winner.** Both engines rank skip-2 >
plain top-10 (relative screen was directionally right). They diverge on binary-vs-proto because the
3-tranche TP is invisible to vec. **Lesson: vec is a valid *within-signal* selection screen; it
CANNOT rank across signals/exit-styles — take those to BackTrader.**

## Exit grid — Tiers 1+2 (2026-07-05 cont.)

Ran 16 arms off the champion (`scripts/run_strategy_confirm.py --grid exit`,
`data/selection_sweep/exit_grid/`). **Every trade + rejection cached** (`trades.parquet`,
`rejections.parquet` per arm) so entries/exits are investigable. **Champion holds — nothing beats
`sl10/atr2/sma50/decoupled/tranche` (0.87)** — but the grid is highly diagnostic:

| Rank | arm | Sharpe | ret | note |
|---|---|--:|--:|---|
| 1 | **G0 champion** | **0.87** | +418% | local optimum |
| 2/3 | G_atr2p5 / G_atr3 | 0.86 | +399% | **byte-identical to champion → ATR-mult is INERT** |
| 4 | G_tp_t1atr2 | 0.79 | +317% | tighter ATR target — best non-champion, win-rate 42% |
| 5 | G_tp_tight | 0.76 | +303% | earlier T1 (+10%) |
| 6 | G_sl15 | 0.75 | +300% | widest stop — credible #2 stop, higher win-rate |
| 9 | G_tp_gated | 0.67 | +224% | decoupled SMA beats gated (confirms E1 spec) |
| 11 | G_sl12 | 0.60 | +172% | — |
| 13 | G_sl08 | 0.53 | +129% | too tight — whipsaws |
| 15/16 | G_x4_atr2/2p5 | **−0.31** | −69% | **INVALID — harness bug** (2% floor mis-expressed X4); discard |

**Findings from the cached trades:**
1. **The `atr_stop_mult` knob is INERT — the champion's stop is effectively a pure 10% trailing
   stop.** `atr2p5`≡`atr3`≡champion (identical trades). `wider-of(N·ATR, 10%)` → the 10% floor
   always wins over 2.5–3× of a ~14-day ATR. **Simplification: drop `atr_stop_mult` from this
   config** (it does nothing). ponytail win — one fewer knob.
2. **The "stop" is a trailing PROFIT-LOCK, not a loss-cut.** avg PnL *at stop-exit* is **positive**
   (+2.4% at 10%): 90% of exits are the raised/trailing stop giving back a little on a winner, not
   −10% disasters. This is the engine of the edge — ride winners, trail out. Stop width trades
   give-back vs whipsaw: 8%→0.53 (whipsaws), 10%→0.87, 12%→0.60, 15%→0.75 (fewer/bigger wins,
   win-rate 42%).
3. **Decoupled SMA > tranche-gated** (0.87 vs 0.67) — confirms the E1 spec.
4. **TP tightening (tp_t1atr2, tp_tight) raises win-rate to 42% but not Sharpe** — champion's later
   profit-take is better risk-adjusted; taking T1 sooner trades a bit of edge for smoother wins.

## Tier 3 interaction + OOS gate — NEW CHAMPION (2026-07-05 cont.)

Stop-width × TP-timing, 6 arms (`data/selection_sweep/tier3_grid/`). **The interaction the
marginal sweep MISSED:**

| arm | in-sample Sharpe | ret | maxDD |
|---|--:|--:|--:|
| **T3_sl15_tpTight** (15% stop × +10% T1) | **1.10** | **+861%** | **45%** |
| T3_sl10_tpDflt (old champion) | 0.87 | +418% | 51% |
| T3_sl10_tpATR2 | 0.79 | +317% | 56% |

**`sl15` alone was 0.75 and `tpTight` alone was 0.76 — both individually WORSE than the champion.
Together, 1.10.** Coherent mechanism: the **wide 15% stop** lets winners breathe (fewer whipsaws);
the **early +10% T1** banks the first pop before the wide stop can give it back. Complementary —
the tight TP de-risks the wide stop's give-back, the wide stop lets runners run. This is the whole
case for interaction grids: a pure marginal sweep discards both halves.

**OOS GATE — it's real, not overfit** (`data/selection_sweep/wfo_gate/`, fixed config, rolling
2yr-train/1yr-test BackTrader folds — a TRUE gate on the locked config, NOT run_strategy_wfo.py
which re-optimizes on the vec engine that lacks tranche TP):

| config | agg OOS Sharpe | OOS ret | OOS maxDD | 2024 fold (the hard one) |
|---|--:|--:|--:|--:|
| **T3_sl15_tpTight (winner)** | **1.47** | +245% | **−28%** | +0.12 / −4% |
| T3_sl10_tpDflt (old champion) | 1.28 | +172% | −36% | **−0.54 / −21%** |

- **No IS→OOS collapse** (opposite of the 1.22→−0.17 overfit precedent) — OOS 1.47 ≥ IS 1.10.
- **Winner beats old champion on EVERY OOS metric** on identical unseen folds.
- The edge concentrates in the **weak 2024 fold**: champion −21%, winner −4%. The wide-stop +
  early-TP combo is **more robust in the bad year**, not just juicing good years.
- Not a lottery: top-5 trades = 34% of PnL, positive every in-sample year incl. 2022 bear.

**➡️ NEW CHAMPION: `E1.d0 / stop 15% / T1 +10% / decoupled SMA50 / top-5 binary`** — supersedes the
sl10/tpDflt seed. `atr_stop_mult` stays inert (drop it). Ships as `selection_skip_top`-free binary.

## Path forward — what would actually strengthen the case (ranked by value)

Ordered by *how much each would change our confidence*, not by ease. The first tier is what stands
between "promising backtest" and "trust real capital."

### Tier A — de-risk before scaling capital (do these first)
1. **Forward paper-trade the champion for a quarter.** The single highest-value step. The OOS gate
   is 3 historical folds; a live forward quarter on unseen 2026-H2 data is the real out-of-sample.
   Wire into SEPAFlatV1, run it in the nightly pipeline shadow (no capital), log fills vs backtest.
2. **Model realistic frictions at size.** Current run uses flat 0.1% commission + 0.1% slippage on a
   microcap universe — optimistic. Re-run with (a) a liquidity floor (drop names below $X ADV),
   (b) slippage scaled to ADR/spread, (c) a capacity ceiling. If the edge survives a $5–10M ADV
   floor, it's tradeable; if it evaporates, it was a microcap-illiquidity artifact.
3. **Widen the OOS gate.** 3 folds is thin and 2024 was flat. Add an *anchored*-train variant and a
   2026-inclusive test fold; report a fold-Sharpe distribution, not a point estimate. Cheap
   (`run_strategy_confirm.py --wfo-gate <arm> --anchored`).

### Tier B — understand the edge better (parallel, informs Tier A)
4. **Stress the trailing-stop mechanic directly.** The whole edge is the profit-lock stop. Sweep
   *how* the stop trails (breakeven-raise trigger, trail distance as f(ATR) vs fixed %, ratchet
   step) — this is the real lever, and we've only tested the whole-stop *width*, not its *trailing
   dynamics*. Highest-upside remaining exit dimension.
5. **Decompose the +861% by cohort.** Is it a handful of 2021/2025 ignition names, or broad? Cache
   already supports it (per-trade parquet). If 3–4 names carry it, capacity risk is worse than the
   34% top-5 concentration suggests.
6. **Test the champion on a liquid-only universe** (large/mid cap subset). If M01+this-exit-stack
   works on liquid names — even at lower Sharpe — that's the *actually scalable* strategy and the
   more important result than the microcap +861%.

### Tier C — deferred / optional
7. **`selection_skip_top`** — shipped/tested; proto-specific DD lever, no-op on binary. Only
   revisit if a proto-signal strategy is stood up (its best OOS arm was 0.59, below binary).
8. **`G_x4` harness bug** — pure-ATR X4 mis-expresses the stop (2% floor became a cap → −69%). Fix
   or delete before any pure-ATR-trail test (overlaps item 4).
9. **Second uncorrelated sleeve** — everything here is one long-only momentum-breakout book. A
   strategy arena needs a second, differently-conditioned sleeve (mean-reversion? liquid-large?)
   before "portfolio of strategies" is real. Longer horizon.

**Honest bottom line:** we have a *candidate* worth a forward paper-quarter and a friction re-run —
not a proven money-maker. The exploration did its job (killed the selection red herrings, found the
exit interaction, gated it once). The remaining risk is universe/liquidity realism, and that's Tier
A's job to settle before any real allocation.
