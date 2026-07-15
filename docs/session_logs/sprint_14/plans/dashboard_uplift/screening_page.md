# Screening Page (`/screening`) — Design & Data-Bridge Plan

> Sprint 14, dashboard uplift. Planning doc only (no implementation).
> Replaces the four overlapping candidate tables on "Today" with one screening
> surface. Ref: theta.md/desk/screening.

---

## What it is

The single **"what to look at" surface**. One population — every name currently
in setup or triggered — filterable by fundamentals and stage, ranked by the
model's honest probability. This is where the four scattered candidate tables on
today's dashboard collapse into one.

**Rename:** the current `sepa_watchlist` table is a *session tracker*
(entry/exit/cooldown) — a different concept. The **screening page population is
not that table**; it's the `trend_ok ∨ breakout_ok` universe. Keep the session
tracker as-is (it feeds Portfolio); "screening" is a fresh view over the feature
table. Don't overload one table with both jobs.

---

## Data reality check

Verified `market_data.duckdb`, 2026-07-16 (latest `t2` date 2026-07-14):

- **Population:** `t2_screener_features` — `trend_ok=581`, `breakout_ok=50`,
  **either=618** of 2,730 scored. Right in theta's ballpark (they show 287 after
  a fundamental pre-filter). Population = one WHERE clause, present today.
- **Fundamentals for columns/filters:** `fundamental_features` has
  `gross_profit`, `net_income`, `revenue`, `free_cash_flow`,
  `revenue_growth_yoy`, `eps_growth_yoy` — margins derive directly.
- **Ranking score:** `daily_predictions` — **no `prob_elite` column**; it's
  `prob_class_1` (binary prod) / `prob_class_3` (4-class), resolved from the prod
  model id (cf. `_rank_metric_for` in the dashboard passport). Ranking is
  **P(Home Run)**, materialized nightly.
- **Missing:** P/E (memory: pe/ps/peg/pb absent from `fundamental_features`) —
  derive `price × shares_outstanding / net_income`, or ingest. Point forecasts
  (expected return / max upside/DD) — **we deliberately don't produce these**
  (see design note).

---

## Column design — theta parity, but honest

| theta column | Ours | Source |
|---|---|---|
| Ticker + name | ✅ | `company_profiles` |
| Price + %chg | ✅ | `price_data` |
| Gross margin | `gross_profit/revenue` | `fundamental_features` |
| Net margin | `net_income/revenue` | `fundamental_features` |
| P/E | derive `px·shares/net_income` | needs `shares_outstanding`; "—" if unprofitable |
| FCF +/− | sign of `free_cash_flow` | `fundamental_features` |
| Revenue growth | `revenue_growth_yoy` | `fundamental_features` |
| **Stage** (ours, not theta) | setup / triggered chip | `trend_ok`,`breakout_ok` |
| **P(Home Run)** (replaces theta "Expected return") | prod-model prob, sort desc | `daily_predictions` |
| Rating date | prediction_date | `daily_predictions` |

**Design note — no fabricated point forecasts.** theta shows "Expected return
−6.2% · max upside +34% · max DD". Our research has *deliberately refused* point
P&L forecasts (label-lift ≠ trade-edge; the start-date cone is our truth, cf.
`project_champion_starttime_dependent`). **Do not copy their ER column.** The
honest analog is **P(Home Run) + the cone caption** we already use on the
shortlist. A "stance" chip may bucket the probability (e.g. top-decile → "Strong
setup") but must not imply a return estimate.

---

## Layout

- **Header stats (mono):** `N in universe · trend_ok N · breakout_ok N · as-of date`.
- **Filter row** (in `st.form` so the rerun fires on Apply, per house rule):
  - Stage: All / Setup (trend_ok ∧ ¬breakout_ok) / Triggered (breakout_ok).
  - Fundamentals: gross margin ≥, net margin ≥, P/E ≤, FCF positive-only,
    rev-growth ≥ — exactly theta's filter set.
  - Sector / market-cap tier.
- **Table:** columns above, default sort **P(Home Run) desc**, sortable.
  Stage as a colored chip; FCF as +/− glyph; P/E "—" when unprofitable.
- **Below:** "Aggressive picks" strip — top P(HR) small-cap tilt (matches the
  shortlist's kept small-cap tilt, `project_binary_promoted_cone_gate`).

---

## The "Today"-page consolidation this replaces

Today's dashboard runs **four overlapping candidate tables** — all "names to
look at," differing only by which slice:

| Today section | Source | → Screening as |
|---|---|---|
| Daily Shortlist | `v_d3_shortlist` | "Aggressive picks" strip (tail-edge slice) |
| Pre-Breakout Watch | `v_d3_prebreakout` | Stage = **Setup** filter |
| Screener Watchlist | `screener_watchlist` | (active *trades* → moves to **Portfolio**, not here) |
| VIP Watchlist | `v_d3_vip` | Stage = **VIP** flag / saved filter |

**Net:** Shortlist + Pre-Breakout + VIP are one population sliced three ways →
one Screening table with a stage filter. Screener Watchlist is *held trades*, a
different job → Portfolio page. The four-table overlap dissolves once Screening
owns the population.

(Full Today-page regrouping — Regime→Macro, Candidates→Screening,
Tracking→Portfolio, Diagnostics→Model Lab — tracked in the dashboard-uplift
overview; this page delivers the Candidates half.)

---

## Build order

1. **View:** `v_d3_screening` = `t2_screener_features` (trend_ok ∨ breakout_ok)
   ⋈ `daily_predictions` (P(HR)) ⋈ `fundamental_features` (margins/growth) ⋈
   `company_profiles`. Materialize/expose; add to slim-DB `MANIFEST`
   (remote-parity, `project_dashboard_remote_parity`).
2. **P/E derivation** (or ingest) — the one missing column.
3. **Page** in the settled style; stage chips + fundamental filters in `st.form`.
4. **Retire** the three redundant Today tables once Screening is live; move
   Screener Watchlist to Portfolio.

**Data gap:** near-zero. Only P/E needs derivation; everything else is a join
over existing tables. This is the **most data-complete page of the uplift** —
build it early.
