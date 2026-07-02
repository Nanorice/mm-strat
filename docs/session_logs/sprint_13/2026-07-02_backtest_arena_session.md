# 2026-07-02 — Backtest Arena, Optimizer, Walk-Forward & Macro Sizing

Session goal: close the gap to systematic model/strategy testing in the backtest,
then actually run it. Ended with an honest equity engine, a working optimizer
(single + walk-forward), an all-variant model arena, and a validated macro-sizing
lever.

## TL;DR findings

1. **The vectorized equity curve was lying.** It booked each trade's whole PnL as a
   spike on the exit date and let N concurrent positions each lever full capital →
   drawdown-blind and return-inflated. Rebuilt as **bar-by-bar mark-to-market against
   `price_data` with a shared capital pool**. This flipped the model ranking (the old
   curve flattered the *worst* model, m01_no_macro).
2. **Model Arena (all variants, honest Sharpe):** on the common window
   (2025-10-06→2026-05-22, bounded by prototype prod-score history) **m01_binary (1.997)
   ≈ m01_prototype (1.992)** — a dead heat; prototype had highest total return (54%).
   **m01_no_macro (4-class) worst (0.33).** These Sharpes are regime-flattered (short
   recent window).
3. **Single-split optimizer overfits.** m01_binary tuned to **IS Sharpe 1.22 → OOS −0.17**
   — converged on `max_positions_per_day=1` (bet-the-top-pick), which blew up OOS. The
   WF gate exists precisely to catch this.
4. **Walk-forward is honest.** 3 folds (2yr train / 1yr test), re-tune each fold:
   **aggregate OOS Sharpe 0.84**, ann ret 79%, **maxDD −33%**. Fold-1 (2024) whiffed
   (IS 1.64 → OOS 0.08) — a regime break, the main risk signal.
5. **Macro sizing works — but the signal matters.** Same trades, only exposure differs:
   - **VIX-banded: Sharpe 0.21→0.31, return 11.8%→23.3%, maxDD −47%→−28%, at 64% avg
     exposure.** More return from less capital = real risk-timing, not de-leveraging.
   - **M03-banded: no-op (Sharpe 0.20 vs flat 0.21)** at the same 62% exposure — de-levered
     without timing skill. M03 (stripped from the model) doesn't add value as a sizing
     lever either → consistent with the sprint's macro-redundancy conclusion.

## What was built (all new/changed code)

- `src/backtest/vectorized_backtest.py`
  - `equity_curve()` rewritten → **bar-by-bar mark-to-market + shared capital pool**
    (`max_slots = 1/position_size_pct`, pro-rata scale-down when over-subscribed).
  - `equity_curve(trades, exposure=<pd.Series>)` — optional daily sizing weight
    (default flat 1.0; backward-compatible).
  - `metrics()` helper — Sharpe / ann return / ann vol / maxDD / total return. The
    optimizer/arena objective surface.
- `src/backtest/macro_sizer.py` (NEW) — `MacroSizer` with `flat` / `vix` / `m03` modes,
  **1-day lag (no lookahead)**, fixed hypothesis bands (`VIX_BANDS`, `M03_BANDS`).
- `scripts/run_model_arena.py` (NEW) — all-variant bake-off, **dual score sources**:
  `score_from_t3` (models with full artifacts) + `daily_predictions` injection (prototype).
- `scripts/run_strategy_optimizer.py` (NEW) — Optuna single IS/OOS, maximize Sharpe.
  Shared `suggest_params()` search space + `run_trades()`.
- `scripts/run_strategy_wfo.py` (NEW) — rolling/anchored WF; per-fold re-tune, stitched
  aggregate OOS curve; reuses optimizer's shared pieces; supports both score sources.
- `scripts/run_sizing_experiment.py` (NEW) — same-trades / different-exposure comparison.

## Artifacts

- `models/arena/` — `arena_report.md`, `arena_results.json`
- `models/m01_binary/optimizer/` — single-split results (overfit demo)
- `models/m01_binary/wfo/` — walk-forward results (aggregate OOS 0.84)
- `models/m01_binary/sizing/` — `sizing_report.md`, `sizing_results.json`

## Landmines pinned (verify before relying)

- **Model loadability = has `categorical_mapping.json`.** Only `m01_binary/v1`,
  `m01_binary_no_macro/v1`, `m01_no_macro/v1` load in the backtest scorer. **`m01_prototype`
  HARD-FAILS** (`ValueError`, no frozen categorical vocab) — the fallback-to-`company_profiles`
  code at `universe_scorer.py:328` is DEAD (an earlier guard raises first). Prototype is
  scored via **Option B: `daily_predictions` injection** instead.
- **`daily_predictions` prototype coverage is short: 2025-10-03 → 2026-06-18 only.** Bounds
  any prototype comparison window. Version id: `m01_prototype_2003_2026_20260514_233125`.
- **`m03_score` is 0–100, NOT 0–1.** First sizing run had a silent no-op (`.clip(0,1)`
  saturated all days to 1.0). Fixed with `M03_BANDS`. Watch this scale elsewhere.
- **m02_breakout is a 5-fold WF regressor** (no single `model.json`, no `prob_elite`) —
  the current `UniverseScorer` can't load it. Needs a scorer adapter before it enters the arena.
- **prototype in the arena is macro-inclusive (M03); the m01_* variants are not** → arena
  "prototype vs m01_binary" carries a macro-vs-no-macro difference. Noted in the report.

## Caveats on the numbers

- Arena Sharpes (~2.0) are **regime-flattered** (short strong-tape window). WF aggregate
  0.84 and the 5-year sizing baseline (Sharpe ~0.2–0.3 flat) are the honest steady-state.
- Sizing bands are **unturned hypotheses** (deliberately, to avoid overfitting a new
  surface). VIX's *direction* is robust; magnitude needs the WF gate if bands are ever tuned.
- Mark-to-market approximations (acceptable for ranking, documented in the docstring):
  stopped trades marked to close not stop-fill; `held_open` marked to last close.

## Next steps (recommended order)

1. **VIX sizing through the WF gate** — does aggregate OOS Sharpe (0.84) improve with VIX
   exposure layered on? Direct test that the timing edge survives OOS, not just in-sample-full.
2. **m02 scorer adapter** — load the 5-fold WF regressor so it can enter the arena.
3. **Backfill prototype `daily_predictions`** (or Option A: regenerate its categorical
   mapping from its training universe) to widen the prototype comparison window.
4. Optional: rolling-WF the sizing bands only if step 1 shows promise (else leave as fixed
   hypothesis — the edge is thin, don't over-engineer).
