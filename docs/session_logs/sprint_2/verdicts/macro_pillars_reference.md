# The 6 Macro Pillars — reference & how to read them

**What this is:** the interpretation layer for the dashboard's 6-pillar macro view. The plumbing
already exists (`load_macro_pillars` in `scripts/dashboard_utils.py`); this doc says what each
pillar *means*, how to read its percentile, and — critically — what role it does and doesn't play
in the strategy. Written 2026-07-07 (sprint 14 Goal "New macro in sizing"). Not a plan; a reference.

> **One-line orientation:** the 6 pillars are a **sizing / risk-context gauge, shared across all
> tickers**. They answer *"how much total exposure should we carry"*, NOT *"which stock to pick"*.
> They cannot break selection ties (every candidate sees the same macro), so they are irrelevant
> to the gate-vs-ranker question. Keep that boundary — it's why regime stays out of the M01 score.

## The pillars

Source: `load_macro_pillars()` reads `macro_data` (single writer = Phase 1 macro pipeline; no live
fetch). Each pillar is shown as a **percentile 0–100**. Two ranking regimes:
- **Fast Risk pillars** (VIX, Credit, Term Spread) → **all-time** percentile rank.
- **Slow Fundamental pillars** (Rates, Liquidity, CAPE) → **5-yr rolling** (1260-trading-day) rank.

| # | Pillar | Raw series (formula) | Rank | High percentile means… |
|---|--------|----------------------|------|--------------------------|
| 1 | **Equity Fear (VIX)** | `VIX` | all-time | Fear/stress high → **risk-off**. The one pillar with proven sizing value (below). |
| 2 | **Credit Stress** | `BAMLH0A0HYM2` (HY OAS) | all-time | Credit spreads wide → funding stress → **risk-off**. Leads equity in true crises. |
| 3 | **Growth Fear (Term Spread)** | `DGS10 − DGS2` | all-time | ⚠️ **read with care** — a *high* term spread is normal/steepening (benign); a *low/negative* (inverted) spread is the recession warning. High percentile ≠ risk-off here. |
| 4 | **Financial Conditions (Rates)** | `DGS10` | 5-yr roll | Rates high vs recent history → tighter conditions → headwind for growth/momentum names. |
| 5 | **Capital Flow (Net Liquidity)** | `WALCL/1000 − WTREGEN/1000 − RRPONTSYD` (≈ $bn) | 5-yr roll | Liquidity high → **risk-on** tailwind. This is Fed balance sheet minus TGA minus RRP. |
| 6 | **Valuation (CAPE)** | `CAPE_OURS` (self-computed; Yale CAPE dormant, cross-check only) | 5-yr roll | Expensive market → **poor long-horizon** expected return. Slow-moving; a *context* gauge, not a timing trigger. See [[project_cape_ours_pillar]]. |

### Reading the dashboard colours
Green `<40` (benign) · Yellow `40–75` (elevated) · Red `>75` (extreme). **Caveat:** this colour
map assumes "high percentile = bad", which is true for VIX/Credit/Rates/CAPE but **inverted for
Liquidity** (high liquidity is good) and **ambiguous for Term Spread** (see above). Don't read the
colour literally for pillars 3 and 5 — read the direction.

## What they're for: sizing, not selection

The strategy separates *what to hold* (M01 score → rank → pick) from *how much* to hold
(`src/backtest/macro_sizer.py` → a daily weight `w(date) ∈ [0,1]` fed to
`equity_curve(trades, exposure=w)`, lagged 1 day, no lookahead). The pillars are candidate inputs
to that **sizing** lever only.

### What sprint 13 already settled (don't re-litigate)
- **VIX-banded sizing ADDS value** — it's the live sizing lever. Bands (fixed hypothesis, not
  tuned): VIX `<15 → 1.00`, `15–25 → 0.60`, `25–35 → 0.30`, `≥35 → 0.15`.
- **M03-banded sizing is a NO-OP** — banding the M03 regime score to exposure didn't beat flat.
  M03 is out of the sizing axis. (It also stays out of the M01 *score* to avoid double-counting.)
- **No macro pillar times *entries*.** The macro-vs-sweep study found none of these signals
  predicts *when* to start; the one weak directional lever was the 5-factor `veto_flag`
  (veto-off starts +32.6%/+22.1% mean/median vs veto-on +21.7%/+10.0%). That's a coarse
  risk-off *veto*, not a fine timer.

### The open question sprint 14 is testing
Does any of the **other 5 pillars earn a place next to VIX** in the sizing lever, or is the axis
just VIX (+ maybe the 5-factor veto)? Candidates worth a banded-sizing test, in rough priority:
1. **Credit (HY spread)** — the strongest theoretical complement to VIX; leads in funding crises
   where VIX can lag. Most likely to add orthogonal risk-timing.
2. **Net Liquidity** — regime tailwind/headwind; slower, may overlap with VIX bands.
3. **CAPE / Rates / Term Spread** — slow context; unlikely to help *timing*, more useful as a
   "temper size in expensive/tight regimes" overlay than a trigger.

**How to test (don't hand-wire):** add a `<pillar>_weight()` method to `MacroSizer` mirroring
`vix_weight()` (banded, lagged), then confirm the uplift **OOS** via `run_strategy_wfo.py` — the
same gate that proved M03 a no-op. Only fold a pillar into the champion if it beats VIX-alone OOS.

## Boundaries / gotchas
- **Percentiles use look-ahead** (all-time / rolling rank over the *full* series) — fine for a
  "where are we historically" gauge, **never feed these percentiles into a backtest or model**
  (`load_macro_pillars` docstring says so explicitly). For sizing, band the *raw* series lagged,
  as `MacroSizer` does.
- **Term Spread and Liquidity invert the "high = bad" intuition** — see the reading notes above.
- **CAPE_OURS is the live valuation source**; Yale CAPE froze 2024-09 (dormant cross-check).
  Winsorized — that clip is a load-bearing concentration cap, not cosmetic. [[project_cape_ours_pillar]].
- These are **display-only** on the dashboard today. Nothing here sizes the live book except VIX.

## See also
- Sizing code: `src/backtest/macro_sizer.py` · Loader: `scripts/dashboard_utils.py::load_macro_pillars`
- Sprint 13 macro study: `docs/session_logs/sprint_13/cells/macro_vs_sweep_return_cells.md`
- CAPE proxy findings: `docs/session_logs/sprint_13/verdicts/cape_fred_proxy_findings.md`
- Memory: [[project_cape_ours_pillar]]
