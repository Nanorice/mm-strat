# Deliverables Roadmap — Shortlist + Weather Gauge (bridge to ship)

**Date**: 2026-07-12 · **Sprint**: 14 (deployment) · **Status**: ✅ A + B SHIPPED (2026-07-12) — B5 stress stabilization still open

> **Shipped 2026-07-12**
> - **Part A** — `v_d3_shortlist` view (built ON `v_d3_lifecycle` active cohort, not a fresh
>   re-join), `load_shortlist()`, `render_shortlist()` on `page_today`, MANIFEST entry.
>   Model-swap via `status_flag='prod'` (NOT a "champion flag" — no such column exists).
>   No `COLUMN_CASE_MAP` change needed (display view, not model-fed).
> - **Part B** — `src/weather_engine.py` (reuses `MacroSizer` for stress+brake, adds the
>   §1c supply gauge), `weather_gauge` table, Phase 7.45 in the orchestrator (WARN mode,
>   before dashboard build), `load_weather_gauge()`, `render_weather_gauge()` headline chip
>   + tiles + 250d history strip. MANIFEST entry.
> - ⚠️ **`DEPLOY MORE` fires ONCE in 2003–2026** (2010-05-07): the bull-stress-famine pocket
>   is genuinely rare (stress days mostly coincide with SPY≤200d — same GATE×TILT tension as
>   the governor). Rule is faithful to §B3; the chip is near-dead as a live signal. Revisit
>   when B5 stabilizes stress (may loosen `stress_high` from top-quintile).
> - **Still open**: B5 (stress sub-axis flicker-stabilization) — gauge ships stress provisional.

---
**Original plan (below) — Status was**: 📋 PLAN — not started
**Goal**: turn the sprint-14 research (all banked as verdicts) into two shippable products —
(1) a **confident daily shortlist for manual review**, (2) a **weather gauge** combining
6-pillar macro + SPY-200d + stress + breakout-supply into one presented state.

> Research is ~done; both deliverables are ASSEMBLY of already-validated parts, not new
> studies. The only open research is the **stress sub-axis** (README: leaky/sparse/flickery).

---

## 0. What already exists (don't rebuild)

| Piece | Where | State |
|---|---|---|
| SEPA universe + sessions | `sepa_watchlist` (SepaWatchlistManager) | live, nightly `update_daily` |
| Dashboard trade log | `screener_watchlist` (ViewManager) | live, shipped in dashboard DB |
| Model scores (serving) | `daily_predictions` keyed by `model_version_id` | materialized nightly; **model file never on serving host** (`load_scored_watchlist`) |
| 6-pillar macro (display) | `load_macro_pillars()` → `render_macro_dashboard()` | live panel, per-pillar percentiles |
| Stress composite (live-safe) | `macro_sizer._stress_ew_vix()` | computed in BACKTEST only, never persisted |
| SPY-200d gate (live-safe) | `macro_sizer.spy_above_200d()` | computed in BACKTEST only, never persisted |
| Breakout-supply gauge | EDA §1b/§1c (AUC 0.93, famine∧>200MA pocket) | **verdict only — no code, no table** |
| Regime M03 | `t2_regime_scores` | live, shipped |

**The gap in one sentence:** every signal exists as either a *backtest-only function* or a
*verdict finding*; none of the weather-gauge inputs is a **persisted daily row**, and the
shortlist has no **ranked, tagged artifact** — just the raw `sepa_watchlist` + `daily_predictions`.

---

## PART A — The Shortlist (leverage `sepa_watchlist`)

### A1. What the shortlist IS (research → product mapping)
The sprint located the edge (`summary_eda_linear_story` §E/§H): **tail phenomenon at
strong-RS × small-cap**, m01's unique add is **industry-tail** (+9.7pp within (RS,size) cell),
liquidity-capped (~$7.5M/day), median inverts. So the shortlist is:

> today's ACTIVE SEPA breakouts, ranked by **RS-decile × size × m01 prob_elite**, liquidity-
> filtered, tagged **defensive** (low rel-vol / rel_ulcer) vs **aggressive** (tail), presented
> as **tail-odds not a point forecast**.

### A2. Infra decision — VIEW, not a new table
**Recommendation: a DuckDB VIEW `v_d3_shortlist`, materialized into the dashboard DB nightly**
(same pattern as `v_d3_deployment` / `v_d3_prebreakout` — MANIFEST `materialize_view`).

Why view not table:
- It's a **JOIN of things already materialized**: `sepa_watchlist` (ACTIVE) ⋈ `daily_predictions`
  (scores by version) ⋈ `t3_sepa_features` (RS/size/liquidity display cols). No new compute.
- **Model-swap is free** (see A4) — the view keys on `model_version_id`, which already flows
  through `load_scored_watchlist`. Replacing the model = new `model_version_id` rows in
  `daily_predictions`; the view re-points, no schema change.
- ponytail: a table would duplicate `daily_predictions` and need its own refresh + a second
  place model-swap breaks. A view is one SELECT and inherits the existing nightly rebuild.

### A3. Build steps
1. **Define `v_d3_shortlist`** in `view_manager.py` (it owns all `v_d3_*`):
   - Base: `sepa_watchlist WHERE status='ACTIVE'` ⋈ latest `t3_sepa_features` per ticker.
   - Score: LEFT JOIN `daily_predictions` on (ticker, prediction_date, model_version_id) —
     LEFT so an un-scored fresh breakout still appears (NaN-passthrough, `project_backtest_prod_parity`).
   - Columns: ticker, entry_date, session_id, prob_elite (=prob_class_3), rank_within_day,
     RS_Universe_Rank, cap-rank/size, dollar_volume (liquidity), rel_vol tag.
   - **Ranking key**: composite of RS-decile + size + prob_elite (the §3c residual). Encode the
     rank in SQL so the artifact is deterministic and reproducible.
   - **Liquidity filter**: `dollar_volume >= 7.5e6` (the R3 constraint) — as a *tag column* not a
     hard WHERE (let the reviewer see borderline names; default-sort pushes them down).
   - **Defensive tag**: low pre-episode rel-vol / rel_ulcer proxy (§6c live-usable slice).
   - ⚠️ **Casing trap**: `RS_Universe_Rank` etc. are TitleCase XS ranks NOT yet in
     `COLUMN_CASE_MAP` (memory: SQL/DuckDB gotchas). Add them to the map first or the view errors.
2. **Add to MANIFEST** (`build_dashboard_db.py`): `("v_d3_shortlist", "materialize_view", ...)`.
   Dashboard-remote-parity rule (memory): any new loader's table MUST be in the manifest or R2 breaks.
3. **Dashboard page**: new `render_shortlist()` on `page_today()` (or a dedicated page). Present
   as a ranked table + a **cone/odds column** (home-run rate for that RS×size bucket), NOT a
   predicted return — the median inverts, so a point forecast would mislead the reviewer (A1 caveat).
4. **Loader**: `load_shortlist(model_version_id)` in `dashboard_utils.py`, mirroring
   `load_scored_watchlist` (keys on version id → model-swap safe).

### A4. Model-replacement story (answered)
**Already solved by the existing serving pattern — reuse it, add nothing.**
- Model scores live in `daily_predictions` keyed by `model_version_id`; the serving host never
  holds the model file (`load_scored_watchlist` docstring, `backfill_daily_predictions.py`).
- To swap the model: train → register (`models` table) → `backfill_daily_predictions.py --model
  <new_version>` writes new rows → dashboard points `model_version_id` at the new version.
- `v_d3_shortlist` is model-agnostic (it JOINs on whatever version id it's given). **No view or
  table change on model swap.** This is the payoff of choosing a view over a table.
- One guard to add: the shortlist page should read the *active* `model_version_id` from a single
  source (the `models` table's champion flag), not a hardcoded string, so swap is one row-flip.

---

## PART B — The Weather Gauge (combine 6-pillar + SPY-200d + stress + supply)

### B1. Infra decision — a new persisted table `weather_gauge`, computed nightly
Unlike the shortlist (a pure join), the gauge **combines signals that are currently backtest-only
functions or unbuilt**. It needs a compute step and a persisted daily row.

**Recommendation: one engine `src/weather_engine.py` → one table `weather_gauge` (date PK),
run in the nightly orchestrator, shipped `full` in the manifest.**

Why a table not a view:
- The stress composite (`_stress_ew_vix`) and supply gauge are **computed, not stored** —
  a view can't hold expanding-z state cheaply; recomputing per dashboard load is wasteful and
  couples the app to backtest code. Materialize once nightly (`project_materialized_scoring` pattern).
- It's small (one row/day) and read at MAX-date — trivial to ship `full`.

### B2. What the gauge row holds (one date = one state)
Promote the backtest-only functions to a live engine (lift, don't fork — reuse `macro_sizer`):

| Field | Source (existing) | Meaning |
|---|---|---|
| `spy_above_200d` | `macro_sizer.spy_above_200d()` | the BRAKE (deploy gate) |
| `stress_z` | `macro_sizer._stress_ew_vix()` | live-safe stress composite (mean of expanding-z) |
| `regime_state` | `t2_regime_scores.m03_score` / trunk | bull/bear (M6 label) |
| `breakout_supply_norm` | **NEW** — daily breakout count / scored-universe size, EMA10/20 | supply gauge (AUC 0.93) |
| `supply_regime` | derived: famine / normal / flood quintile | the §1c state expression |
| `deploy_posture` | **combined verdict** (see B3) | the single headline the reviewer reads |
| 6 pillar percentiles | `load_macro_pillars()` logic | value/stress context (already displayed) |

### B3. The combination rule (this is the "finish what's left" ask)
The research already tells us how these compose — encode it, don't re-derive:
- **SPY-200d is the BRAKE** (the one honest gate). Below 200d → posture = `STAND ASIDE`
  regardless of everything else (§D: it does the honest work).
- **Stress + supply are the DURING-PERIOD STEER** (not brakes). Above 200d:
  - `stress_z` high **∧** supply famine (early-recovery scarcity) → posture = `DEPLOY MORE`
    (the +10.5% vs +3.6% pocket, `entry_timing_macro_axis`). This is the only real tilt.
  - normal → `DEPLOY`.
  - flood + low stress (late-cycle) → posture = `DEPLOY, TRIM NEW` (supply-drift warning).
- **6-pillar macro** = context panel (value/stress axis), NOT a gate — it already flips
  bull↔bear so pooling it is unsafe (§E). Display only.
- ⚠️ **Stress sub-axis is the one OPEN research item** (leaky/sparse/flickery per README). Ship
  the gauge with stress as a *displayed z-score + coarse tercile*, flag it "provisional", and
  close the flicker separately (B5). Don't block the gauge on it.

### B4. Presentation (how to show the weather gauge)
- **One headline posture chip** at the top of `page_today()`: `DEPLOY MORE / DEPLOY / DEPLOY,
  TRIM NEW / STAND ASIDE` with a colour (green→amber→red). This is the "gauge" the user asked for.
- **Below it**: the existing 6-pillar panel (keep) + two new small tiles: SPY-vs-200d (brake
  on/off) and supply famine↔flood quintile. Stress as a labelled z-tile marked provisional.
- **A history strip**: posture over last ~250d (so the reviewer sees regime transitions, not a
  point). Reuse `render_regime_history` charting.
- Rendered in the dashboard (extra tiles/table, per the user's "extra tables shown in dashboard?"
  question): YES — one `weather_gauge` table shipped in the manifest, one `render_weather_gauge()`
  panel replacing/wrapping the current macro header.

### B5. Open research to close (only real study left)
**Stress sub-axis stabilization** — the dd/macro stress split is leaky/sparse/flickery (README M6).
Scope: pick the live-safe variant (`stress_ew_vix` is already the best per Thread F), add
hysteresis/EMA to kill flicker, verify it doesn't leak (expanding-z is causal). One verdict, then
promote `stress_z` from "provisional" to a real steer input in B3. **Do this AFTER the gauge ships
provisional** — the brake+supply already carry the gauge; stress is the enrichment.

---

## PART C — Sequencing & infra summary

**Order** (highest leverage / lowest risk first):
1. **A (shortlist)** — pure join, model-swap already solved, one view + one page. Ships the sprint's
   whole research as a morning artifact. ~1 session.
2. **B1–B4 (weather gauge, provisional stress)** — one engine + one table + one panel. The
   combination rule is already decided (B3). ~1–2 sessions.
3. **B5 (stress sub-axis)** — the only open research; closes the gauge to full. Separate verdict.

**Infra decisions (answering the user's questions directly):**
- *Table or view for the shortlist?* → **VIEW** (`v_d3_shortlist`), materialized nightly. Pure join;
  model-swap free.
- *What happens on model replace?* → **Nothing structural.** Scores are `daily_predictions` keyed by
  `model_version_id`; swap = backfill new version rows + flip the champion flag in `models`. The view
  and dashboard are model-agnostic. (This is exactly why A2 chose a view.)
- *Weather gauge — table or view?* → **TABLE** (`weather_gauge`, date PK), computed by a new
  `weather_engine.py` in the nightly orchestrator. It combines computed (not stored) signals; a view
  would recompute expanding-z per load.
- *Extra tables in dashboard?* → one new table (`weather_gauge`) + one materialized view
  (`v_d3_shortlist`). Both go in the `build_dashboard_db` MANIFEST (parity rule) and
  `sync_dashboard_db`.
- *How to present the gauge?* → one posture chip (headline) + brake/supply/stress tiles + a
  250d posture history strip, wrapping the existing 6-pillar panel.

**Guards to not trip** (from memory):
- `COLUMN_CASE_MAP` must include the XS RS ranks before `v_d3_shortlist` (casing bug).
- Any new table/view MUST be in the dashboard MANIFEST or the R2 remote breaks (parity).
- Notebook/interactive DuckDB connections read_only; nightly engine writes are orchestrator-owned.
- Shortlist presents **tail-odds, not point returns** (median inverts — a forecast would mislead).

**Not doing (YAGNI):** no new ranker model (§3c: within-pool re-ranking is a closed kill), no sector
sizing (§6b killed), no per-name SL / governor in the product (variance knobs, not alpha). The
research says the product is *presentation of the validated tail edge + honest regime posture*, not
another model.
