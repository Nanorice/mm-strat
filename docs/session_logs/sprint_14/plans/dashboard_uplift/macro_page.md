# Macro Page — Design & Data-Bridge Plan

> Sprint 14, dashboard uplift. Planning doc only (no implementation).
> Three stacked sections, top→bottom in decreasing glance-frequency:
> **(1) regime headline → (2) sector heatmap → (3) full indicator board.**
> The original rough notes are preserved at the bottom under "Appendix: raw notes".

---

## Data reality check (what the DB actually holds)

Grounding for the whole plan — verified against `market_data.duckdb`, 2026-07-16:

- **`macro_data`** (long: `date, symbol, value`): **12 symbols only** —
  `BAMLH0A0HYM2` (HY OAS), `CAPE`, `CAPE_OURS`, `CPIAUCSL`, `DFII10` (10Y real),
  `DGS10`, `DGS2`, `RRPONTSYD`, `VIX`, `WALCL` (Fed BS), `WBAA` (Baa), `WTREGEN` (TGA).
- **`t2_regime_scores`**: the 6-pillar M03 (`m03_score`, `m03_pillar_trend/liq/risk`,
  deltas, regime_vol).
- **`weather_gauge`**: `spy_above_200d`, `stress_z`, `breakout_supply_share`,
  `supply_regime`, `deploy_posture`.
- **`t2_screener_features`**: per-ticker/-date `trend_ok`, `breakout_ok`, RS ranks —
  the bottom-up breadth source.
- **`company_profiles`**: `sector` (11 real + 17 `ETF:*` pseudo), `industry`
  (native Yahoo/FMP taxonomy, **not GICS**).

**Consequence:** Section 2 is ~90% a rendering job on existing data. Section 1 is
buildable now (minus F&G ingest). Section 3 is an **ingestion backlog** — ~54 of
its ~66 indicators do not exist in the DB yet.

---

## Section 1 — Regime headline

**Purpose (settled).** The listed sentiment gauges — Fear&Greed, VIX, HY OAS,
NAAIM, MOVE, AAII — largely **collapse to one factor: risk-appetite**. CNN
Fear&Greed is itself a composite that already ingests put/call, junk-bond demand
(≈ HY OAS) and momentum, so showing F&G *and* its own ingredients double-counts.
Rather than tile one factor six times, we **shift the section's purpose**:

> **Show Fear&Greed (the familiar 0–100 risk-appetite composite) + our 6 M03
> pillars (our own regime answer).** F&G = the market's mood in one number; the
> pillars = our deploy gate. Two complementary lenses, no redundant tiles.

**Layout**
- **F&G gauge** — 0–100 dial + label (Fear/Greed), prior value, Δ.
- **6 M03 pillars** — trend / liquidity / risk (+ the sub-pillars the model
  exposes), each as a percentile-ranked tile with a regime-bias tag
  (LONG / SHORT / NEUTRAL).
- **Deploy headline** — `weather_gauge.deploy_posture` + SPY>200d + breakout
  supply share (bottom-up participation). This is the "should I deploy at all"
  glance and stays load-bearing — it's the research's own answer.

**Data gap** — ✅ CLOSED 2026-07-16 (S1 SHIPPED).
- **Have now:** the 6 macro pillars come from `load_macro_pillars()` —
  VIX / Credit / Term Spread / Rates / Liquidity / CAPE, each with a percentile
  (`macro_data`). ⚠️ **Doc correction:** an earlier draft of this line credited
  `t2_regime_scores` for the "6 pillars" — wrong. `t2_regime_scores` holds M03's
  **three** pillars (trend/liq/risk) + `m03_score`; that feeds the *deploy
  headline*, not the pillar tiles. The live Today page's "6-Pillar Macro
  Environment" has always read `load_macro_pillars`.
- **Fear&Greed — LANDED.** `curl_cffi` `impersonate="chrome"` clears the
  Cloudflare 418 (confirmed: plain urllib → 418, curl_cffi → 200).
  `macro_engine.fetch_fear_greed()` → `macro_data` symbol `FEAR_GREED`; wired
  into the existing `update_macro_cache()` loop, so the nightly Phase 1.4 picks
  it up with **no orchestrator change**. `macro_data` is already MANIFEST-`full`
  → remote parity free.
  - ⚠️ **~1yr history only** (253 rows). CNN serves no deep archive, so this
    series can NOT backfill to 2003 like the FRED ones. Display gauge only —
    never feed a backtest expecting depth.
  - `INSERT OR IGNORE` on the `(date,symbol)` PK means the first write of a day
    wins (F&G drifts intraday). Correct for a nightly EOD snapshot; note it if a
    future consumer needs intraday freshness.
- **Explicitly dropped:** NAAIM, MOVE, AAII as Section-1 tiles — they re-express
  the same risk-appetite factor; if wanted at all they live in Section 3.

---

## Section 2 — Sector / subsector heatmap

**Purpose.** Bottom-up regime read: where is trend/breakout participation
concentrated, and where is today's tape unusual vs. its own history.

**Taxonomy (settled).** Use the **native Yahoo/FMP taxonomy** — no GICS
crosswalk. Granularity is comparable to theta's GICS depth, so divergence in
labels/cut-points is acceptable. Verified per-sector subsector counts:

| Sector | Subsectors | Companies |
|---|---|---|
| Industrials | 29 | 504 |
| Financial Services | 24 | 671 |
| Consumer Cyclical | 23 | 395 |
| Healthcare | 13 | 866 |
| Real Estate | 13 | 232 |
| Technology | 12 | 549 |
| Energy | 12 | 188 |
| Consumer Defensive | 12 | 170 |
| Basic Materials | 11 | 125 |
| Communication Services | 9 | 149 |
| Utilities | 6 | 92 |

(Technology's 12: Software-Application 163, Software-Infrastructure 94,
Semiconductors 74, Hardware/Equipment 62, IT Services 56, Comm Equipment 40,
Computer Hardware 27, Electronic Gaming 10, Consumer Electronics 10, Tech
Distributors 9, Software-Services 3, Internet Content 1.)

**Layout**
- **Top row:** index tiles — S&P 500, Nasdaq, large-cap, small-cap.
- **Sector grid:** 11 real sectors (exclude the 17 `ETF:*` pseudo-sectors).
  Each card:
  - today's cap/equal-weight return + a **KDE of constituent daily returns**,
    with a vertical line marking today's print in that distribution.
  - **breadth bar:** ▲up / ▼down name counts.
  - **participation bar (our addition):** segmented by # `trend_ok` and
    # `breakout_ok`, total length ∝ constituent count; plus **added today** and
    **added past 5d** (date-diff on `t2_screener_features`).
- **Expand on click:** subsector cards render as a row directly below the sector,
  same card format.

**Design constraints (must decide in build, flagged now)**
1. **Min-constituent threshold (~5–10 names).** A KDE over 1–3 names is a dot, not
   a distribution. Subsectors below threshold collapse into an **"Other <sector>"**
   card (e.g. Software-Services=3, Internet Content=1 in Tech). Theta shows the raw
   1-name cards; we won't pretend a distribution exists.
2. **Exclude `ETF:*` pseudo-sectors** from the grid.
3. **Materialize, don't compute live.** Nightly job → a `sector_breadth`-style
   table (per sector/industry/date: return-dist summary stats, up/down counts,
   trend_ok/breakout_ok counts, added-today/5d). Page renders the KDE from summary
   stats, never re-scans `price_data` per pageload. (Slim-DB `MANIFEST` must
   include it — remote-parity invariant, cf. `project_dashboard_remote_parity`.)

**Data gap:** essentially none. All inputs present (`price_data`,
`company_profiles`, `t2_screener_features`). Blockers are the two design
decisions above, not data sourcing.

---

## Section 3 — Full indicator board (~66 indicators, 10 groups)

**Purpose.** The deep reference board: 10 collapsible groups, each indicator with
prior / now / Δ% / sparkline / range. This is a **macro-ingestion backlog**, not a
dashboard task.

**Coverage: 42 of ~66 — SHIPPED 2026-07-16** (was ~12). The **C1 FRED tier is
done**: `config.FRED_SERIES` now carries 45 entries, 42 of them `group`-tagged and
rendering on the board across 8 of the 10 groups. Remaining gaps are **C2**
(AAII/NAAIM/COT scrapes → group 7 Flows) and **C3** (futures/MOVE/VVIX/SKEW/term
premium/FOMC calendar → group 10 + the deferred rows), exactly as tiered below.

⚠️ Two C1 IDs came back **shallower than this doc assumed** (caught by the
pre-commit smoke test, 36/36 fetched): `BAMLC0A0CM` (IG OAS) has only **785 rows
from 2023-07** — it is NOT a deep 2003+ series like its HY sibling
`BAMLH0A0HYM2` (6,148 rows) and would fail M03's 10yr-z bar; `EXHOSLUSM495S`
(existing home sales) is re-based → **13 rows**. Both display fine, neither is
model-grade.

⚠️ **22 of the 42 are FRED-REVISED** series captured at **first print only**
(`write_to_macro_data` is `INSERT OR IGNORE`). Display-only — see
`config.FRED_SERIES` for the flag and the `INSERT OR REPLACE` upgrade path.

**Triage into 3 ingestion tiers** (build the board incrementally; grey out
missing rows, don't gate the page on all 66):

| Tier | Source class | Examples | Cost |
|---|---|---|---|
| **C1 — free daily/weekly FRED** | FRED (already our source) | GDPNow, jobless/continuing claims, payrolls, unemployment, U-6, IP, retail sales, PCE/core PCE, PPI, breakevens (5Y/10Y/5Y5Y), 3M/30Y treasury, 3M-10Y, SOFR, IORB, M2, C&I loans, DXY, gold, WTI, housing (starts/sales/Case-Shiller), vehicle sales, CC delinquency | **Low** — extend `macro_engine`, ~1 pass |
| **C2 — weekly scrape** | HTML/CSV scrape | AAII bull/bear, NAAIM, CNN Fear&Greed, CFTC COT | Medium — parsers + schedule |
| **C3 — live/premarket (defer)** | Vendor/real-time | S&P/Nasdaq/Treasury futures, MOVE, VVIX, SKEW, term premium (Kim-Wright), Treasury auctions, FOMC countdown | **Real cost** — some paid/real-time; defer |

**Group-by-group status** (✓ have / C1 / C2 / C3):
- **1 Growth (9):** all **C1** (FRED).
- **2 Inflation (8):** CPI ✓; core CPI, PCE, core PCE, PPI, 3×breakevens → **C1**.
- **3 Fed Policy (7):** RRP ✓, Fed BS ✓, TGA ✓; Fed funds, IORB, reserves, M2 →
  **C1**; days-to-FOMC → **C3** (calendar).
- **4 Rates & Curve (10):** 10Y ✓, 2Y ✓, 10Y real ✓ (→2s10s derivable);
  3M/30Y/3M-10Y → **C1**; MOVE, term premium, 10Y futures → **C3**.
- **5 Liquidity & Credit (7):** HY OAS ✓; IG OAS, SOFR, C&I → **C1**; HYG/LQD/TLT
  → C1 (price proxies via existing price infra).
- **6 Risk Regime (10):** VIX ✓; DXY, gold, USD/JPY, BTC → **C1**; F&G → **C2**;
  VVIX, SKEW, S&P/Nasdaq futures → **C3**.
- **7 Flows & Positioning (4):** AAII bull/bear, NAAIM, COT → **C2**.
- **8 Geopolitics (2):** WTI, gold → **C1**.
- **9 Cyclical Sectors (6):** all **C1** (FRED housing/vehicles/delinquency).
- **10 Calendar & Catalysts (2):** FOMC countdown, Treasury auctions → **C3**.

**Net:** ~30 C1 (cheap, do first), ~4 C2 (scrape), ~10 C3 (defer). The board grows
one row at a time as series land.

---

## Data sources (queryable endpoints)

Verified/attempted 2026-07-16. Store all series into `macro_data`
(`date, symbol, value`) via `macro_engine` unless noted.

### C2 — scrape/API

**CNN Fear & Greed** — `https://production.dataviz.cnn.io/index/fearandgreed/graphdata/`
- Returns JSON: `fear_and_greed` (current `score`, `rating`, `timestamp`,
  `previous_close/1_week/1_month/1_year`), `fear_and_greed_historical.data`
  (full daily history `[{x: epoch_ms, y: score}]`), **plus 7 component sub-indices**
  (`market_momentum_sp500`, `stock_price_strength`, `stock_price_breadth`,
  `put_call_options`, `market_volatility_vix`, `junk_bond_demand`,
  `safe_haven_demand`) — each with its own history. So this one endpoint also
  supplies the S3 *Flows/Positioning* breadth internals for free.
- ⚠️ **Cloudflare bot-gate.** Plain `curl`/`urllib` → **HTTP 418 "I'm a teapot"**
  regardless of User-Agent (TLS-fingerprint block, not UA). Works from a real
  browser. Ingest options, cheapest first: (a) `curl_cffi` with
  `impersonate="chrome"` (mimics browser TLS — usually clears it); (b) a
  scheduled headless-browser fetch; (c) an unofficial mirror API. Confirm
  (a) works before committing S1's F&G tile. Only C2 gap for Section 1.

**AAII bull/bear** — no clean free API; weekly XLS at aaii.com (member-gated) or
free mirror via Nasdaq Data Link `AAII/AAII_SENTIMENT` (free key). Weekly.
**NAAIM Exposure** — `naaim.org/programs/naaim-exposure-index/` publishes a CSV
link; weekly. **CFTC COT** — official CSV/API at
`publicreporting.cftc.gov` (Socrata; free, no key). Weekly.

### C1 — FRED (already our source; extend `macro_engine` symbol list)

All are `fred.stlouisfed.org/series/<ID>` (free API key, JSON). Add the IDs:
- **Growth:** `GDPNOW` · `ICSA` (initial claims) · `CCSA` (continuing) ·
  `PAYEMS` (payrolls) · `UNRATE` · `U6RATE` · `INDPRO` · `RSAFS` (retail) ·
  `UMCSENT` (Michigan).
- **Inflation:** `CPILFESL` (core CPI) · `PCEPI` · `PCEPILFE` (core PCE) ·
  `PPIACO` · `T5YIE` · `T10YIE` · `T5YIFR` (5y5y).
- **Fed:** `FEDFUNDS` (or `DFF`) · `IORB` · `WRESBAL` (reserves) · `M2SL`.
- **Rates:** `DGS3MO` · `DGS30` · `T10Y2Y` (2s10s direct) · `T10Y3M` (Fed proxy).
  (2Y/10Y/10Y-real already ingested.)
- **Liquidity/Credit:** `BAMLC0A0CM` (IG OAS) · `SOFR` · `BUSLOANS` (C&I).
- **Risk:** `DTWEXBGS` (broad USD) · `DEXJPUS` (USD/JPY). Gold/BTC via price infra.
- **Geopolitics:** `DCOILWTICO` (WTI). Gold via price infra.
- **Cyclicals:** `HOUST` (starts) · `EXHOSLUSM495S` (existing sales) · `HSN1F`
  (new sales) · `SPCS20RSA` (Case-Shiller 20) · `TOTALSA` (vehicle SAAR) ·
  `DRCCLACBS` (CC delinquency).

Price-proxy tickers (`HYG/LQD/TLT/GLD/DXY` ETFs) route through existing
`price_data`, not FRED.

### C3 — live/premarket (defer; real cost)

Futures (ES/NQ/ZN premarket), MOVE, VVIX, SKEW, Kim-Wright term premium,
Treasury-auction calendar, FOMC countdown. No free clean feed for most;
MOVE/VVIX/SKEW are CBOE/ICE (paid or delayed). Deferred per the tier table.

---

## Build order (recommendation)

1. **Section 2 heatmap** — real, data-complete, ours. Ships on existing tables
   once the two design decisions (min-names threshold; native taxonomy=settled)
   are set. Highest value-to-effort.
2. **Section 1** — F&G ingest (one C2 scrape) + pillars + deploy headline. Pillars
   render immediately even before F&G lands.
3. **Section 3** — incremental. Land the ~30 **C1** FRED series first (they fill 6
   of 10 groups), then C2 scrapes, defer C3. Never block the page on completeness.

---

## Appendix: raw notes (original)

```
Section 1: sentiment — fear greed (CNN), NAAIM, HY OAS, VIX, MOVE, Trend,
  other factors, trend-ok/breakout supply; include pillars + regime bias.
Section 2: index (large/small cap), sector → subsector on click; per-card bar
  for #composite cos color-coded trend_ok/breakout_ok; up/down bar; per-card
  return distribution with today annotated + line; trend-ok/breakout added
  today + past 5d. Mapping e.g. Info Tech → Electronic Components, Semis, ...
Section 3: 10 groups, ~66 indicators — Growth 9, Inflation 8, Fed 7, Rates 10,
  Liquidity/Credit 7, Risk 10, Flows 4, Geopolitics 2, Cyclicals 6, Calendar 2.
```
