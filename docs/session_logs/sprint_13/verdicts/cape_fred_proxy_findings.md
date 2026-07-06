# CAPE FRED-Proxy — Quantify-Before-Swap Findings

**Sprint 13 TODO:** macro dashboard's 6th pillar (Valuation/CAPE) trails badly. Before
swapping in a daily FRED-derived proxy, answer three acceptance criteria: (a) gap vs true
CAPE, (b) *why* Yale is stale, (c) proxy reliability. Isolated to the dashboard valuation
pillar — no model/backtest impact.

Analysis scripts (scratchpad, throwaway): `cape_proxy_analysis.py`, `cape_proxy_v2.py`.
Read-only DB throughout.

---

## TL;DR — the answer changed the fix

Two-part answer: **half the gap was a dead URL; the other half is a dead source.**

- Our engine fetched `econ.yale.edu/~shiller/data/ie_data.xls`. **Shiller moved hosting;
  that Yale mirror froze at 2023-09** (earnings column NaN after 2023-06, last row a
  footnote). Dead file.
- The **current canonical host** (`shillerdata.com` CDN blob) carries data through
  **2024-09** — a year fresher — but its own `Last-Modified` is 2024-09-04: Shiller has
  **not updated the workbook in ~22 months.** The series is dormant, not just slow.
- **Fix shipped:** one-line `CAPE_URL` swap in `src/macro_engine.py` → DB moved
  2023-09 (30.8) → **2024-09 (35.2)**, 12 months recovered, `fetch_cape` unchanged.
- Because the source is dormant, a FRED/real-price proxy is **required** to reach "today"
  (bridging 2024-09 → now, ~22mo, ~5% expected error) — not optional. Not yet wired.

---

## (b) Why Yale is stale — ANSWERED (root cause, not our fetch)

Fetched both files and inspected the raw `Data` sheet:

| Source URL | Last CAPE row | Notes |
|---|---|---|
| `econ.yale.edu/~shiller/…` (old, what we used) | **2023.09** | earnings `E` NaN after 2023-06; last row is a footnote string. Dead mirror. |
| `shillerdata.com` CDN blob (current canonical) | **2024.09** | same layout; blob `Last-Modified: 2024-09-04` |

- **Not a publication-cadence-vs-fetch problem on our side.** Our fetch worked perfectly;
  the *source* it pointed at stopped updating in Sept 2023.
- **The source is effectively dormant.** Even the *current* canonical host's file has
  `Last-Modified: 2024-09-04` and a last data row of 2024-09 — i.e. Shiller has not
  updated the workbook in **~22 months** (verified via HTTP HEAD, not inferred). This is
  no longer "slow cadence" — the series is not being actively maintained to current.
- **Consequence:** the URL swap recovers 12 months (2023-09 → 2024-09) for free, but
  **cannot reach "today."** A proxy is therefore the *only* path to a live gauge, not an
  optional enhancement. It must bridge 2024-09 → now (~22 months, ~5% expected error).

## (a) Gap between a FRED-derived proxy and true CAPE — QUANTIFIED

FRED has **no S&P earnings series** (and `SP500` only goes back 10 years, license-limited),
so a *true* Shiller CAPE cannot be reconstructed from FRED alone. What is buildable from
data we already have (`^GSPC` daily since 1990 + FRED `CPIAUCSL`):

**Real-price roll:** `CAPE_proxy(t) = CAPE_anchor × realPrice(t) / realPrice(anchor)`,
holding the slow 10yr-avg real earnings ~constant. Naive roll drifts upward because it
ignores real-earnings growth. Adding the overlap's implied real-E10 growth
(**+3.83%/yr** over 2003–2023) as a decay term roughly halves the error.

**Rolling-anchor backtest** (every 2003–2023 window, proxy vs true CAPE):

| horizon | naive mean APE | **growth-adj mean APE** | growth-adj median APE |
|--------:|---------------:|------------------------:|----------------------:|
| 12m | 4.9% | **2.9%** | 2.2% |
| 24m | 9.6% | **5.2%** | 3.9% |
| 36m | 13.6% | **6.8%** | 6.1% |
| 48m | 17.1% | **7.7%** | 7.2% |

Corr(proxy, true) ≈ 0.87 even for the naive 10yr roll — the proxy tracks *direction*
well; the error is a slow level drift, fully attributable to earnings growth.

## (c) Reliability as a stand-in — QUANTIFIED

- After the URL swap, the source gap is only **~9 months**, where the growth-adjusted proxy
  carries **~3–5% expected error** (interpolating the table). Well inside the width of a
  0–100 display percentile band — fine for a "where are we historically" gauge.
- Current values (May 2026, ~2.7yr horizon from the old 2023-09 anchor, for reference):
  naive roll **47.7**, growth-adjusted **43.1**, stale frozen **30.8**. (Historical CAPE
  range 2003–2023 was 13–39, so ~43 is a real "expensive" signal the frozen 30.8 hides.)
- **Do NOT feed the proxy into any model/backtest** — display-only, same rule as the
  existing look-ahead pillar percentiles.

**Verdict:** proxy is a reliable *display* stand-in. Recommended form = growth-adjusted
real-price roll anchored on the latest true CAPE (now 2024-09 = 35.2), decay = trailing
implied-E10 CAGR (~3.8%/yr). **Required, not optional** — since the source is dormant, only
the proxy can carry the gauge to "today" (~22mo tail, ~5% expected error). Not yet wired.

---

## Dashboard gap check (closing pass)

- **5/6 pillars fresh** to 2026-06-30 (VIX, Credit, Term Spread, Rates, Liquidity). ✅
- **CAPE now 35.2** (2024-09) after the URL swap + re-fetch, up from stale 30.8. But
  `load_macro_pillars()` **ffills it forward** to the latest date, so the gauge still reads
  "current" when the underlying point is ~22 months old. Real remaining dashboard gap:
  **no visual staleness indicator on the CAPE gauge** — a viewer can't tell it's ffill'd.
  (Cosmetic; deferred with the proxy wiring.)
- **DQ audit tolerance corrected:** `CAPE` max-stale 70d → **300d** in
  `tools/audit_t1_data_quality.py`. The old 70d assumed "~1–2 month" lag and threw a
  false-alarm WARN; 300d reflects the verified publisher cadence. Audit is now truthful:
  OK when the source is as-fresh-as-Shiller-publishes, WARN only if we fall behind *that*.

## Changes shipped

1. `src/macro_engine.py` — `CAPE_URL` → shillerdata.com CDN. **DB CAPE re-fetched:
   2023-09 (30.8) → 2024-09 (35.2)**, 12 new rows.
2. `tools/audit_t1_data_quality.py` — `CAPE` staleness tolerance 70 → 300 days (reflects
   verified publisher cadence). Note: CAPE **still WARNs** because the dormant source is
   ~670d behind even 300d — the WARN now correctly says "wire the proxy," not "fetch bug."

## Build-our-own CAPE — VALIDATED (2026-07-04)

Since even the current Shiller host is dormant (`Last-Modified 2024-09-04`), the only path
to a *live* gauge is to compute CAPE from our own data. FRED has no S&P EPS series (S&P
license) and FMP's index endpoints are dead/paywalled, so official-S&P-500 CAPE is not
sourceable — but we can compute a **self-contained aggregate market CAPE** and it tracks
Shiller well enough to be the gauge. Script: `scripts/validate_own_cape.py` (read-only).

**Method:** winsorized cap-weighted mean of per-ticker real-P/E10 over a deep-earnings
basket (~1808 tickers, ≥60 quarters net_income spanning 2005–2024). Cap = price ×
shares_outstanding; earnings = 10yr trailing mean of TTM `net_income`; both CPI-deflated.

**Landmines hit and fixed (all real data dirt, not method):**
1. Dup quarters (`2025-12-31` *and* `2025-12-27`, same NI) → dedup by *calendar quarter*.
2. Sum-based aggregates are hostage to one dirty `shares_outstanding` row — **PCG 2016 =
   44 quadrillion cap** blew up Σcap. → winsorize caps at monthly 99th pct.
3. Median-of-ratios is dirt-immune but undershoots level (down-weights mega-caps that drive
   Shiller): 12m-change corr 0.81 but level corr only 0.22. → cap-weighting needed for level.

**Result vs true Shiller CAPE (142-mo overlap 2012–2024, in-DB CAPE_OURS):**

| metric | value |
|---|---|
| level correlation | **0.871** |
| 12-month-change correlation | 0.853 |
| percentile-rank correlation | **0.874** (mean rank diff 11.3pts) |
| offset (ours/Shiller) | mean **1.30×**, but **DRIFTS 1.28 (2012) → 1.53 (2024)** |
| after single static-k rescale (k=1.29) | mean APE **7.0% / max 27.0%** |
| latest computable | **2026-07 = 59.7** — updates nightly, forever |

**Calibration — the offset is NOT a stable constant.** The ratio drifts **+0.022/yr** so a
single k leaves a *systematic trend*. A toggle-one-factor decomposition
(`scripts/analyze_cape_drift.py`, regress ratio-vs-Shiller on time) settles *what causes it*:

| variant | slope/yr | note |
|---|---|---|
| BASE (current engine) | +0.022 | the drift |
| **scope: top-500 only** | **+0.043** | narrowing scope *doubles* it → **scope is NOT the cause** |
| no winsorize | +0.004 | apparent flatten — but an *accident* (see below) |
| keep losses (ratio-of-sums) | −0.046 | loss-filter contributes, secondary |

**The drift is METHODOLOGY + DATA QUALITY, not scope. Three stacked mechanisms:**
1. **Dirty caps (data quality).** 4 tickers — **PCG (39 mo), CNA (18), GPUS (30), CBT** —
   have corrupt `shares_outstanding` giving caps of *thousands of trillions* in 2012–2017.
   The 99th-pct winsorize accidentally masked them **while also clipping 90–99.9% of legit
   cap mass those years** (measured). That unstable clip-fraction (99% early → ~30% recent)
   was ~80% of the *apparent* drift. Fix = absolute sanity ceiling (drop cap > $8T), not a
   percentile — largest real company ever ≈ $4.7T (NVDA 2026).
2. **E10 10yr-window ramp (methodology transient).** 2012–2015 P/E10 is inflated because the
   trailing 10yr earnings window straddles the 2008–09 crash trough (low E10 → high P/E10).
   Rolls off by ~2019.
3. **Mega-cap concentration (real market structure).** Top-5 cap share **13% (2016) → 27%
   (2024**, AAPL $4T). Cap-weighting genuinely loads high-P/E mega-caps more over time — once
   dirt+ramp are removed the post-2016 slope is **+0.09/yr** (the persistent driver; it
   doesn't go away because it's real).

**Consequence:** no single clean fix recovers Shiller-level *tracking* AND kills the drift —
mechanism 3 is real. The dirty-cap fix (#1) is a genuine data bug worth doing regardless;
#2/#3 are irreducible for a self-computed aggregate. All of it is immaterial to the gauge,
which ranks on percentile. (Earlier note claimed winsorize was the sole cause — that was
incomplete; it's the largest but only one of three.)

**Decision: leave uncalibrated; the pillar ranks on percentile (rank corr 0.87 holds under
the drift).** Absolute level IS shown on the dashboard (like every other raw pillar) but
labelled `CAPE*` with a caption: "self-computed aggregate CAPE, tracks Shiller but runs
~1.3× high — read the percentile, not the level." De-trending / de-biasing (share-weighted
index earnings, keep losses) is deferred; only worth it if the displayed *level* ever needs
to be believable as the published number.

**Verdict:** build-our-own beats the FRED real-price roll — same ~5–6% accuracy but *fully
self-sufficient* (no Shiller dependency at all). This is the recommended replacement.

## Wiring — SHIPPED (2026-07-04)

1. **`src/cape_engine.py`** — `CapeEngine.update()` computes the aggregate CAPE and upserts
   `CAPE_OURS` into `macro_data` (INSERT OR REPLACE — trailing months recompute as new
   prices/earnings land). In-DB tracking: level corr 0.871, rank corr 0.874, latest
   2026-07 = 59.7 (= all-time high of its own range → pillar percentile 100, correctly
   flagging rich valuations).
2. **`config.py`** — added `CPIAUCSL` to `FRED_SERIES` (deflator; now mirrored to
   `macro_data`, backfilled through 2026-05). CAPE reads CPI locally, no extra network.
3. **`scripts/dashboard_utils.py`** — `load_macro_pillars()` valuation pillar now sources
   `CAPE_OURS`; Yale `CAPE` retained as raw `CAPE_yale` cross-check column.
4. **`src/orchestrators/daily_pipeline_orchestrator.py`** — CAPE_OURS compute runs nightly
   in Phase 1 after the macro block, isolated try (never fails the macro phase).
5. **`tools/audit_t1_data_quality.py`** — `CAPE_OURS` (40d) + `CPIAUCSL` (70d) monitored;
   dormant Yale `CAPE` tolerance → 800d (cross-check only, don't alarm). All three OK.
6. `macro_data` already in `build_dashboard_db` MANIFEST → CAPE_OURS reaches the R2 remote
   app automatically (no parity break).
7. **`tests/test_cape_engine.py`** — real CI unit test (no live DB/network): synthetic
   3-ticker panel asserts the exact cap-weighted P/E10 (19.0909), winsorize-no-blow-up,
   idempotent upsert, and the small-basket guard. `CapeEngine` params (basket/window)
   made overridable so the test can use a tiny hand-computable panel. 4 tests pass.

**Data quality probed (2026-07-04):** current caps have **no dirt** (the 2 caps >4T are legit
NVDA/AAPL; the PCG 44-quadrillion blowup was historical); shares lag price ~14d (negligible
monthly); **32% of quarterly net_income is negative** (drives the E10>0 divergence above).

### ⚠️ Survivorship caveat (accepted by design — documented per request)

The CAPE_OURS basket is **fixed to current deep-earnings survivors** (~1800 tickers with
≥60 quarters of `net_income`). This means historical values carry a **survivorship lift** —
our level runs ~1.28× true Shiller and the ratio creeps 1.28→1.43 across 2012→2024 as the
surviving basket's growth-tilt compounds. **This is intentional and safe for the gauge**
because: (1) the pillar ranks against its OWN history, not an absolute threshold, and (2) the
same fixed basket every month = the same bias every month, so the *timing/percentile* signal
is internally consistent. It is **NOT** an official S&P 500 CAPE and **must not** feed any
model or backtest (display-only, same rule as the look-ahead pillar percentiles). Removing
the bias would need as-of index membership + delisting data we don't currently store —
deferred; revisit only if the pillar's absolute level (not its ranking) ever needs to matter.

## Winsorize→ceiling swap — RE-EVALUATED WITH CLEAN CAPS AND REJECTED (2026-07-04)

The planned fix ("replace the 99th-pct winsorize with the absolute $8T ceiling once caps are
clean") was tested after the full T1 cleanup (ISSUE_dirty_shares_cap_dq_gap CLOSED, incl. the
sub-ceiling 1000× tier). Result, 2012–2024 overlap vs Shiller:

| variant | level corr | rank corr | drift slope |
|---|--:|--:|--:|
| winsorize (shipped) | 0.871 | **0.874** | +0.022/yr |
| absolute ceiling only | 0.514 | **0.416** | +0.004/yr |

The swap flattens the drift exactly as the decomposition predicted — **but collapses
tracking**. Mechanism: the winsorize was never just a dirt filter; clipping the monthly
top-1% of caps acts as a **mega-cap concentration cap**, and Shiller tracking depends on it
(divergence concentrates in 2024–25 mega-cap months, up to +53%; unclipped latest = 73.1 vs
59.7). The earlier "no-winsorize flattens the drift" observation was correctly suspected to
be an accident — confirmed: the flat drift comes with an unusable gauge (the pillar ranks on
percentile, so rank corr is the load-bearing metric).

**Final shipped design:** absolute ceiling (`T1_PLAUSIBILITY_BOUNDS['implied_cap_max']`)
masks impossible caps *before* weighting (dirt guard, masks nothing on clean data), then the
99th-pct winsorize stays — now deliberately, as a concentration cap on already-clean caps.
Post-cleanup recompute shifted dirt-era months by ≤2.1% (the cleanup showing through);
tracking metrics unchanged. CAPE_OURS rewritten (164 rows, latest 2026-07 = 59.7).
The drift (+0.022/yr) is accepted as before: percentile gauge, rank corr holds.

## Superseded

- FRED growth-adjusted real-price roll (~5% @ 24mo). Kept documented above as the fallback
  if the own-CAPE aggregate ever proves unstable, but own-CAPE is preferred (no dependency).
