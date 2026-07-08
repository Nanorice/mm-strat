# Sprint 15 — <theme TBD>

**Dates:** 2026-07-08 → TBD · **Status:** 🔄 Active · **Prev:** [sprint_14](../sprint_14/README.md)

> <one-paragraph framing — fill when goals are set.> Sprint 14 shipped the M6 regime STATE label and
> established that m01's ranking is regime-robust while the stress-return gap grows with the hold. The
> open thread it hands over: the stress sub-split is NOT settled, and the regime work hasn't reached
> the real product surfaces (SEPA-candidate during-period lens, dashboard).

### Folder map
- **`RESEARCH_LOG.md`** — linear question ledger (create on first entry).
- **`logs/`** — dated session handovers.
- **`plans/`** — forward-looking design/plan docs.
- **`verdicts/`** — findings / reports.
- **`cells/`** — notebook-cell artifacts (`*_cells.md`).

## Carried over from sprint 14
- [ ] **Settle the regime STRESS sub-split** — persistence filter (de-flicker; both axes have
  median 1–4d runs) + a **vol/VIX-percentile stress cut** (`spy_vol20` already computed; ≈ a VIX
  cut, so it grounds the stress axis in the S13-validated sizing signal and fixes the dd-sparsity /
  macro-leak). cf `sprint_14/verdicts/2026-07-08_m6_regime_state_label.md` §3b/§5.
- [ ] **Run the dd regime axis on the SEPA-CANDIDATE population pre-2013** — the real "does it reach a
  2008-scale crash" test AND the model-agnostic during-period lens on the actual watchlist (survives
  m01/m04 recalibration). This was the durable M6 goal; consumer #2 used the full universe, not the
  candidate grain yet.
- [ ] **Dashboard: current-state regime badge + regime strip** beneath the 6-pillar table — DEFERRED
  as a separate deliverable (user, 2026-07-08). Payload = the state→level+CI table
  (`sprint_14/verdicts/2026-07-08_m01_by_regime.md`).
- [ ] **Feed regime as a training FEATURE into m01/m04** (once the stress axis is settled) — the label
  is date-keyed and joinable; the finding (ranking regime-robust, level regime-dependent) suggests
  regime helps LEVEL calibration more than ranking.
- [ ] **M4 regime-reweighting** — runnable now, but the counter-cyclical finding argues AGAINST
  down-weighting stress/bear rows (the edge is BEST there). Parked; revisit only with a direction.

## New goals (sprint 15)
<!-- user to fill: the sprint's actual theme + goals -->

## TODOs
<!-- sprint-local isolated TODOs; cross-session facts go to memory -->
