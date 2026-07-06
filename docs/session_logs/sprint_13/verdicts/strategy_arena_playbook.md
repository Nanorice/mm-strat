# Strategy Arena — Playbook

> The manual arena: what strategy *types* exist, the grid to sweep, and the run order.
> Companion to [backtester_manual.md](../../architecture/backtester_manual.md) (the engine
> mechanics) — this is the *research plan* on top of it. Model scores are inputs; the arena
> compares **strategy rules**, holding the signal fixed, then compares signals under the best rule.

## 0. Two axes — don't confuse them

- **Signal axis** = which model's score drives selection (m01_binary, m01_prototype, m02_breakout, …).
- **Strategy axis** = the rules on top of any signal (enter / exit / size / rebalance).

The **Model Arena** (done, `run_model_arena.py`) fixed the strategy and varied the signal.
The **Strategy Arena** (this) varies the strategy — and only *then* re-checks the best strategy
across signals. Keep them orthogonal or results become uninterpretable.

## 1. Strategy types (the taxonomy)

Each type is a distinct (enter, exit, hold) shape on the same engine. Differences are almost
entirely in the **exit**.

| Type | Thesis | Enter | Exit | Typical hold |
|---|---|---|---|---|
| **Momentum-hold** (M01 baseline) | ride a confirmed leader | top-N by score/day | stop → SMA50 break → 252d | weeks–months |
| **Breakout / short-hold** (m02) | capture the ignition move, leave | top-N by proximity | stop → fixed N-day (5/10/21) or ATR-trail | days–weeks |
| **Swing** | mean-revert within a trend | score + pullback | tranche targets + tighter trail + `min_hold` | days |
| **Persistent-strength** (S5-style) | only names strong for K of last M days | persistence gate on trailing rank | as momentum-hold, higher position cap | weeks |

> The first two are the priority (M01 is validated; m02 is the new question). Swing/persistent
> are S2–S5 variants — test them on BackTrader where the tranche/min-hold knobs already exist.

## 2. The test grid (strategy knobs to sweep)

Hold the signal fixed, sweep these. Values are the sweep grid, not commitments.

| Knob | Engine param | Grid | Notes |
|---|---|---|---|
| **Entry gate** | `min_prob_elite` | {0.10, 0.15, 0.25, 0.35} | 0.10 uninformative for prototype (93% pass) — start ≥0.15. |
| **Positions/day** | `max_positions_per_day` | {1, 3, 5, 8} | 1 = bet-the-top-pick (overfits OOS — WFO gate catches it). |
| **Rank basis** | `rank_by` | {daily, trailing-10, trailing-20} | trailing = persistence; BackTrader-only today. |
| **Stop** | `stop_loss_pct` / `atr_stop_mult` | {8%, 10%, 12%} or ATR×{1.5,2,2.5} | ATR variant = BackTrader. |
| **Exit type** | `exit_policy` / tranche cfg | {sma, nday(5/10/21), atr_trail, tranche} | the strategy-type selector (§1). |
| **Position size** | `position_size_pct` | {5%, 10%, 15%} | interacts with `max_slots`. |
| **Regime sizing** | `exposure` (MacroSizer) | {flat, vix} | M03 = no-op, don't grid it. Overlay, not selection. |

**Don't grid:** industry preference (B4, dropped — already a model feature); M03 sizing (no-op).

## 3. Run order (cheap → expensive; gate before you commit)

1. **Pre-score once per signal** (`prescore()` in the optimizer) → inject everywhere. Never re-score per trial.
2. **Vectorized grid / Optuna** (`run_strategy_optimizer.py`) — fast IS/OOS single split, maximize Sharpe. Finds candidate knob sets per strategy type.
3. **WFO overfit gate** (`run_strategy_wfo.py`) — re-tune per fold; keep only strategies whose *aggregate OOS* Sharpe holds (recall M01: IS ~2.0 → WFO ~0.84 is the honest number). **Kill anything that only shines in-sample.**
4. **BackTrader confirm** (`run_strategy_array.py`, S1..S5 + the winner) — capital-honest Sharpe with real cash-blocking + tranche exits. This is the number you trust for a go/no-go.
5. **Sizing overlay last** — layer VIX `exposure` on the survivor; confirm the risk-timing uplift holds (and OOS via step 3 if tuning bands).

## 4. Per-signal plan

- **m01_binary / m01_prototype** — already through steps 2–3 (Model Arena + WFO). Re-enter only to
  test *new strategy types* (e.g. does a tighter exit beat 252d-hold on the same M01 signal?).
- **m02_breakout** — needs B3 first (`--final` model + score panel, m02 doc §8a G1/G3). Then run
  the FULL ladder on the **breakout/short-hold** type (§1 row 2). Precede with the cheap Job-2
  lead-time analysis (A3 plan §3) as a go/no-go before the trade build.

## 5. Decisions already banked (inputs, not open questions)

- **Engines = fidelity ladder** (vectorized sweep → BackTrader confirm), not a choice. (B1)
- **Optimizer + WFO gate = built**, they are steps 2–3. (optimizer question — cleared)
- **Regime/sizing is a portfolio exposure dial, not a selector** — `exposure` Series only; VIX
  works, M03 no-op → M03 retired as a sizing lever. (manual §6)
- **Industry preference not a strategy knob** — it's already a model input. (B4 dropped)

## 6. Definition of done (arena)

- [ ] m02_breakout finalized + scored (B3).
- [ ] Grid swept per strategy type on vectorized; overfit-gated on WFO.
- [ ] Survivors confirmed on BackTrader (capital-honest).
- [ ] One comparison table: (signal × strategy-type) → honest Sharpe/maxDD, with the winner named.
- [ ] Verdict written back to sprint summary: which (signal, strategy) pairs earn a live slot.
