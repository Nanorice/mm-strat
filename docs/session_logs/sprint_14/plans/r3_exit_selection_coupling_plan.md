# R3 — Exit × selection coupling A/B (the conversion problem)

**Date:** 2026-07-10 · **Status:** 📋 PLAN (not started) · **Parent:** `sepa_funnel_meta_plan.md`
**Cost:** ~1 session build + long BackTrader runs (checkpointed). Smoke-test batch confirmed with the
user before any full cone (standing rule).

## The thesis

Selection and exit are **coupled**, and the two halves have only ever been tested against the wrong
partner:

- M4 ran the tail-seeking selection (RS top decile) under the champion's **median-optimized tranche
  exits** → 3.5× label lift converted to cone Sharpe 0.10. Diagnosis in the verdict itself: *exits
  truncate the tail* — a tranche exit banks +15–20% and forfeits the +30% MFE the label measures.
- The Minervini-style trail exit (prog-fills) was only tested with the OLD selection on the
  population-inflated arena, and washed ([[project_minervini_progfills_fails_bt]]).

The pair **RS-tail selection × tail-preserving exit** has never run. This is the last untested cell of
the matrix, and it decides whether sprint 14's selection finding is monetizable at all.

## Design — 2×2 factorial on the BackTrader cone

Selection ∈ {champion picker, `rs_universe_rank` top decile} × Exit ∈ {native tranche, SEPA trail}:

| Arm | Selection | Exit | Status |
|---|---|---|---|
| A `champion_gated` | champion | tranche | ✅ have it — M4 reference cone (median 0.47, 33% neg) |
| B `rs_tail` | RS-D10 | tranche | ✅ have it — M4 (median 0.10, 47% neg) |
| C `rs_tail_trail` | RS-D10 | SEPA trail | 🔲 **the test** |
| D `champion_trail` | champion | SEPA trail | 🔲 control — isolates the exit main effect from the selection×exit interaction |

Harness identical to M4 so A/B carry over unchanged: BackTrader, gated population, top-5 slots,
90 quarterly-start × 12m cells 2003–26, arms via `src/backtest/strategy_registry.py`, runner
`scripts/run_strategy_confirm.py`. Vec engine not used anywhere ([[project_vec_engine_optimistic]]).

**Trail definition (decide at build, keep to ≤2 variants and verify they actually differ in fills):**
no profit-taking tranches; exit = trend-break event via the existing `effective_exit_date` /
SEPA-exit machinery (e.g. close < SMA50 vs an ATR-multiple trail as the tight/wide pair). Stop-loss
discipline unchanged from champion (initial stop stays — the tail thesis is about the upside exit,
not about removing risk control).

## Milestones

- [ ] **M0 — Build + smoke.** Register arms C and D; single-cell smoke run; verify trail variants
  produce different exit dates on a sample of trades (guard against silent no-op configs). Confirm
  smoke output with user before the cone.
- [ ] **M1 — The cone.** All 4 arms × 90 cells (A/B reused from M4 run artifacts if compatible).
  Progress logging `flush=True`, per-cell checkpoint/resume.
- [ ] **M2 — Read-out.** Primary: cone median Sharpe, %neg cells, median/worst fold DD, paired
  per-cell wins vs A. **Diagnostic that names the mechanism:** per-trade MFE-capture ratio
  (realized exit return ÷ MFE_63 at entry) per arm — the direct measure of "does this exit keep the
  tail". C must beat B on capture *and* A on the cone to claim conversion.
- [ ] **M3 — Consequence.**
  - C > A (cone median, era-robust) → new champion candidate → deploy-gate re-confirm (SPY-200d
    trunk per [[project_capital_deployment]]) before any registry promotion.
  - D > A but C ≁ B-relative-lift → the trail helps *any* selection; exit improvement is orthogonal,
    adopt on champion, selection question stays closed.
  - C ≤ B → **the tail is un-monetizable in this trade structure**; RS lift = watchlist-ordering
    value only. Record it; steps 3–4 re-aim at discretionary support (meta plan).

## Guardrails / gotchas

- BackTrader all-feed warmup trap — latest-listing ticker gates `next()` ([[project_backtrader_allfeed_warmup]]).
- 12m cells truncate long trail holds; keep 12m for A/B comparability but report the share of
  window-end force-closes per arm — if C's "losses" are mostly truncations, flag before concluding.
- Stop gap-fill bias understates stop losses (vectorized path; BackTrader arm should be clean —
  verify, [[project_backtest_stop_gap_fill]]).
- No parameter tuning on the trail beyond the tight/wide pair — tuning a losing exit into a marginal
  win is the same failure mode M3 forbade.

## Kill criteria

- Neither trail variant changes the cone materially vs its tranche counterpart → exit policy is not
  the binding constraint either; the conversion gap is structural (slots/stops/entry) — stop, rethink.
- C wins the cone but only via 1–2 outlier cells → start-date lottery, not a champion
  ([[project_champion_starttime_dependent]]).

## Done when

Verdict doc (`verdicts/YYYY-MM-DD_r3_exit_selection_coupling.md`) with the 2×2 cone table + MFE-capture
table; champion either re-confirmed or replaced (with deploy-gate re-confirm); meta-plan R3 box checked.
