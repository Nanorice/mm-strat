# Backtest Studio (`/backtest`) — Design & Revision Plan

> Sprint 14, dashboard uplift. Planning doc only (no implementation).
> **Tier 2 (workshop) — do NOT theta-style.** Dense/mono is correct here.
> This page EXISTS (`scripts/pages/4_Backtest_Studio.py`) but **contradicts the
> new methodology** and needs structural revision. Ref reflection:
> `logs/2026-07-15_02_reflection_and_atr_fix.md` (G6 rewrite + 3-currencies spine).

---

## What it is

The researcher's backtest browser: lists runs (`manifest_version=v1` only),
shows per-run trades, equity/drawdown, regime/sector breakdowns, and a compare
view. Correct *role*, wrong *framing*.

---

## Methodology-adherence gap (the reason for this doc)

Sprint 14 settled the **3 currencies** — C1 label / C2 OOS / C3 exit-P&L — and
the master lesson **label-lift ≠ trade-edge**. The **model card was brought into
line** (C1 banner, all metrics tagged label-level). **The Studio was not touched
and now contradicts the doctrine:**

| # | Current behaviour | Violates | Fix |
|---|---|---|---|
| 1 | Headlines a **single Sharpe** per run (`report.py`→`"sharpe_ratio":"Sharpe"`, table col) | **G6 rewrite** killed the vec-style single-Sharpe; champion is **start-time dependent** (`project_champion_starttime_dependent`) — one Sharpe is the misleading draw the sprint disproved | Demote single-Sharpe to per-run detail; **promote the start-date CONE** (median / floor / %neg across `champion_trail`) as the primary verdict |
| 2 | **No currency label.** Studio numbers are **C3 (exit-P&L)** but nothing says so; user can't tell card AUC (C1) from Studio Sharpe (C3) | 3-currencies spine; the confusion the card's banner exists to prevent | Add a **C3 banner** mirroring the card's C1 one |
| 3 | **No cone surface** — the `champion_trail` start-date cone lives in `run_cone_gate.py`/promotion gate, absent from the Studio | The cone IS the trade verdict now | Surface the cone; this is where the **OOS-gate "Gate" tab** belongs (Tier-2 review) |
| 4 | vec & BackTrader runs sit in one table, look comparable | vec is optimistic — median Sharpe 1.51 vs BackTrader 0.35 same config (`project_vec_engine_optimistic`) | **Tag engine** per row; caption vec as ranking-only |

---

## Revised design

**Banner (new).** Standing C3-currency caveat, mirroring the card's C1 banner:

> *All metrics here are **trade-level (currency C3: exit-P&L)**. A single run is
> **one start-date draw**, not the edge — the champion is start-time dependent.
> The trade verdict is the **start-date cone** below. (Label-level C1 metrics
> live on the model card.)*

**Section order (verdict-first, not run-first):**
1. **Cone verdict** (promoted) — for the selected strategy/model, the
   `champion_trail` start-date sweep: **median Sharpe · floor · %neg · Calmar**,
   incumbent-anchored thresholds, pass/fail. This is the "did it earn promotion"
   answer = the **Gate tab** merged in.
2. **Run browser** (kept) — table of individual runs, now with an **Engine**
   column (vec / BackTrader) and vec captioned ranking-only-optimistic. Single
   Sharpe demoted to a per-run detail column, not the headline.
3. **Per-run detail** (kept) — trades, equity/DD, regime & sector breakdowns.
4. **Compare** (kept).

**Engine discipline.** Promote on **BackTrader**; vec = ranking only
(`project_vec_engine_optimistic`, `project_minervini_progfills_fails_bt`). The
Engine tag + caption enforce this visually.

---

## Data status

- Cone: `run_cone_gate.py` / `champion_trail` sweep output already exists — surface
  it, don't recompute. May need a small materialized `cone_summary` table (or read
  the gate's artifact) → add to slim-DB `MANIFEST` if a new table.
- Per-run metrics/trades/equity: already read from run artifacts. No gap.
- Engine tag: from `manifest.json` (strategy/engine field) per run.

**Data gap: near-zero.** This is a **reframing**, not a data project — surface the
cone that already exists, relabel the currency, tag the engine.

---

## Build order

1. Add the **C3 banner** (cheapest, highest clarity win).
2. **Engine column + vec caption** on the run table.
3. **Promote the cone** as section 1 (merge the OOS-gate/Gate concept here).
4. Demote single-Sharpe to detail.

Tier-2 page — keep dense/mono; no cream/serif restyle.
