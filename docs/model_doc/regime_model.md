# Regime Model (M03) — Macro "Weather Gauge"

> Model-lifecycle doc: problem, theory, journey, roadmap — the source of truth for
> *why the model is the shape it is* and *how to run it* (§3, §7). For code structure/infra
> see the passport [docs/modules/model_m03.md](../modules/model_m03.md).
>
> **Naming:** called the "macro" or "regime" model; the code and artifacts are named
> **M03** (`src/pipeline/m03_regime.py`, `models/m03_config.json`).
>
> **Scope:** M03 scores *the market environment*, not individual names. What it is **not**:
> a drawdown predictor or a market-timing gate — that framing was tested and rejected (§6).

## 0. TL;DR / Status

- **Status:** `SHIPPED` — runs nightly via `src/regime_pipeline.py`; feeds M01 as features and
  the macro dashboard as a gauge. Config `models/m03_config.json` **v1.3.0**.
- **What it does:** a 0–100 "traffic light" for the trading environment (Green/bull →
  aggressive, Red/bear → defensive), from a weighted sum of Trend + Liquidity + Risk-Appetite.
- **Validated:** Cohen's D **2.24** (discrimination), GFC detection lag **10d**, fitness 0.793.
- **Key truth (sprint 13):** M03 is a **coincident state descriptor**, *not* a forward
  predictor. It helps M01 *selection* (−0.22 Sharpe if removed) but is a **no-op as a sizing/
  timing lever** on its own. Use it to *confirm* state, never to *lead*.

## 1. Problem & Purpose

The strategy needs a single, legible answer to "how dangerous is the environment right now?" —
to (a) give M01 regime context as a feature, and (b) render a macro weather gauge for the human.
M03 is that composite. It replaces staring at VIX + SPY + credit spreads separately with one
calibrated 0–100 score plus a categorical label.

## 2. Theory / Hypothesis

Market risk state is legible from three orthogonal pillars, combined as a weighted sum:

1. **Trend (40%)** — SPY vs 200-day SMA. `50 + 50·tanh(pct_above_sma·10)`. The separation driver.
2. **Liquidity (20%)** — Fed Net Liquidity (Assets − TGA − RRP), 10-day slope. `50 + 50·tanh(slope·50)`.
   Supporting role. **T+1 lag applied** for FRED publication delay (no lookahead).
3. **Risk-Appetite (40%)** — VIX + HY spread, linear-interpolated to 0–50 each. Tight VIX bands
   (bull 15 / bear 20 / extreme 30) for fast crash detection. The speed driver.

**The load-bearing hypothesis test (sprint 13):** does the score *lead* drawdowns? **No.**
`corr(danger_signal_t, fwd_return)` *rises* with horizon (+0.09 → +0.30) — the opposite of a
leading bear signal. Danger signals are contrarian-bullish on the mean (vol risk premium) but
fatten the left tail. **Conclusion: M03 measures dispersion/state, not direction.** Its legitimate
uses are (a) cross-sectional context for M01 and (b) short-horizon (1–2 week) *vol* targeting —
`corr(z_vix, realized vol next 5–10d)` peaks at 0.67. It is **not** a long/flat market-timing gate.

## 3. Specification

| Aspect | Value (config v1.3.0) |
| :--- | :--- |
| **Output** | `score` 0–100 + `category` (strong_bull/bull/neutral/bear/strong_bear) + pillar breakdown |
| **Pillars / weights** | Trend **0.40** · Liquidity **0.20** · Risk-Appetite **0.40** |
| **Trend** | SPY vs 200-SMA, S-curve `50+50·tanh(pct_above·10)` |
| **Liquidity** | Net Liquidity 10d slope, `50+50·tanh(slope·50)`, **T+1 lag** |
| **Risk** | VIX bands 15/20/30, HY-spread bands 4.0/5.0/7.0 |
| **Category thresholds** | strong_bull ≥75 · bull ≥60 · neutral ≥45 · bear ≥25 · else strong_bear |
| **Gating** | allow_longs ≥30 · reduced_sizing <50 |
| **Inputs** | `MacroEngine` (FRED/FMP: liquidity, VIX, spreads) + SPY price |

**M01 feature export** (`generate_m01_features`): `m03_score` (0–1), `m03_regime_cat` (0–4),
`m03_delta_5d/20d`, `m03_regime_vol`, `m03_pillar_*` — 7 columns consumed by the M01 feature sets.

**⚠️ Scale gotcha:** the raw `score` is **0–100**, but the M01-export `m03_score` is **0–1**.
Mixing them silently breaks sizing (`.clip(0,1)` saturates the 0–100 version to 1.0). Confirm scale
before use.

## 4. Variants

Single production model, config-tuned — no competing trained variants. Configuration history lives
in `models/m03_configs/` and the calibration reports (§9); the live config is `models/m03_config.json`
(v1.3.0, the "hybrid" Trend/Risk/Liq = 0.4/0.4/0.2 tuning).

## 5. Performance

Validated against a hard-coded ground-truth of historical regimes (`m03_ground_truth.py`: GFC,
COVID crash, etc.) via `M03Evaluator`:

| Metric | Target | Achieved (v1.3.0) |
| :--- | :--- | :--- |
| Discrimination (Cohen's D) | ≥ 2.0 | **2.24** |
| ROC-AUC | ≥ 0.90 | (config-validated) |
| GFC reaction lag | ≤ 7d | **10d** (accepted trade-off for tight VIX) |
| Crash Capture Rate | ≥ 80% | calibrated 2026-01-31 |
| False Alarm Rate | ≤ 5% | calibrated 2026-01-31 |
| Fitness | — | 0.793 |

**As an M01 feature:** removing all `m03_*` cols costs **−0.22 Sharpe** (mid-pack contributor;
total return 198%→114%). **As a standalone sizing lever:** **no-op** (M03-banded Sharpe 0.20 vs
flat 0.21) — de-levers without timing skill, unlike VIX-banded which does add edge. See
[2026-07-02_backtest_arena_session.md](../session_logs/sprint_13/2026-07-02_backtest_arena_session.md).

## 6. Version History / Journey

- **Built as a 3-pillar traffic light** (Trend/Liquidity/Risk), calibrated against a ground-truth
  regime list. Reached Cohen's D 2.24 / GFC lag 10d at config **v1.3.0** (the "hybrid" tuning).
- **Sprint 13 — reframed from predictor to descriptor.** The drawdown-*prediction* framing was
  tested three ways (lead-lag sweep, conditional outcomes, rotation) and **rejected**: no danger
  factor leads; the correlation to forward return *rises* with horizon. M03 is a **coincident vol
  meter**, useful for M01 selection and 1–2wk vol targeting, not for timing. See
  [2026-06-23_tail_analysis.md](../session_logs/sprint_13/2026-06-23_tail_analysis.md).
- **Sprint 13 — kept in M01, rejected as model-baked sizing.** Ablation confirmed M03 helps M01
  (−0.22 if dropped) → keep it as a feature. But stripped from the *models* elsewhere
  (`fs_m01_no_macro`) and re-tested as a pure sizing lever → no-op. Macro's honest role is
  *confirming* trend, not scoring names or timing entries.

## 7. Usage

```bash
# Nightly regime compute (production path)
.venv/Scripts/python.exe src/regime_pipeline.py     # or via the daily orchestrator

# Historical scores (vectorized) / M01 features — from M03RegimeCalculator
#   calculate_history_vectorized(start, end, freq)   → full history DataFrame
#   generate_m01_features(start, end)                → normalized 7-col M01 feature block
#   should_gate_signal(score)                        → {allow_longs, reduced_sizing}
```

- **Feeds:** M01 feature sets (via `generate_m01_features`) + the macro dashboard gauge.
- **Sizing:** if used at the backtest sizing layer, prefer **VIX bands** (validated edge) over
  M03 bands (no-op). Watch the 0–100 vs 0–1 scale (§3).
- Config lives in `models/m03_config.json`; re-calibrate thresholds with
  `M03Evaluator.calibrate_thresholds(ccr_target, far_target)`.

## 8. Roadmap / Open Questions

1. **CAPE valuation pillar (dashboard 6th pillar)** — Yale `ie_data.xls` CAPE is ~1000d stale
   (frozen 2023-09); build a daily FRED-derived CAPE proxy, and *quantify the gap* before swapping
   it in. Isolated to the dashboard valuation pillar — no model/backtest impact.
2. **VIX sizing through the WF gate** — the validated sizing edge is VIX's, not M03's; confirm it
   survives out-of-sample walk-forward before trusting magnitude.
3. **`veto_flag` follow-up** — the one danger signal with a genuine forward-negative skew
   (P(neg) 36% @63d vs 24% base) — worth a separate look as a fragility overlay.

## 9. Sources

- Module passport (code structure): [docs/modules/model_m03.md](../modules/model_m03.md)
- Session logs: [2026-06-23_tail_analysis.md](../session_logs/sprint_13/2026-06-23_tail_analysis.md),
  [2026-07-02_backtest_arena_session.md](../session_logs/sprint_13/2026-07-02_backtest_arena_session.md),
  [macro_dashboard_implementation_plan.md](../session_logs/sprint_13/macro_dashboard_implementation_plan.md),
  [signs_of_tail.ipynb](C:\Users\Hang\PycharmProjects\quantamental\notebooks\signs_of_tail.ipynb),
  [regime_model.ipynb](C:\Users\Hang\PycharmProjects\quantamental\notebooks\regime_model.ipynb)
- Calibration reports: `models/m03_calibration_20030101_20251231.md`,
  `models/m03_evaluation_*.md`
- Code: `src/pipeline/m03_regime.py`, `src/regime_pipeline.py`, `src/evaluation/m03_evaluator.py`,
  `src/evaluation/m03_ground_truth.py`
- Config/artifacts: `models/m03_config.json` (v1.3.0), `models/m03_history.parquet`
