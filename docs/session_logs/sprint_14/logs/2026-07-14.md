# Session Handover: 2026-07-14

## 🎯 Goal
Execute the regime-indicator test manual — settle, once and for all, whether *any* coincident regime
gauge (15 candidates: SPY/QQQ technicals + market breadth) beats the incumbent SPY-200d at telling
bad-days-for-our-strategy from good ones. Then assess the next thread (§1.2 regime-tiered usage).

## ✅ Accomplished
- **Built the full research harness** (3 reproducible scripts + a notebook generator): candidate
  feature builder (expanding-z, shift(1), as-of identity self-check), Block-A WFO AUC sweep, Block-C
  BackTrader cone with candidate-gate swap.
- **Block A (nowcaster) — all 15 candidates FAIL.** Best pooled OOS AUC = breadth **0.55** vs SPY-200d
  baseline **0.531** (reproduced the plan's re-baseline exactly). Nothing near the 0.65 wall; the only
  statistically-significant deltas (block-bootstrap, 50d blocks) are candidates *worse* than baseline.
- **Block C (cone) — both §7 leads FAIL.** §6.8 slope candonly median Sharpe 0.59 / breadth candonly
  0.46 (both *worse* than baseline 0.76); composed-OR arms are washes (≈0.76 — candidate deploy-days
  overlap SPY>200d, the overlap trap). Breadth's calm-year AUC 0.71 did NOT convert to P&L.
- **Regime-expression question CLOSED** — 5th independent falsification. Documented back into the
  regime-tiering plan; §0.5.4 fork resolves to ONE axis → §1.2 unblocked.
- **Assessed §1.2** and wrote it into the plan: §1.2a/§1.2b are a cheap re-cut of existing cone
  `trades.parquet` (no new backtests); recommended order (§1.2b gate-sweep first); honest prior baked in.
- **Deliverable notebook** built + executed clean (16 cells, 5 figures) + consolidated verdict.

## 📝 Files Changed
- `docs/session_logs/sprint_14/scripts/regime_candidate_features.py` (NEW): SPY/QQQ technicals +
  whole-universe breadth, live-safe, as-of identity self-check.
- `docs/session_logs/sprint_14/scripts/regime_candidate_blockA.py` (NEW): WFO AUC nowcaster sweep,
  50d embargo, block-bootstrap CI.
- `docs/session_logs/sprint_14/scripts/regime_candidate_cone.py` (NEW): Block-C cone, candidate-gate
  swap. (SPY-gate hoisted to a single DB load + retry after a foreign-kernel DB-lock crash.)
- `docs/session_logs/sprint_14/scripts/build_regime_indicator_nb.py` (NEW): regenerates the notebook.
- `docs/session_logs/sprint_14/cells/regime-indicator-results.ipynb` (NEW): deliverable notebook.
- `docs/session_logs/sprint_14/verdicts/2026-07-14_regime_indicator_manual.md` (NEW): consolidated verdict.
- `docs/session_logs/sprint_14/plans/2026-07-13_regime_tiering_and_system_usage.md`: closure of the
  regime-indicator program + §1.2 assessment + next-actionable marked.
- Caches (regenerable): `data/model_output_eda/regime_gauge/{candidate_features_daily.parquet,
  blockA_results.json}`, `data/selection_sweep/starttime/cand_{slope,breadth}_cone_summary.json` +
  cone cell dirs (`cand_slope_*`, `cand_breadth_*`).

## 🚧 Work in Progress (CRITICAL)
- **None half-finished.** All blocks complete, notebook executes clean, verdict final.
- **One caveat on the cone crash:** the cone crashed twice mid-run on a *foreign* process (system-
  Python PID 4988, ~1GB) holding `market_data.duckdb` READ-WRITE, locking out read-only opens. It
  exited on its own; I hoisted the SPY-gate to a single DB load + retry so my runner no longer opens
  the DB per-cell. Resume-safe cells (equity.parquet skip) preserved all completed work. **Result
  unaffected** — verified by recomputing cone stats directly from the equity curves.

## ⏭️ Next Steps
1. **§1.2b — per-regime gate sweep (NEXT ACTIONABLE).** Re-cut the UNGATED `champion_trail` cone's
   90 `trades.parquet` (2664 trades, both regimes); tag each by SPY-200d-at-entry; sweep the entry
   gate 0.15→0.30 on the above-200d (bull) subset. Diagnostic only — promote to a bull-only cone if
   the split shows the pooled Q47 median hid a regime interaction. Tests the user's live-pick hunch.
2. **§1.2a — per-regime fan/cone** (only if §1.2b shows the split matters): two cones (bull-start vs
   chop-start), not one blended.
3. **§1.1 / earnings breaker cones** (already wired, un-run) — the chop-tier's floor-lift overlays.

## 💡 Context/Memory
- **The whole exercise was a disciplined RETIREMENT, and it retired cleanly.** The manual itself
  pre-registered the AUC 0.65 bar as "a WALL, by design." The null was the expected, correct outcome.
- **Why it fails:** regime signal is a *mean-shift*, not day-level *separability* — reconfirmed now
  from a completely fresh (price/breadth) feature set, not just the macro pillars.
- **The overlap trap is the recurring killer:** any candidate gate that correlates with SPY-200d, when
  OR'd with it, collapses to ≈ SPY-200d. Composed arms are washes for exactly this reason.
- **§1.2 honest prior:** the 200d gate already captures most of "trade in bull, stand aside in chop."
  Realistic §1.2 upside is confirming whether the gate is regime-conditional + formalizing a chop
  stand-aside tier — NOT a second alpha engine. Don't oversell it.
- **DB-lock lesson:** a foreign kernel holding the DB read-write blocks all read-only opens on Windows.
  Per-cell DB opens are fragile; hoist shared lookups to one pre-loop load with retry.
