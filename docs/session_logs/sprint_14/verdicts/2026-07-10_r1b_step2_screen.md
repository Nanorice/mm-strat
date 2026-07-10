# R1b verdict — Mark's step 2, tested book-faithfully: SUBSUMED by RS, not null; screen dominated at every depth

**Date:** 2026-07-10 · **Plan:** `plans/r1b_step2_book_faithful_plan.md` · **Status:** ✅ CLOSED — all milestones ran
**Data:** full `trend_ok` panel per `m01a_tail_v1` source_query (1,611,203 rows, 2001–2026), labels
MFE_63 **and** MFE_126 computed in one window pass (entry-day excluded, full forward window required).
**Repro:** `scripts/r1b_build_panel.py` → `r1b_m0.py` / `r1b_m1.py` / `r1b_m2.py` / `r1b_m2b.py` / `r1b_m2c.py`.
**Cache:** `data/research_cache/r1b/` (panel parquet + every result table as CSV).

## TL;DR

1. **Step 2 is real but upstream of RS — "subsumed", not null.** `revenue_growth_yoy` and
   `gross_margin_trend` have genuine unconditional monotone ramps on the panel (D10/D1 tail ≈ 1.74×)
   and are exactly the criteria positively rank-correlated with RS per-date (ρ = 0.22 / 0.12). R1's
   within-D10 null is explained: the signal exists, RS already carries it. The mediation hypothesis
   from the plan is CONFIRMED for these two criteria.
2. **The book's headline EPS criteria are null-to-inverted on this panel.** `eps_growth_yoy` and
   `eps_accel` are **U-shaped**: the worst EPS-growth decile has a *higher* home-run rate (0.149)
   than the best (0.140). "EPS ≥ 25%" cuts off an equally home-run-rich left arm (turnaround /
   low-base names). As a *screen* they subtract capture without adding lift.
3. **The verbatim screen is dominated by RS at every depth.** Depth-matched at the screen's own
   3.7% selectivity: screen tail lift **1.48×** vs pure-RS **4.54×** (63d); 1.53× vs 3.42× (126d).
   Stacked on RS-D10 it adds a rounding error (2.14× vs 2.06×) while destroying capture (4.2% vs 58%).
4. **No horizon rescue (M3).** At MFE_126 the screen improves marginally (1.48→1.53) and RS softens
   (2.06→1.86 at D10), but there is **no crossover** — RS dominates at both horizons, everywhere.
5. **Surprise finding: the missing-fundamental bucket is the hottest cohort in the funnel** —
   tail lift 2.2–2.9×, **era-stable**, 8% of the panel. Silently dropping missing-fundamental rows
   would discard the most home-run-rich names. See §6.

**Operational conclusion:** unchanged and now general — the one-column RS rule stays the selection
gate. R1's verdict upgrades from scope-narrowed to general, with the *characterization* corrected
from "null" to "subsumed" for revenue growth / margin trend. All label-level; monetization routes
through R3 (no strategy claims from EDA).

---

## M0 — Corrected step-1 gate: RS-percentile floor sweep

The book's RS ≥ 70 (1–99 percentile scale) mapped onto our scale = per-date percentile of the
`rs_rating` composite → `rs_universe_rank` ≥ 0.70/0.80/0.90. Key structural fact: **the trend
template already does most of the RS selection** — within `trend_ok` the median `rs_universe_rank`
is the **84th percentile** (p25 = 73rd). The "missing" step-1 RS floor was largely implicit.

| RS floor | rows | % of panel | names/day (med) | tail lift 63 | HR capture 63 | tail lift 126 | HR capture 126 |
|---|---:|---:|---:|---:|---:|---:|---:|
| panel (none) | 1,611,203 | 100.0 | 232 | 1.00 | 100.0 | 1.00 | 100.0 |
| ≥ 70pct | 1,275,488 | 79.2 | 193 | 1.19 | 90.7 | 1.16 | 87.1 |
| ≥ 80pct | 972,341 | 60.3 | 151 | 1.44 | 80.2 | 1.38 | 73.7 |
| ≥ 90pct (=RS-D10) | 540,622 | 33.6 | 84 | 2.06 | 58.0 | 1.86 | 49.0 |

**Corrected step-1 gate = RS ≥ 70pct**: proper floor semantics — keeps 91% of all panel home-runs
while trimming 21% of names. Depth (≥90) buys lift by sacrificing capture; that trade belongs to a
later funnel stage, not step 1. (Panel-level baselines: HR rate 11.5% @63d, 24.3% @126d.)

## M1 — The book's step-2 preferences, quantified holistically

Criteria mapped (% units confirmed — book thresholds transfer verbatim): `eps_growth_yoy ≥ 25`,
`revenue_growth_yoy ≥ 20`, `gross_margin_trend > 0`, `eps_accel > 0`, `revenue_accel > 0`.
Note: `eps_accel` **is** in `t3_training_cache` — R1's set (from `fs_m01_prototype`) excluded it;
R1b tested it. Missing rates 8.0–9.2% per criterion.

### (a) Portraits + selectivity drift

| criterion | panel p50 | pass rate | HR median | rest median | verdict lens |
|---|---:|---:|---:|---:|---|
| eps_growth_yoy ≥ 25 | 12.5 | 36.0% | **5.4** | **13.0** | HRs have *worse* median EPS growth than the rest — U-shape |
| revenue_growth_yoy ≥ 20 | 9.7 | 25.4% | 14.5 | 9.3 | clean separation, right direction |
| gross_margin_trend > 0 | 0.5 | 55.5% | 0.98 | 0.46 | clean separation |
| eps_accel > 0 | 3.0 | 48.4% | 1.6 | 3.1 | no separation |
| revenue_accel > 0 | 1.1 | 51.9% | 2.3 | 1.0 | weak separation |

Selectivity drift (per-year pass rates, `m1_pass_rates_by_year.csv`): `eps_growth_yoy` swings
**22% (2001) ↔ 47% (2005) ↔ 23% (2009)**; `revenue_growth_yoy` collapsed to **7.3% in 2009** and
spiked to 50% in 2022. The book's fixed numbers are strongly pro-cyclical in selectivity — a "25%
EPS growth" bar means a different animal in a recession trough than in a boom. Margin/accel
criteria are stable (~46–60%).

### (b) Mediation check — the plan's core question

Unconditional per-date decile ramps (full panel, home-run rate by criterion decile):

| criterion | D1 HR | D10 HR | D10/D1 tail | D10/D1 HR | shape | mean per-date ρ vs RS |
|---|---:|---:|---:|---:|---|---:|
| revenue_growth_yoy | 0.120 | 0.181 | **1.74** | 1.52 | monotone ↑ | **+0.22** (89% dates > 0) |
| gross_margin_trend | 0.107 | 0.150 | **1.74** | 1.41 | monotone ↑ | **+0.12** (84%) |
| revenue_accel | 0.130 | 0.161 | 1.26 | 1.23 | shallow U, top tilt | +0.08 |
| eps_growth_yoy | **0.149** | 0.140 | 0.99 | 0.94 | **U — D1 beats D10** | +0.05 |
| eps_accel | 0.144 | 0.140 | 0.98 | 0.97 | U, flat ends | +0.02 |

**Readout (per the plan's logic):** ramps monotone unconditionally + dead within-D10 (R1) + positive
RS correlation = *fundamentals → outperformance → RS* mediation confirmed for revenue growth and
margin trend. They are **upstream of RS — "subsumed", not null**. The EPS pair is a genuine null
(actually U-shaped) — the panel's home-runs include turnaround phenotypes the book's EPS bar excludes.
126d ramps (in `m1_decile_ramps.csv`) are materially identical — the shapes are not horizon artifacts.

### (c) Interaction structure

The 5-way conjunction selects **4.33%** of panel rows — a coherent, non-empty cohort (the book's
archetype exists in the data). Binding constraints: `revenue_growth_yoy` (25.4% solo) and
`eps_growth_yoy` (36.0%); joint rev×eps only 13.0%.

## M2 — The book-faithful screen, judged holistically

Screen = 5-way conjunction, book verbatim, + staleness guard `days_since_report ≤ 135`
(91d quarter + ~44d filing grace; zombie fundamentals fail rather than pass — only 0.4% of RS≥70
rows are stale). Applied on M0's corrected step-1 survivors (RS ≥ 70pct).

### Funnel triples (the alpha lens)

| arm | % of panel | names/day | tail lift 63 | HR capture 63 | tail lift 126 | HR capture 126 |
|---|---:|---:|---:|---:|---:|---:|
| RS ≥ 70 (step 1) | 79.2 | 193 | 1.19 | 90.7 | 1.16 | 87.1 |
| RS-D10 | 33.6 | 84 | 2.06 | 58.0 | 1.86 | 49.0 |
| SCREEN alone | 4.3 | 10 | 1.36 | 6.2 | 1.40 | 5.9 |
| **SCREEN ∧ RS≥70 (book funnel)** | 3.7 | 9 | **1.48** | **5.8** | 1.53 | 5.4 |
| SCREEN ∧ RS-D10 | 2.1 | 5 | 2.14 | 4.2 | 2.05 | 3.7 |
| missing-fund bucket (RS≥70) | 8.2 | 19 | **2.40** | 14.4 | 1.85 | 10.6 |

**Depth-matched head-to-head** (the decisive table, `m2c_depth_matched.csv`) — same 3.7% selectivity:

| arm @ 3.7% depth | tail lift 63 | HR rate 63 | HR capture 63 | tail lift 126 | HR capture 126 |
|---|---:|---:|---:|---:|---:|
| SCREEN ∧ RS≥70 | 1.48 | 0.177 | 5.8 | 1.53 | 5.4 |
| **pure RS top 3.7%** | **4.54** | **0.323** | **11.1** | **3.42** | **7.7** |

The screen is not merely redundant — at equal selectivity RS finds **3× the tail magnitude** and
~2× the home-runs. Substitutes-vs-complements: 85% of screen survivors are already inside RS≥80,
56% inside RS-D10 (Jaccard 0.05/0.06 — the screen is a small, mostly-interior subset). **Verdict:
subsumed-and-dominated.**

### Who survives (the archetype check)

Sector tilt vs RS≥70 base: Energy +4.2pp, Technology +2.9pp, Financials +2.0pp; Healthcare −3.6pp,
Consumer Cyclical −2.0pp. Cap/age (age = years since first price bar; `listing_date` is 100% NULL
in `company_profiles` — data gap): screen survivors median cap $3.3B, median age 10.6y, only 7.9%
younger than 3y — **the screen does NOT select the book's young-growth archetype**; it selects
established mid/large-caps with clean growing financials, *fewer* young names than its own base
(9.4%). The young-growth archetype hides in the missing-fund bucket (below).

### Era stability

| arm | P1 <2012 lift 63 | P2 2012–18 | P3 2019+ |
|---|---:|---:|---:|
| RS-D10 | 2.00 | 2.16 | 1.97 |
| SCREEN ∧ RS≥70 | **2.14** | 1.40 | **1.29** |

The screen's residual lift decays monotonically across eras while RS is flat — it inherits the M3
temporal-break suspicion (features beat RS pre-2019 only) and is not a standing gate. Per
[[project_regime_during_period_goal]]: WHEN it worked = pre-2012; it has been fading for 15 years.

Threshold sensitivity (secondary): monotone tighter→more lift, less capture (15/10: 1.06×@8.1%;
35/30: 1.78×@3.9%) — no setting approaches the depth-matched RS line. Book numbers are not the problem;
the axis is.

## M3 — Horizon extension (MFE_126)

Ran as dual-horizon columns through every M1/M2 table (label form identical to `m01a_tail_v1`,
126-bar forward window, full window required, 1.58M rows have it). The earnings-thesis-is-slower
hypothesis **fails**: ramp shapes unchanged at 126d, screen lift 1.48→1.53 vs RS-D10 1.86 and
depth-matched RS 3.42 — the gap narrows slightly but there is no crossover. The 63d label does not
under-serve the earnings axis enough to matter.

## §6 — The missing-fundamental bucket (unplanned finding)

Rows failing the screen because fundamentals are absent (8.2% of RS≥70) are the **highest-lift
cohort in the whole exercise**: tail lift 2.06/2.86/2.25 across the three eras — *more* era-stable
than the screen. They are younger (15.5% < 3y vs 8.6% panel) and much smaller (median cap **$0.98B**
vs $3.1B). Youth split shows it is not purely an IPO effect (missing & old ≥3y still 2.35×).
Mirror image: **RS≥70 ∧ mature ∧ full-fundamentals ≈ 1.01× — no tail at all.** The panel's tail
lives in young/small/sparse-coverage names. ⚠️ Caveat: `tail_mag` is not risk-adjusted — small-cap
volatility inflates MFE mechanically; this is a *label-level* lead (candidate watchlist axis:
cap/coverage, alongside RS), strictly R3-gated for any trade claim.

## Kill-criteria evaluation (from the plan)

- ~~M1 flat unconditionally~~ → did NOT fire: rev growth + margin trend have real ramps → **subsumed
  branch**, not general-null branch.
- **M2 screen ≈ RS with high interiority → substitutes; RS stays the operational gate** — FIRED
  (85% interior to RS≥80, dominated 3× depth-matched). One column beats five thresholds.
- **Era-conditional** — FIRED for the screen's residual (pre-2012 only) → not a standing gate.
- No label-level WIN to route to R3 from the screen itself; the missing-fund cohort is the only
  new lead.

## Mapping table (row-by-row, feeds the meta-plan)

| Book criterion | Mapped to | Verdict | Evidence |
|---|---|---|---|
| RS rating ≥ 70 (step-1 #8) | `rs_universe_rank` ≥ 0.70 | **PROVEN (as floor)** | 91% HR capture at 79% of panel; trend template already implies median 84th pct |
| EPS growth YoY ≥ 25% | `eps_growth_yoy` | **NULL (U-shaped)** | D1 HR 0.149 > D10 0.140; HRs' median EPS growth below the rest's |
| EPS acceleration (Code-33 shadow) | `eps_accel` | **NULL** | flat U; no separation HR vs rest |
| Sales growth YoY ≥ 20% | `revenue_growth_yoy` | **SUBSUMED by RS** | monotone 1.74×/1.52× unconditional; ρ=+0.22 vs RS; dead within-D10 (R1) |
| Sales acceleration | `revenue_accel` | weak / mostly NULL | 1.26× ramp, shallow U |
| Margin expansion | `gross_margin_trend` | **SUBSUMED by RS** | monotone 1.74×/1.41×; ρ=+0.12; dead within-D10 (R1) |
| Earnings surprise | — | **UNTESTED** (unmapped; R4 trigger unfired) | |
| Estimate revisions | — | **UNTESTED** (unmapped) | |
| True Code-33 streak (multi-quarter) | — | **UNTESTED** (only 1-quarter accel proxies exist) | |
| Base count / VCP stage | — | **UNTESTED here** (technical, lives in VCP features, out of R1b scope) | |

An unmapped criterion is not a null — but note the R4 trigger ("R1b finds step-2 signal that needs
the unmapped criteria") did **not** fire: the mapped growth criteria that work are already inside RS.

## Guardrail compliance

`read_only=True` throughout; labels from the registered `m01a_tail_v1` source_query (forward windows
strictly exclude entry day); forward paths from `price_data`, never shift on t3; staleness handled as
fail-not-pass; missing rows tracked as their own bucket (and turned out to be the headline finding).
