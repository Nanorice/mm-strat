# Dashboard Uplift — Meta Plan

> Sprint 14. Rebuild the dashboard toward the theta.md workflow/style.
> **Implementation started** (2026-07-16): Macro S2 shipped on a **shadow app**
> (`scripts/dashboard_uplift.py`) — the live `dashboard.py` is untouched until the
> full uplift switches over. This is the index + progress tracker; each page has
> its own design doc in this folder.

---

## Goal

Move from today's single monolithic Streamlit "Today" page to a **two-tier**
dashboard in the theta.md visual language, wired to the daily research workflow
(orchestrator → model → tradingagent reports → comprehension → reading list →
decisions → portfolio).

## Architecture — two tiers

| Tier | Pages | Audience | Style |
|---|---|---|---|
| **1 · Decision surface** (theta "Console") | Macro · Screening · Portfolio · ~~Track Record~~ (dropped) · Supply-chain | daily decision-making | **new** cream/serif (`style.md`) |
| **2 · Workshop** (ours only) | Model Lab · Backtest Studio · Pipeline Health | operator/researcher | dense/mono — **do NOT theta-style** |

Shared nav + header shell; divergent body density. theta exposes only Tier 1;
Tier 2 is the mechanic's view.

## The "Today" page dissolves

The old monolith splits — every orphaned section gets a home:

| Old "Today" cluster | Lands on |
|---|---|
| 6-Pillar Macro · Weather Gauge · Sector Heat | **Macro** |
| Daily Shortlist · Pre-Breakout · VIP (one population, sliced) | **Screening** (stage filter) |
| Screener Watchlist (held trades) · Watchlist Activity · Decision Log · Past-Decision Perf | **Portfolio** |
| Daily Rank Bump · Cohort-Return · Analytics (diagnostics) | **Model Lab** (new "Live Monitoring" tab) |
| decision headline + 6-decision widget | stays as slim **Today** landing |

---

## Progress tracker

Status: ⬜ not started · 🟡 planned (design doc done) · 🔵 mock built · 🟢 partial (some sections shipped) · ✅ shipped

### Tier 1 — Decision pages
| Page | Status | Doc | Data gap | Notes |
|---|---|---|---|---|
| **Macro** | ✅ | `macro_page.md` + `macro_page_mock.html` | **COT + C3 feeds** (61/61 live; C1 FRED + AAII/NAAIM ingested) | **S1+S2+S3 SHIPPED** (`scripts/pages/2_Macro.py` on shadow app). S1 = F&G dial (`curl_cffi` clears the CF 418 ✓) + 6 macro-pillar percentile tiles + deploy headline. S2 = `sector_breadth_engine.py` + Phase 7.46. S3 = indicator board, **9 of 10 groups** (group 7 filled by the C2 sentiment scrapes; only 10/calendar awaits C3). |
| **Screening** | ✅ | `screening_page.md` | **near-zero** (P/E derived) | **SHIPPED** (`scripts/pages/3_Screening.py` on shadow app; `v_d3_screening` view + MANIFEST + `load_screening`). Population = trend_ok∨breakout_ok (619); stage/fundamental filters in `st.form`; P(HR) rank + aggressive small-cap strip. No point-return column (honest cone). |
| **Portfolio** | ✅ | `portfolio_risk_section.md` | **closed** (`trades` + `cash_flows` + `nav_history`) | **SHIPPED incl. Risk section** (`scripts/pages/4_Portfolio.py` on shadow app). Append-only `trades` + `cash_flows` cash leg via `scripts/portfolio.py` CLI → derived positions/cash. **NAV = cash + positions; return TIME-WEIGHTED** (flows stripped per day → a deposit is not a gain) so YTD/drawdown are truthful. Score (raw) + cohort + %NLV + concentration + sector tilt. **Risk** = ATR/vol/S-R/52w/beta + 1-ATR-per-NAV, all from `price_data` so off-screen holdings are covered (entries are discretionary). Empty until fills are logged. ✅ `nav_history` **wired into the nightly** 2026-07-17 — **Phase 7.47** (`portfolio_nav`, WARN, between sector_breadth 7.46 and dashboard_db 7.5 so the row ships in the slim DB). |
| **Track Record** | ❌ **DROPPED** | — | n/a | **Retired 2026-07-17 (user).** Overlaps Portfolio: reports are *study material*, entries/exits are **discretionary**, so the only thing actually "projected" is the entry/exit decision — which IS the `trades` log on Portfolio. Scoring the *report* would measure a thing that never bound the decision. The tradingagent structured-block contract it was blocked on wouldn't fix the overlap. ⚠️ The old "Brier/**cone** scoring already exists" claim was **wrong** — the cone is the *start-date* cone (strategy evaluation across 90 start dates); it has no role in scoring a forecast ledger. Two different things called "scoring". |
| **Supply-chain** | 🟡 | `supply_chain_page.md` | **highest** (nodes yes, **zero edges**) | long-term; Tier-0 correlation mock → Tier-1 EDGAR 10-K extraction (new engine) vs Tier-2 buy |

### Tier 2 — Workshop pages (exist; grow, don't rebuild)

> **Spine (user, 2026-07-17): `data → model/label → strategy`.** Pages split by **STAGE**;
> the currency (C1 label / C2 OOS / C3 exit-P&L) is the claim-strength banner *within* a
> page, not the split itself. Dataset EDA = data · Model Lab = model/label · Backtest
> Studio = strategy. See `cone_and_studio_design.md`.
> ⚠️ **All three are LIVE `dashboard.py` pages** — unlike Macro/Screening/Portfolio, a
> revision here touches the working version. Uplift versions land as **new files** in the
> shadow nav; the live ones stay untouched until switch-over.

| Page | Status | Doc | Change |
|---|---|---|---|
| **Dataset EDA** | ✅ exists | `cone_and_studio_design.md` | **= the `data` stage.** Pretrain-audit report browser (120 lines). **No change planned** — it's input inspection, upstream of any currency claim. (The sprint EDA belongs on Model Lab, not here.) |
| **Model Lab** | 🟡 **revision planned** | `cone_and_studio_design.md` | **= the `model/label` stage.** Absorb diagnostics as "Live Monitoring" tab + **the sprint-summary EDA** (funnel / label outcome / **LABEL cone** — the §5 buy-and-hold fan, NOT the backtest cone). Today it's a card browser with no population view. **Card ✅ adheres to methodology** (C1 banner shipped; Section-G hang outstanding) |
| **Backtest Studio** | 🟡 **revision planned** | `backtest_studio_page.md` + `cone_and_studio_design.md` | **= the `strategy` stage. ⚠️ contradicts new methodology** — headlines the single Sharpe G6 retired, no cone, no C3 label, no engine tag. Revise: C3 banner → engine column → promote **strategy cone** (full distribution) → demote single-Sharpe. **+ cell-level zoom** (trades/rejections/exposure — the per-cell artifacts already carry all of it) |
| **Pipeline Health** | ✅ exists | — | **DQ section shipped 2026-07-17** (`render_data_quality` — per-audit breakdown + failing checks + `new_fails` regressions) + the **audit-history zero-chart bug fixed**. Serving-layer audit now covers Phases 7.4/7.45/7.46/7.47. Still open: surface `deactivate_tickers.py` (memory TODO); a `comprehend_reports` row if that phase lands |

### Cross-cutting infra
| Item | Status | Doc | Notes |
|---|---|---|---|
| **Style system** | 🟡 | `style.md` | tokens/type/components settled |
| **Research layer contract** | 🟡 | `research_layer_contract.md` | `research_reports` table = tradingagent boundary; `comprehend_reports` phase + `research_signals` deferred |
| **Platform decision** | ⬜ open | — | Streamlit vs static-HTML-over-slim-DB. Decide *per page* by interaction density; validate with the mocks. Migrate page-by-page, no big-bang. Dense pages (Macro, Supply-chain) are the pressure cases. |
| **Slim-DB `MANIFEST`** | — | — | **every** new table/view a loader reads MUST be added (remote-parity, `project_dashboard_remote_parity`) |

---

## Recommended build order

1. **Screening** — most data-complete; retires 3 redundant Today tables immediately.
2. **Macro** — S2 heatmap (data-complete) → S1 (F&G ingest) → S3 incremental (C1 FRED first).
3. **Portfolio** — needs `positions`/`nav_history` tables first; unlocks the held-trades migration.
4. ~~**Track Record**~~ — **DROPPED 2026-07-17** (overlaps Portfolio; see the tracker row).
5. **Supply-chain** — long-term; Tier-0 mock now, edges as a separate research thread.

Workshop-tier changes (Model Lab monitoring tab, Pipeline Health phase rows) slot
in alongside whichever data thread lands them.

---

## Build log

- **2026-07-17 (session 06) — NAV nightly (Phase 7.47) · Track Record dropped · DQ section
  + serving audit.** Three user decisions.
  - **Phase 7.47 `portfolio_nav`** (WARN, order 7.47) — `snapshot_nav()` between
    sector_breadth (7.46) and dashboard_db (7.5) so the row ships in the slim DB.
    Modelled exactly on 7.46. `target_date` is a **str** in the orchestrator but
    `snapshot_nav` takes a `date` → explicit `strptime`, no silent pass-through.
    **Why it earns a slot despite writing 1 row/day**: a NAV series **cannot be honestly
    backfilled** — TWR needs the day's `net_flow` recorded *on the day*, so a missed run
    is a permanent hole. Driven for real on a temp DB: NAV 105,000 = cash 85k + positions
    20k, net_flow 100k captured, idempotent on re-run (1 row after 2 runs).
  - **Track Record DROPPED** (user). Overlaps Portfolio — reports are study material,
    decisions are discretionary, so what gets "projected" is the entry/exit = `trades`.
    ⚠️ Also killed a **false claim in this very doc**: "Brier/**cone** scoring already
    exists" conflated the **start-date cone** (strategy evaluation) with forecast
    scoring. Two unrelated things called "scoring"; the cone has no role on that page.
  - 🐛 **The Pipeline Health "Audit History" chart has NEVER shown real data** — it read
    `summary.pass_count`/`passed` etc.; the real keys are `summary.total.{OK,WARNING,
    FAIL,INFO}`. Three fallback spellings + `.get(...,0)` on each → a total miss rendered
    **three flat zero lines** instead of an error, hiding **6 real FAILs** across 23
    reports. In committed HEAD, not from the uplift. **A green-looking panel is not
    evidence the panel works.**
  - **DQ section shipped** (`render_data_quality`): per-audit FAIL/WARN/OK breakdown,
    today's failing checks by name+detail, and **`new_fails`** (regressions vs the
    previous run). All three were **already written nightly by `run_all_audits.py` and
    simply never read** — no new table, no new phase. Answering the user's "how do we
    maintain the DQ data?": Phase 8 already writes `data/audit_reports/*.json` (23 on
    disk, R2-synced).
  - **`tools/audit_serving_tables.py` (NEW)** — the derived tables had **no audit at all**
    (the T1 script audits T1; `sector_breadth`/`weather_gauge`/`daily_predictions`/
    `nav_history` sat below that line, so a dead Phase 7.4/7.45/7.46 greys a panel and
    says nothing). Registered in `run_all_audits.py` → **Serving Tables: 0 FAIL 0 WARN
    6 OK** in the real nightly run.
    - 📏 **Tolerances MEASURED not guessed** (the macro_data lesson): observed 2y
      worst-case gap = weather_gauge **6d**, daily_predictions **13d** (a one-off
      07-02→07-15), sector_breadth is a **1-date snapshot**. Shipped 10/20/5 = observed
      + headroom → 0 false warnings on the live DB.
    - Sanity checks beyond freshness: `sector_breadth` must hold **exactly 1 as_of_date**
      (refresh replaces; >1 = the append bug), `weather_gauge` non-NULL posture (it drives
      SPY>200d, the only surviving lever), `nav_history` **nav == cash + positions**
      (cash is derived, so drift = broken invariant).
    - 🐛 Caught by **driving the CLI, not by pytest**: `sector_breadth.as_of_date` is a
      **TIMESTAMP** while the rest are DATE → `TypeError: date - datetime`. Fixed with a
      `CAST(... AS DATE)` in the query. 3rd time this thread that running the real command
      caught what tests didn't.
    - 🧪 **All 4 checks mutation-verified**: on a deliberately broken DB all 4 fire; on the
      healthy DB none do. The tolerance test varies staleness across the 20d boundary —
      mutating the tolerance 20→60 **fails it** (an all-OK audit proves nothing until you
      prove it can fail).
  - ✅ Verified: page driven via `AppTest` → **0 exceptions**, "Data Quality" renders the
    **real 6 FAIL / 25 WARN / 224 OK / 35 INFO**; audit history now 23 rows of real data
    (0 all-zero rows, was 23). Suite **381 passed** + 7 new serving tests (baseline's 7
    failures / 26 errors unchanged). Real book untouched: **0 rows** (all drives on temp
    DBs, deleted).
- **2026-07-17 — Portfolio Risk section shipped** (`_render_risk` +
  `dashboard_utils.load_portfolio_risk`). Doc: `portfolio_risk_section.md`.
  - **Two user decisions reshaped it.** (1) Entries/exits are **DISCRETIONARY** — the
    champion is only there to set expectation (*"it is a lottery"*) → **no
    divergence-from-champion panel**, and holdings routinely sit **outside the SEPA
    screen**, so every metric resolves from `price_data` (all tickers) rather than
    t2/t3 (~2,724 of 3,980 active). (2) The section is to **measure/monitor**, not act.
  - **Shipped**: ATR(14)/ATR%, realized vol 20d/60d, 20d-50d support/resistance,
    **distances in ATR UNITS** (dollars aren't comparable across names), **1-ATR move
    as % of NAV** (`qty×ATR/NAV`), true 52w high/low, mv-weighted book beta,
    top-3/sector share.
  - 💡 **`1-ATR / NAV` is the payoff metric** — it converts per-name noise into book
    impact. Live: **PSNL (7.9% ATR) contributes MORE book risk than a much larger
    NVDA position**. Invisible on a positions table.
  - 🛑 **NO VaR / expected shortfall — and NOT for infra reasons** (it's ~10 lines off
    `price_data`). It would **mislead**: it needs a covariance matrix to mean anything
    at book level, and with ~4 concentrated same-sector names the correlation term
    dominates; a window-fitted VaR prints calm right up to the regime that breaks it.
    Don't re-propose.
  - ⚠️ **A true 52w level CANNOT be recomputed on the remote** — the slim DB windows
    `price_data` to ~172 bars (~8mo). t3's `high_52w` is a **stored** value so it
    survives the window: **READ it, never recompute**; "—" off-screen. Conversely ATR
    is **computed in the loader, NOT read from t3's `atr_20d`**, so the window is
    identical for every holding. ATR bounds the known OHLC dirt with GREATEST/LEAST.
  - 🧪 **The ATR test was mutation-checked and the first version was WORTHLESS**: a
    constant true range makes EVERY window average the same, so it passed with the
    window mutated 14 → 5. Fixed by varying TR per bar (ATR(14)=7.5 vs 5-bar=3.0);
    the mutation now fails it. **A metric test must vary the input along the axis it
    claims to pin.** 2nd time this class hit this thread (cf the session-04 bot-block
    test). ATR SQL also cross-checked against an independent pandas computation
    (NVDA 7.1407 / KO 1.7146, exact).
  - 🐛 **Bug fixes from the prior session's list**: (a) the CLI docstring still claimed
    *"NAV carries NO cash leg"* — stale and false after the cash leg landed; (b) the
    `nav_history` shape fix confirmed. ⚠️ **The first verification of (a) was a FALSE
    PASS**: `grep -P` isn't supported in this locale, so it printed "none" without
    running. Re-checked properly, then proved the real failure mode by running the CLI
    under an actual **cp1252** console (prints clean).
  - ✅ Verified: 31 portfolio tests (3 mutations checked), suite **381 passed** (7
    pre-existing failures unchanged); page driven end-to-end with real market data
    (PSNL/NVDA/KO incl. an off-screen holding). Real book untouched: 0 rows.
- **2026-07-16 — Portfolio page shipped; cash leg added after a mock review.**
  Built from a competitor screenshot the user shared. **The screenshot is a marketing
  page** — it self-labels "CONCEPT PREVIEW — SAMPLE DATA" / "money sample" behind a
  £15/30d paywall. Analysed panel-by-panel against our DB rather than copied (same
  discipline as `macro_page_mock.html`, whose "10/10 indicators" were invented):
  roughly ⅓ real for us, ⅓ needed a cash leg, ⅓ needs data that doesn't exist.
  - **Built**: append-only `trades` fill log + `cash_flows` + derived positions/cash;
    `scripts/portfolio.py` CLI (buy/sell/deposit/withdraw/positions/trades/nav);
    Score (raw) + cohort + %NLV + Top-3 concentration + sector tilt + TWR curve.
  - ✅ **Cash leg (user reversed the earlier positions-only call).** NAV = cash +
    positions; **return is TIME-WEIGHTED** — `nav_history.net_flow` stores the day's
    external flow so `returns()` strips it. Verified live: **a 500k deposit → ret
    +0.0000%**, while the naive `pct_change` it replaces booked **+500%**; a real
    mark-up on the next day still measured +1.82%. Both directions test-pinned and
    mutation-verified.
  - ⚠️ **The model scores only ~751 of ~3,980 active tickers** (SEPA lifecycle
    universe) → a held name outside it renders **"—", never a stale score or a zero**
    (a zero reads as "model hates it"). Score is **RAW** (a rank, not a probability),
    same rule as Screening.
  - **Rejected from the mock, deliberately**: cash/margin/theta/options (no data),
    supply-chain concentration (**zero edges**), and the "Style review 5.8/10
    Balanced" composite (**an invented number**).
  - **Risk section = PLAN ONLY** (`portfolio_risk_section.md`), per the user —
    *(superseded: **shipped 2026-07-17**, see the entry above)*. The plan's core
    finding, which still binds it: **our research already falsified the obvious
    levers** — DD circuit breaker (sweep 6–30% = mechanism not threshold), earnings
    blackout, VIX de-risking all LOSE on the cone; only **SPY>200d** survived
    BackTrader. So the section **describes, never acts**.
  - 🐛 **pytest green ≠ the command works**: unit tests never touch stdout, so they
    missed a CLI that **crashed on every successful trade** (✅ glyph vs Windows
    cp1252 under a bare `python.exe`). The writes succeeded; only the print raised.
    Driving the real CLI caught it → ASCII `[OK]`/`[ERR]`.
  - 🐛 **`CREATE TABLE IF NOT EXISTS` silently skips an existing OLD-shape table** —
    the cash columns were a no-op until the (verified empty) `nav_history` was dropped.
  - ✅ Verified: 29 portfolio tests (2 mutations checked), suite **379 passed** (7
    pre-existing failures unchanged); slim rebuilt + parity checked **directly**;
    page driven end-to-end with **real scored tickers** (PSNL 0.855 / NVCT 0.818) and
    a real unscored holding (KO → "—"). Real book untouched: 0 rows.
- **2026-07-16 — AAII ingest LANDED; group 7 complete (4/4 rows live).** The Imperva
  block aged out; fetch clean on the dev box. `macro_data` **214,699 rows / 69 symbols**;
  slim rebuilt, parity verified **against `dashboard.duckdb` directly** (69/69, no loader).
  DQ audit macro_data section: **71 OK / 0 FAIL** (was 68 OK / 3 FAIL — the 3 AAII rows).
  Board renders all 4 flows rows, all |z|<1.5 (quiet, correct).
  - 🐛 **`update_series()` does NOT write the DB — it only writes the pickle cache.**
    The DB write lives in `update_macro_cache`, which calls `write_to_macro_data`
    separately. The previous handover's "re-run `MacroEngine().update_series('AAII_BULL')`
    to ingest" is **wrong**: it returns a populated 1,228-row frame and prints success
    while inserting **zero rows**. Correct one-off ingest:
    `df = e.update_series(sym); e.write_to_macro_data(sym, df)`.
  - Verified the col-0 trap did NOT bite: the 3 symbols hold **distinct** means
    (bull 37.51 / bear 33.57 / spread 3.95), spread ≡ bull−bear on **all 1,228 dates**
    (max err 0.0), zero bull+bear>100 violations.
  - Note: `macro_data.value` is **NULL for all 69 symbols** — the populated column is
    `close`. Pre-existing and audit-guarded; don't "fix" it by reading `value`.
- **2026-07-16 — S3 group 7 (Flows & Positioning): AAII + NAAIM ingest.** The last
  group with no source; board now **9 of 10 groups**. Scope confirmed with the user:
  AAII+NAAIM only, **COT deferred** (87-col file, one zip PER YEAR ≈ 20 fetches to
  backfill, plus a market-selection + net-position derivation — triples the work for a
  third sentiment read).
  - `config.SENTIMENT_SERIES` (NEW dict, 4 symbols) + `macro_engine.fetch_aaii_sentiment`
    / `fetch_naaim_exposure` + dispatch + an **isolated** nightly loop (per-symbol try,
    like the Yahoo loop — these parse third-party spreadsheets whose layout can change).
    Ingest free as predicted: `macro_data` is MANIFEST-`full` → **zero orchestrator/
    MANIFEST edits**.
  - **NAAIM: 1,045 weekly rows, 2006→2026-07-15, live in main + slim.** ✓
  - ⚠️ **AAII: fetcher verified against live data (1,228 rows, 2003+, bull+bear ≤100,
    spread ≡ bull−bear) but NOT yet ingested** — the IP tripped **Imperva bot defense**
    mid-session. Configured-but-empty → the 3 rows grey out; the nightly picks them up
    when the block ages out. No retry loop added (hammering hardens the block).
  - 🐛 **The exact trap this thread keeps hitting: AAII's block returns HTTP 200 with
    6KB of HTML** ("Pardon Our Interruption"). Status *and* a plausible length both look
    fine; `read_excel` then raises a **misleading** "format cannot be determined" that
    hides the cause. Guard = **magic bytes** (`D0CF11E0` .xls / `PK` .xlsx) *before*
    parsing, applied to NAAIM too (same exposure — its 404 serves 175KB of HTML).
    Reinforces **smoke-test the payload, not the status code**.
  - **NAAIM's export URL is date-stamped** (`USE_Data-since-Inception_2026-07-15.xlsx`)
    and rolls weekly → scraped off the page, never hardcoded (a pinned URL 404s within
    a week *into HTML that looks alive*).
  - **AAII sheet parsed by date-detection, not `header=3`** — a pinned header row
    silently shifts if AAII adds a banner. 3 junk rows above, commentary below.
  - `write_to_macro_data` takes **one symbol per call** (`value_col = df.columns[0]`),
    so the 3-column AAII frame is sliced per symbol at dispatch — passing it whole would
    have silently written `AAII_BULL`'s values under all three names.
  - Unit: `percent` → **absolute-change z** (AAII_SPREAD crosses zero; a pct z would
    explode like T10Y2Y's 22.6% σ). Not `revised` — a survey print is a point-in-time
    count, so INSERT-OR-IGNORE costs nothing. Display-only like the rest of S3.
  - ✅ Verified: parity checked by opening `dashboard.duckdb` **directly** (66/66
    symbols, no loader) after rebuilding **post-ingest**; NAAIM z=0.98 (quiet, correctly
    under the 1.5σ amber); `/` + `/Macro` 200 clean. **335 passed** (was 332; +3 new).
  - 🧪 The bot-block test was **mutation-checked**: the first version passed even with
    the guard deleted (read_excel raises → broad `except` → empty either way), so
    `.empty` proved nothing. Now asserts `read_excel` is **never called**; verified it
    fails with the guard removed and passes with it.
- **2026-07-16 — Data-quality audit: macro_data freshness 12 → 66 symbols.**
  Prompted by "update the DQ check with the new feeds"; the real finding was bigger than
  the two new feeds. `tools/audit_t1_data_quality.py` held a hardcoded
  `MACRO_DATA_EXPECTED` of **12 symbols while macro_data had grown to 66** — every one of
  the **54 series added by the S3 board over sessions 01–03 had NO freshness check**. A
  dead FRED/Yahoo feed would have gone unnoticed indefinitely (the board greys the row
  out and says nothing).
  - Fix = the same one the board already uses: **derive tolerance from each series'
    `freq`** (`MACRO_FRESHNESS_BY_FREQ`), so a newly-configured series is audited the
    moment it's added. `MACRO_DATA_EXPECTED` shrinks to genuine exceptions (VIX/CAPE/
    CAPE_OURS/FEAR_GREED + the dead `EXHOSLUSM495S`). New check: **unconfigured_symbols**
    (ingesting but in no config dict → never renders, nothing owns its freshness).
  - 📏 **Tolerances MEASURED, not guessed.** First cut (D5/W12/M70/Q190) fired **11
    false warnings** on healthy feeds. Cause: the inter-OBSERVATION gap is small (M=31d)
    but these series are **dated at PERIOD START and published weeks later**, so
    staleness must cover period + publication lag. Measured worst-case on a healthy feed
    over 2y: **D=6** (DEXJPUS/DTWEXBGS skip US holidays), **W=12** (CCSA), **M=106**
    (SPCS20RSA — Case-Shiller is a 2mo-lagged 3mo average), **Q=196** (DRCCLACBS).
    Shipped D10/W18/M125/Q230 = observed worst + headroom → **68 OK, 0 false warnings**.
    Same wallpaper lesson as the S3 banner: an alert that fires on a healthy day is noise.
    Test-guarded against re-tightening.
  - ✅ Result: macro_data section 12 → **72 checks**; the only FAILs are the **3 AAII
    rows** — i.e. the audit immediately caught the one thing genuinely broken. Other
    sections' 3 FAIL / 7 WARNING are pre-existing (price_data/t1_macro), untouched.
    Suite **337 passed** (+5 new).
- **2026-07-16 — Macro S3 round 3**: commodities + anomaly banner + typography.
  - **Commodities via YAHOO (`config.YAHOO_SERIES`, 16 syms)** — Geopolitics 1 → 16
    rows. Yahoo beat FRED on **every** one (smoke-tested first): all daily + deep to
    2003, including **cocoa**, which FRED has no clean series for and which has no US
    ETF. Yahoo's `CL=F` is fresher than FRED's `DCOILWTICO` (T+0 vs T+2) so it owns
    the WTI row; the FRED one stays as an ungrouped cross-check. New
    `macro_engine.fetch_yahoo_series` + dispatch (per-symbol try → one dead ticker
    can't fail the nightly macro phase). Uranium = URA ETF (2010+), no futures exist.
    `macro_data` 119,593 → **209,970 rows / 65 symbols**; slim rebuilt, parity
    verified **against the slim file directly** (57/57 board series present).
  - **Anomaly banner + Z column** — |z| of the latest CHANGE vs each series' own
    full-history change distribution.
  - 🛑 **The proposed 0.5σ/1.0σ thresholds were REJECTED on measurement.** Over the
    last 120 days: **0.5σ fires on a median 14 of 56 rows EVERY day, 1.0σ on 6**. A
    banner lit daily is wallpaper. This is arithmetic, not tuning — |z|≥1 covers ~32%
    of a normal distribution, so ~18 of 56 rows fire on an ordinary day. Shipped
    **1.5σ amber / 2.5σ red**: median day = 2 amber / 0 red, a real event still
    spikes to 14/5. Guarded by a test so it can't be quietly lowered.
  - 🐛 **Two statistical flaws found and fixed before shipping:**
    1. **Absolute change isn't stationary for a trending price.** Gold's full-history
       σ is $22.69, but it traded ~$350 in 2003 and ~$4,000 now — a routine 1% day
       scored ~1.8σ. Pct-change is scale-free and measurably stationary (gold σ
       1.146% full vs 1.154% since 2021). First cut fired **21 red / 31 amber of 56**.
    2. **But pct-change EXPLODES for a series crossing zero** — T10Y2Y scored a
       **22.6% σ**. So the unit is chosen per series: pct for prices/levels,
       absolute for spreads/rates (`config.S3_PCT_UNITS`, keyed off the existing
       `unit` field — no new flag). Post-fix: **1 red / 6 amber**.
    3. `latest_v` comes from the same SQL that builds mu/sd, so the change can never
       be measured in a different unit than the moments it's compared against.
  - ⚠️ Full-history moments = all-time = **look-ahead**. Board is display-only; the z
    must never reach a model. Stated in the loader docstring + the page footer.
  - **Typography** (user: "too pale... range col too small"): body/value text →
    `#1c1a17`, secondary → `#6f6858` (was `#c3bba6`, which was near-invisible); Range
    10px → 12px, matching Prior. Indicator name now left-aligned with the symbol +
    `rev` chip on a **second line** beneath it.
  - **History mark: bars → LINE + area** (user: prefers a spline for the level). The
    original failure was never the mark type but the resolution — 180 points in 64px
    = 0.4px/point. Now 90px wide, capped at ~1pt/1.5px. **Per-row histograms of daily
    %Δ were NOT built**: a histogram needs ~50+ points for a shape, but 22 of the 42
    FRED series are monthly/quarterly (6 points in a 180d window) — half the board
    would render noise. The z column answers the same "is today unusual?" question in
    one number. Suite **332 passed**.
- **2026-07-16 — Macro S3 board redesign** (user review: "too squeezed, the line chart
  is not very informative"). Compared against `macro_page_mock.html`:
  - **Layout**: `.ggrid` was `auto-fit minmax(380px)` → packed 2–3 groups per row; now
    **one group per row, full width** (`flex column`). Row padding 4px → **14px**.
    Group headers get a filled bar + `live/total indicators` count, like the mock.
  - **History: polyline → BARS** (`_sparkbars`, 24 buckets, downsampled by mean). At
    64×22px a 180-point line gives each point ~0.4px — sub-pixel noise, which is why
    it read as uninformative. Bars are quantized to what the eye can resolve; last
    bar = today at full opacity, the rest recede.
  - **Context columns added**: `Prior` + `Range` (window min–max) + `Np` point count,
    matching the mock's Prior/Now/Δ/History/Range shape. `_fmt` scales precision to
    magnitude (the board spans SOFR 4.3 → payrolls 158,984).
  - ⚠️ **The screenshot under review was the MOCK, not the built board** — its Risk
    Regime shows "10/10 indicators" but **8 of those 10 rows are `null` in the mock's
    own data** (VVIX/SKEW/DXY/Gold/USD-JPY/BTC/futures are C3 = paid/real-time,
    deferred). The real board shows the 2 that exist. Density in the mock is partly
    fabricated; **not** reproduced.
  - 🐛 **Correction to the entry below**: the earlier "remote parity holds ✓" check was
    **WRONG** — it read the MAIN db through the loader (`_connect()` fell back), so it
    reported 49 symbols/119,593 rows that were main's, not the slim DB's. The slim DB
    at that moment had only **12 symbols, no PAYEMS**. The tell was an identical row
    count between a full DB and a windowed slim one. Re-verified by opening
    `dashboard.duckdb` **directly**: now genuinely 49 symbols/119,593 rows, all 42 S3
    series present, loader confirmed reading `dashboard`. **Lesson: verify parity
    against the slim file itself, never through a loader that can silently fall back.**
  - `tests/test_macro_s3_board.py`: +downsampling test (180 pts → 24 bars), +`_fmt`
    magnitude test. Suite **326 passed**.
- **2026-07-16 — Macro S3 (indicator board) shipped** — the C1 FRED backlog landed.
  - `config.py` — `FRED_SERIES` extended 9 → **45** entries (36 new C1 IDs, all
    smoke-tested against the live FRED API before commit: **36/36 fetch clean**).
    Each S3 entry carries a `group` tag (drives the board) + `revised` flag.
    **Ingest was free exactly as predicted**: `update_macro_cache` iterates the
    dict and `macro_data` is MANIFEST-`full` → **zero** orchestrator/MANIFEST edits;
    nightly + remote parity followed with no wiring.
  - `macro_data`: 13 → **49 symbols / 119,593 rows**. Slim-DB rebuild verified all
    42 grouped series reach `dashboard.duckdb` (remote parity holds).
  - `scripts/dashboard_utils.py` — `load_macro_indicators()`: one SQL pass →
    latest/prior/Δ%/sparkline/n_obs per series, driven off the config metadata (no
    hardcoded ID list in the page). Δ is vs previous **observation** (w/w weekly,
    m/m monthly), not a fixed calendar lag.
  - `scripts/pages/2_Macro.py` — `_render_s3` + `_sparkline` (inline SVG) +
    `S3_GROUPS`; 8 of 10 groups render (42 rows). Groups 7 (flows) + 10 (calendar)
    have no C1 source → land with C2/C3. Configured-but-empty greys out; page never
    gates on completeness.
  - `tests/test_macro_s3_board.py` (NEW) — sparkline degenerate inputs (flat series
    div-by-zero, <2 points), config↔board group parity (a series can't ingest but
    silently never render), revised-flag coverage.
  - ⚠️ **Revision caveat (accepted, documented)**: 22 series are FRED-revised but
    `write_to_macro_data` is `INSERT OR IGNORE` → **first print wins, revisions
    dropped**. Fine for a display board; these are **display-only** and must not
    feed a model wanting point-in-time accuracy. Upgrade path = `INSERT OR REPLACE`
    (cf `cape_engine`) if a consumer ever needs it.
  - **Two series are shallower than the plan assumed** (caught by the smoke test):
    `BAMLC0A0CM` (IG OAS) returns only **785 rows from 2023-07** — not the deep
    2003+ series its HY sibling `BAMLH0A0HYM2` is (6,148 rows); it would fail M03's
    10yr-z bar like the sprint-13 `MOVE` rejection. `EXHOSLUSM495S` (existing home
    sales) is re-based/discontinued → **13 rows**. Both render as stubby
    sparklines; display-only, fine for the board.
  - 🐛 **Pre-existing bug fixed** (`dashboard_utils._ensure_local_db`): `Path.rename`
    raises `FileExistsError` on Windows when the target exists (POSIX rename
    overwrites) → **`os.replace`**. Was blocking pytest collection of
    `test_cohort_return_panel.py`. Present in committed `HEAD` (93497c9), not from
    this session. Suite: **315 passed** (7 known-broken modules still excluded).
  - ⚠️ **Deeper flaw left OPEN (needs the user's call)**: `_on_cloud()` infers "am I
    the cloud app?" from **R2 creds**, but the dev box's `.env` and the ops box both
    carry them → any dotenv-loading `import dashboard_utils` starts a ~751 MB R2
    download. A correct fix needs a positive cloud marker verifiable **on** Streamlit
    Cloud; guessing it here would silently stop the remote pull (stale DB — worse
    than the bug). Documented in the docstring, not patched blind.
- **2026-07-16 — Macro S1 (regime headline) shipped** + **Fear&Greed ingest landed**.
  - `src/macro_engine.py` — `fetch_fear_greed()`: CNN dataviz endpoint via
    `curl_cffi` `impersonate="chrome"` (clears the Cloudflare TLS 418; plain
    urllib reproduces the 418). Dispatched in `update_series` + added to the
    `update_macro_cache` non-FRED loop → **nightly Phase 1.4 picks it up with no
    orchestrator change**; `macro_data` is already MANIFEST-`full` → remote parity free.
    ⚠️ ~1yr history only (253 rows) — CNN serves no deep archive; display gauge, not a
    backtest input.
  - `scripts/pages/2_Macro.py` — `_render_s1`: F&G dial (SVG arc, CNN banding) +
    6 macro-pillar percentile tiles w/ LONG/SHORT/NEUTRAL bias chips + deploy
    headline (posture · SPY>200d · supply regime · stress_z · M03 score).
  - `scripts/dashboard_utils.py` — `load_fear_greed()` + `fear_greed_label()`.
  - **Doc correction**: the plan credited `t2_regime_scores` for the "6 pillars" —
    wrong table. Pillars = `load_macro_pillars` (VIX/Credit/Term/Rates/Liquidity/
    CAPE); `t2_regime_scores` = M03's *three* pillars, now feeding the deploy
    headline. Fixed in `macro_page.md`.
  - Verified: F&G scrape 200 (score 46.9 neutral, 253 pts); gauge geometry across
    0/25/50/75/100; all 6 tiles resolve w/ percentiles; slim DB ships F&G (253
    rows); shadow app `/Macro` + `/Screening` boot 200 no errors.
- **2026-07-16 — Screening page shipped** on the shadow app.
  - `src/managers/view_manager.py` — `_create_v_d3_screening`: latest-day
    `trend_ok∨breakout_ok` universe ⋈ prod `daily_predictions` (P(HR), COALESCE
    class_3→class_1) ⋈ `fundamental_features` (margins/growth, deduped as-of
    filing) ⋈ `company_profiles`; derived P/E (`close/eps_diluted`, NULL when
    unprofitable). Display view, lowercase (not model-fed).
  - `scripts/pages/3_Screening.py` — theta-styled header strip + `st.form`
    stage/fundamental/sector/cap filters + `st.column_config` P(HR)-ranked table
    + aggressive small-cap strip. No point-return column (honest cone).
  - Wiring: `v_d3_screening` → `build_dashboard_db` MANIFEST (`materialize_view`);
    loader `load_screening()`; mounted in `dashboard_uplift.py` nav.
  - Verified: view 619 rows / 558 scored / 408 P/E; slim-DB build + MANIFEST
    invariant ✓; shadow app + `/Screening` route boot 200 no errors.
- **2026-07-16 — Macro S2 (sector/subsector heatmap) shipped** on the shadow app.
  - `src/sector_breadth_engine.py` — nightly `sector_breadth` snapshot (return
    histogram + breadth + participation + added today/5d, per sector & subsector).
  - `scripts/pages/2_Macro.py` — theta-styled S2 render (histogram KDE, expand-on-click).
  - `scripts/dashboard_uplift.py` — shadow `st.navigation` entrypoint (live nav untouched).
  - Wiring: Phase 7.46 (`phase_registry` + `config` + orchestrator) + `build_dashboard_db`
    MANIFEST entry. Loader `load_sector_breadth()` in `dashboard_utils.py`.
  - Session handover: `../../logs/2026-07-16.md`.
  - **Switch-over reminder**: fold shadow pages into `dashboard.py`'s `st.navigation`
    and delete `dashboard_uplift.py` once the full uplift is ready.

## Open questions (user)

1. **tradingagent output** — what does it emit, can it write DuckDB or drop a file? (sizes the ingest side of the research layer)
2. **Supply-chain edges** — build (Tier-1 EDGAR extraction, multi-week) vs buy (Tier-2 vendor feed, paid)?
3. **Platform** — settle after the mocks give evidence.

## Files in this folder
- `README.md` — this meta plan.
- `style.md` — visual system.
- `macro_page.md` / `macro_page_mock.html` — Macro design + standalone mock.
- `screening_page.md` — Screening design.
- `portfolio_risk_section.md` — Portfolio Risk section: shipped metrics, why no VaR, and the falsified-lever list that binds it.
- `backtest_studio_page.md` — Backtest Studio revision (methodology adherence: cone + C3 currency).
- `cone_and_studio_design.md` — **the TWO cones** (label §5 fan vs strategy `cone_gate`), the
  `data → model/label → strategy` page spine, cell-level zoom, and the cache design
  (Track A = bounded dashboard summary; Track B = re-runnability, infra-only).
- `supply_chain_page.md` — Supply-chain design + edge-sourcing tiers.
- `research_layer_contract.md` — tradingagent → repo boundary.
