# R2 — Leadership-profile contrast EDA (Minervini step 3, reverse-engineered from fwd returns)

**Date:** 2026-07-10 · **Status:** 📋 PLAN (not started) · **Parent:** `sepa_funnel_meta_plan.md`
**Cost:** 1–2 sessions, read-only EDA via notebook cells (`cells/` .md per rules). No training.

## The thesis

Minervini's step 3 scores similarity to past super-performers. The dataset to reverse-engineer that
profile already exists: `label_registry/m01a_tail_v1.json` — 1.61M `trend_ok` panel rows, 11.45%
realized home-runs (`home_run_63` = MFE_63 > 30%). Step 3 = a **descriptive contrast**: home-run rows
vs rest-of-panel, characterized *at entry*. No model — the ML track record here (M3, m02) says a
fourth ranker is not the move; a trait checklist is.

## Trait set (entry-time, all computable from existing tables)

| Trait | Source / proxy | Book rationale |
|---|---|---|
| Market cap | `shares_outstanding × close` (per-date XS rank) | young/small leaders |
| Liquidity / float proxy | `dollar_volume_avg_20`, `shares_outstanding` | thin float fuels runs |
| Listing age | days since first `price_data` bar (proxy — history start ≠ IPO, state the caveat) | super-performers cluster < ~10y from IPO |
| Distance from 52w high | `dist_from_52w_high` | leaders emerge near highs |
| Base character | `consolidation_duration`, `consolidation_width`, `vcp_ratio` | tight, mature bases |
| Group leadership | `rs_industry_rank`, `rs_vs_industry`, `industry_momentum` (⚠️ XS-rank casing bug — verify columns resolve before trusting) | leaders lead their group |
| Sector / industry | categoricals | sector carry is the one proven residual ([[project_breakout_pool_refinement]]) |
| Volatility signature | `adr_20d`, `natr` | high-ADR names produce the tails |
| Earnings proximity | `days_since_report` | moves cluster around reports |

Per-date cross-sectional ranks for cap/liquidity/age (raw levels aren't comparable across 25 years).

## Milestones

- [ ] **M0 — Univariate contrast.** Per-trait decile → home-run rate + mean `tail_mag_63`, home-runs
  vs panel. Anti-tests inherited from m01a: monotone **to the top decile** (the m02 "decile-7 peak"
  trap), and stable across date-thirds. **Deliverable:** one lift table + small-multiple ramp chart.
- [ ] **M1 — RS-stacking test (the part that matters).** A trait only earns a passport line if it adds
  lift *on top of* the shipped signal: 2-way split `rs_universe_rank` D10 × trait tercile. Report the
  per-date rank correlation vs RS for every candidate — a trait that's RS in disguise is dropped even
  if it "wins" M0. **Gate:** ≥1.3× within-RS-D10 lift, monotone, date-stable.
- [ ] **M2 — The passport.** Compose survivors into the "super-performer passport": a one-page trait
  checklist with measured lifts, interaction notes, and NULL results listed just as prominently
  (step 4 needs to know what does NOT matter). Include the top-30 historical home-run names as
  worked examples (eyeball validation against the book's archetypes).
- [ ] **M3 — Step-4 handoff (scope with user).** Decide the passport's operational form: a column set
  on the dashboard watchlist vs a standalone review sheet. NOT a new model, NOT auto-gating —
  step 4 is explicitly manual in the book; keep it that way until the passport proves stable.

## Guardrails / gotchas

- `read_only=True`; label rows from the registry `source_query`, never re-derived; ROOT-anchored
  paths in cells ([[feedback_no_direct_notebook_edits]]).
- Survivorship shape: contrast is *within* the trend panel (already conditioned), so classic index
  survivorship doesn't apply — but listing-age proxy biases old-data tickers; report coverage.
- MFE labels sit on dirty highs history — corrupt highs were source-nulled 2026-07-10 but lows were
  deliberately kept ([[project_price_data_ohlc_dirt]]); MFE (high-based) is the clean side, fine.
- This is label-level (watchlist ordering). Any monetization claim routes through R3's harness —
  do NOT promote a passport trait to a strategy claim from EDA alone (the M4 lesson).

## Kill criteria

- No trait stacks ≥1.3× on RS-D10 → step 3 collapses into RS as well; passport ships as a
  descriptive/manual-review aid only, meta plan annotated.
- A trait monotone only pre-2019 → same decay verdict as M3, excluded from the passport.

## Done when

Verdict doc (`verdicts/YYYY-MM-DD_r2_leadership_profile.md`) + the passport artifact; meta-plan R2
box checked; step-4 form agreed with the user.
