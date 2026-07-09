# M4 — deploy-gate BackTrader confirm: the SPY-200d gate is a REAL improvement on the fidelity engine

**Date:** 2026-07-09 · **Status:** ✅ CONFIRMED. The SPY-200d ex-ante deploy gate, run through
**BackTrader** on the SEPA-gated population, improves **every** headline metric — Sharpe, return, drawdown,
and %neg folds. This UPGRADES the vec governor verdict (`2026-07-09_regime_governor_backtest.md`), which —
on the engine-optimistic vectorized cone — found the governor *lowered* the median Sharpe and helped only
drawdown. Milestone M4 of `../plans/population_rectification_plan.md`.

**Engine:** BackTrader (`scripts/run_strategy_confirm.py --wfo-gate`) — real cash-blocking, next-open fills,
gap-down exits. NOT the vectorized engine (which is ~3× optimistic in absolute terms and understates exactly
the bear damage this gate prevents — [[project_vec_engine_optimistic]]).
**Population:** SEPA-gated (`trend_ok AND breakout_ok`) — the `binary_gated` cache, same one M2/M2b used.
**Config:** the native-tranche baseline (`_base_kwargs(5)`: top-5 by prob_elite, 10% stop, decoupled SMA50,
3-tranche TP) — identical to `M2b_gated_baseline`. The gate is ONE knob off it.
**Scope note:** on BackTrader "the governor" reduces to the **binary SPY-200d gate** — the strategy has only
`spy_deploy_gate` (block new entries when SPY<200d), not a per-day size multiplier. This is faithful to the
governor verdict's own finding: the stress-TILT goes inert once gated (gate × tilt cancel — 96% of
high-stress days are sub-200d), so the honest confirm of the governor *is* the gate.

---

## 1. The two cones (25y, rolling 2y-train/1y-test, 21 folds, gated)

`python scripts/run_strategy_confirm.py --wfo-gate {M4_gated_baseline|M4_gated_spygate} --start 2003-01-01
--end 2026-05-22 --train-years 2 --test-years 1`. SPY-200d gate dict built per fold via
`macro_sizer.spy_above_200d(test_start, test_end)` (close-through-t only, no lookahead).

| arm | agg OOS Sharpe | agg return | agg maxDD | cone median | min | %neg folds | fold DD median |
|---|--:|--:|--:|--:|--:|--:|--:|
| baseline (native tranche, no gate) | 0.52 | 299% | −61% | 0.53 | −1.86 | 45% | −17% |
| **+ SPY-200d deploy gate** | **0.79** | **794%** | **−37%** | **0.68** | −1.80 | **35%** | −12% |

**The gate improves everything at once** — Sharpe +0.27, return +495pp, maxDD +24pp, %neg −10pp, cone
median +0.15. This is NOT the "DD-controller only, costs the mean" story the vec cone told.

**Consistency check (passes exactly):** `M4_gated_baseline` reproduces the M2b BackTrader baseline to the
decimal — agg 0.52, cone median 0.53, min −1.86, %neg 45% (cf `2026-07-09_m2b_backtrader_confirm_FAILS.md`).
Same config, same cache, same scheme → the gate wiring didn't perturb the baseline.

## 2. Why it works — the win is 3 deep-bear rescues, the cost is 4 mid-cycle whipsaws

Per-fold Sharpe (baseline → gate), with the gate's open-fraction (days SPY>200d) for the movers:

| fold | base | gate | Δ ret | gate open | what happened |
|---|--:|--:|--:|--:|---|
| **2008** | −1.86 | **+2.50** | **+51pp** | **2%** | gate near-fully shut through the collapse → sidesteps the −29% BackTrader (correctly) inflicts; catches the late-2009 above-200d leg |
| **2022** | −1.69 | **−0.33** | **+33pp** | 19% | gated off through the bear → −36% → −3% |
| **2009** | −0.20 | +0.45 | +10pp | — | small rescue on the recovery |
| **2005** | 0.28 | +1.75 | +8pp | — | modest |
| 2007 | −0.10 | **−1.33** | **−15pp** | 89% | **worst cost:** 27 blocked days around the Aug-07 dip whipsawed (shallow wobble that recovered) |
| 2018 | 0.82 | 0.13 | −13pp | 84% | sat out the Jan-19 snap-back that started sub-200d ([[project_capital_deployment]] "rebound lives sub-200d") |
| 2010 | 0.78 | 0.36 | −9pp | — | early-cycle recovery below 200d, missed |
| 2014 | 1.35 | 0.91 | −8pp | — | minor |

**Mechanism:** the gate's value scales with how SHUT it is in a genuine bear (2008 open 2% → biggest
rescue). The costs are all folds where it's ~85% open — a few whipsaw days on shallow dips or a missed
sub-200d rebound leg. **3 bear rescues (+51/+33/+10pp) dwarf 4 mid-cycle drags (−15/−13/−9/−8pp)** → the
aggregate return nearly triples and Sharpe jumps. All the classic Minervini-market-filter failure modes are
present but small; the crash-avoidance dominates. (2006/2011/2012/2013/2015/2017/2019/2021/2023/2024 are
unchanged — gate ~fully open, no entries blocked. 2020 is NaN both arms — COVID fold, no completed trades.)

## 3. Why BackTrader disagrees with the vec governor verdict

The vec cone found the governor LOWERED median Sharpe (0.76→0.51), helping only drawdown. BackTrader finds a
clear all-metric improvement. The difference is the ENGINE, exactly as [[project_vec_engine_optimistic]]
predicts:

- **Vec understates the bear damage the gate prevents.** Vec's baseline 2008/2022 folds look far less bad
  (no real cash-blocking; stop-outs booked at `stop_level` even on gap-downs, [[project_backtest_stop_gap_fill]]).
  If the baseline barely bleeds in the crash, a gate that skips the crash has little to rescue → the vec cone
  showed the gate as pure cost. On BackTrader the baseline bear folds are genuinely −1.86/−1.69 (real gaps,
  real cash-out), so removing them is a large real gain.
- This is the fidelity gap made concrete: **a drawdown-avoidance overlay can only be valued on an engine that
  models the drawdown.** The vec verdict's "flat wins the median" was an artifact of vec not hurting enough
  in bears. BackTrader restores the bear damage → the gate earns its keep.

Two secondary differences (don't change the conclusion, noted for honesty): the vec governor used the full
stress-tilt × gate on the `m01_binary calibrated` cache with anchored folds; M4 is the binary gate only on
the `binary_gated` cache with rolling folds. The tilt is inert (verdict §6), and the consistency check ties
M4's baseline to the M2b BT baseline, so the engine — not these axis differences — is the driver.

## 4. Verdict & what it changes

1. **The SPY-200d deploy gate CONFIRMS on BackTrader** and is a real improvement on the SEPA-gated
   population — not merely a DD dial. It's a candidate for the live champion's deployment layer.
2. **The vec governor verdict's "DD-controller, costs the mean" conclusion is DOWNGRADED to a vec artifact.**
   The stress-tilt story is untouched (still inert once gated); what changes is that the GATE alone, measured
   honestly, is net-positive, not net-cost. Retro-flag: the governor verdict's §2/§6 "flat wins the median"
   was on the optimistic engine.
3. **The gate stays a GATE, not a re-entry model.** It re-deploys at the 200d RECLAIM, not the trough — 2018
   and 2010 quantify the missed-rebound cost. A "release near the bottom" v2 (recovery-momentum re-deploy)
   remains the natural extension (governor verdict Ext-B), and would recover the 2018-type drag.
4. **Registry:** `champion_spygate` already exists (native-config + gate, `status="candidate"`). This
   confirm is the evidence to consider promoting it to the deployment layer of the live champion — a
   portfolio-exposure decision, orthogonal to the (settled) native-tranche exit choice. NOT auto-promoted
   here; flagged for the user.

**Caveats.** Rolling 2y/1y folds (matches M2b; not the governor verdict's anchored yearly — chosen for the
M2b consistency check). The gate is coincident (200d SMA), so mid-cycle whipsaw (2007) and sub-200d
rebound-miss (2018) are structural costs of THIS gate, not tunable away without a recovery trigger. Single
gate threshold (200d), unswept — the win is large enough that fine-tuning is secondary.

cf `2026-07-09_regime_governor_backtest.md` (the vec verdict this upgrades),
`2026-07-09_m2b_backtrader_confirm_FAILS.md` (the baseline this ties to),
`../plans/population_rectification_plan.md` (M4), [[project_capital_deployment]] (SPY-200d as ex-ante gate),
[[project_entry_timing_macro_axis]] (governor = gate × tilt), [[project_vec_engine_optimistic]].
