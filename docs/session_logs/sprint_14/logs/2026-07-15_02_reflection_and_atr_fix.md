# Session Handover: 2026-07-15 (session 02)

## 🎯 Goal
Close the last open regime item (§1.2a), distil the sprint's hard-won meta-knowledge into durable
artifacts (memory + methodology doc + model-card assessment), and — surfaced mid-session — fix a
serving-side feature bug that blocked the m01_binary model card.

## ✅ Accomplished
- **§1.2a regime-tiered fan/cone (Q72) — the tier IS the SPY-200d gate.** Re-cut the 90-cell ungated
  `champion_trail` cone by SPY-200d (no new backtest). Cut A (start-tag): bull-start median Sharpe 0.37
  vs chop-start 0.15. Cut B (honest day-attribution): **chop-days −2.0 annualized Sharpe** vs bull-days
  +1.15 — all the loss lives on days deployed below 200d. No standalone chop edge to tier into →
  tiered usage = deploy in bull / stand aside in chop = the shipped gate. Cells + chart + verdict.
- **Reflection deliverables (user's 3 questions → distil bottom-up):**
  - **`project_standing_epistemics` memory** — the ~12 recurring traps in one ranked ledger (master:
    label-lift ≠ trade-edge; a C1 win is a hypothesis until it clears the C3 cone). Indexed as the hub.
  - **`model_development_methodology.md` rewritten** (not appended): added the **3-currencies spine**
    (C1/C2/C3 mapped onto the gates), tagged each gate's currency, **rewrote G6** (out: the vec-style
    single-Sharpe portfolio_backtest; in: BackTrader-confirm + start-date CONE + the C1→C3 death), added
    the RS one-column bar to G2/G3 + "2019+ or it doesn't ship", updated stale m01_rank/4-class framing.
  - **`docs/model_doc/m01.md` enriched** (via document-model): corrected the champion (binary is prod,
    4-class archived — verified from `model.json` + registry), replaced arena/WF numbers with the cone,
    added **§2a label/score-nature assessment** (gate-not-ranker, upside-only/quantized label,
    label-lift≠trade-edge, continuation-only/regime-blind, size axis). Fixed 3 dead links.
- **Model-card currency banner** (`report.py`) — a standing "all metrics are label-level C1;
  label-lift ≠ trade-edge; trade verdict is the strategy cone" banner. Card is already
  strategy-independent (A–G all label-level; equity-fan ≈ Section D's decile table — no new code needed).
- **`atr_pct_chg` view-regression bug — FOUND + FIXED.** The v3.1 delta refactor (2026-07-02) dropped
  the raw feature `atr_pct_chg` from `v_d2_training`/`v_d3_deployment` EXCLUDE lists (no `_delta` twin).
  Card builder hard-failed on it. **Fixed** (removed from both EXCLUDE lists), recreated views, refreshed
  `d2_training_cache`. **Verified prod was NOT degraded** — model trained 2026-05-24 (before the bug),
  and live scoring reads `v_d3_lifecycle` which never lost the column. **m01_binary card rebuilt** (banner
  present, A–F real metrics AUC 0.807; Section G stubbed — see WIP).
- **Answered:** retrain? No (trained on the real feature). Training range? 2003–2026 no-holdout; the
  anchored WFO (expanding train) is how "does more history help" is tested; expanding blindly isn't free.
- **MEMORY.md compacted** 20.3→16.6KB (m01-modelling one-liners trimmed to hooks).

## 📝 Files Changed
- `src/managers/view_manager.py`: restore `atr_pct_chg` to scoring views (2 EXCLUDE lists).
- `src/evaluation/model_card/report.py`: currency-C1 banner + `.banner.currency` style.
- `docs/architecture/model_development_methodology.md`: 3-currencies spine + G6 rewrite + RS bar.
- `docs/model_doc/m01.md` + `README.md`: binary-champion correction + §2a assessment.
- `docs/session_logs/sprint_14/RESEARCH_LOG.md`: Q72 + carried-open update.
- `docs/session_logs/sprint_14/plans/2026-07-13_regime_tiering_and_system_usage.md`: §1.2a done + §INFRA todos.
- NEW: `cells/regime_tiered_cone_cells.md`, `scripts/regime_tiered_cone.py`,
  `verdicts/2026-07-15_regime_tiered_cone.png`.
- Memory: NEW `project_standing_epistemics`, `feedback_readonly_connections`,
  `project_atr_pct_chg_view_regression`, `project_model_card_section_g_hang`; compacted MEMORY.md.
- DB state (not files): recreated views + refreshed `d2_training_cache` (both now carry `atr_pct_chg`).
- Artifact: rebuilt `model_cards/m01_binary_v1.html`.

## 🚧 Work in Progress (CRITICAL)
- **Model-card Section G is STUBBED, not computed.** Section G (edge-existence permutation/bootstrap,
  `section_g_edge.py`) HANGS in multiprocessing on the dev box — a child burned 1600s+ CPU at 500×500,
  and even 20×20 spun 50s+ → structural, not iteration count. The rebuilt card has A–F real + G marked
  SKIPPED. `project_model_card_section_g_hang`.
- **IDE watcher deadlock (env, not code):** something auto-spawns a SYSTEM-python (`C:\Python312`) copy
  of any script run, which races the `.venv` copy and deadlocks on the DB lock. Made the card build a
  whack-a-mole; the final untouched attempt won. Disable the watcher before the next card build.
- Nothing half-finished in the code — both fixes are complete + verified.

## ⏭️ Next Steps
1. **Fix Section G hang** — add a timeout + serial fallback or `--skip-section-g`, then rebuild the
   m01_binary card with G real (banner + view fix already in place).
2. **Disable the IDE run-on-save / debugpy watcher** that spawns the system-python script copies.
3. **Make the card builder's advisory DB write-back optional/read-only-safe** (needless write forces a lock).
4. **Sync ops box `sh019`** — nightly scheduler there still has 4-class as prod in its own DB.
5. Sprint is otherwise saturated → the remaining research item is Q69 (model-skill-regime gate).

## 💡 Context/Memory
- **The reflection produced a coherent doctrine, bottom-up as the user asked:** distil traps → memory
  (`project_standing_epistemics`) → reconcile → methodology doc. The 3 currencies (C1 label / C2 OOS /
  C3 exit-P&L) are now the organizing spine, and G6 was the stalest gate (it still used the vec engine +
  single Sharpe the whole sprint disproved).
- **The `atr_pct_chg` bug is a clean lesson:** the live scorer's NaN-fill-on-missing HIDES a dropped
  feature (scores "fine" but degraded); the card builder's hard-fail is the canary that surfaced it.
  Consider a feature-contract assert across the scoring views. Timeline analysis (trained-before-bug +
  live-view-kept-the-column) is what proved no retrain was needed — don't assume; check the dates.
- **Card ≠ gate boundary confirmed:** the model card is strategy-independent (label-level C1, + fan-style
  studies); the cone is a strategy verdict that lives in the promotion gate. The banner states this.
