# Session Handover: 2026-07-16 → 07-17 (session 05)

> Fifth session on the dashboard-uplift thread (01 = Macro S2, 02 = Screening + Macro S1,
> 03 = Macro S3, 04 = C2 sentiment + DQ audit). This one: **AAII landed**, then
> **Portfolio page built from scratch** (fill log + cash leg + score columns + Risk
> section). Ran past midnight — dated 07-16 for thread continuity; the Risk section is
> 07-17 work. Live `dashboard.py` still untouched. **NOT COMMITTED.**

## 🎯 Goal
Finish the half-done AAII ingest, then build **Portfolio** — the next page in the README
build order — including a **risk-management section** the user asked for mid-session.

## ✅ Accomplished

### AAII ingest LANDED — S3 group 7 complete (board 9/10 groups)
- Imperva block had **aged out**; fetch clean on the first try (no retry loop needed).
  **3,684 rows** (1,228 × 3 symbols, 2003-01-02 → 2026-07-16) in main + slim.
- 🐛 **The previous handover's own next-step instruction was WRONG and failed silently.**
  It said to run `MacroEngine().update_series('AAII_BULL')` to ingest — but
  `update_series()` **only writes the pickle cache**; the DB write is a separate
  `write_to_macro_data()` call that only `update_macro_cache` makes. My first attempt
  returned a populated 1,228-row frame, printed "done" 3×, and inserted **zero rows**.
  Only a follow-up `COUNT(*)` caught it. Corrected in the README + memory.
- Verified the col-0 trap did NOT bite: 3 **distinct** means (bull 37.51 / bear 33.57 /
  spread 3.95), spread ≡ bull−bear on **all 1,228 dates** (max err 0.0), 0 bull+bear>100.
- DQ audit macro_data section: **68 OK/3 FAIL → 71 OK/0 FAIL**.
- **Answered the user's standing question**: all 69 macro symbols ARE maintained
  automatically — orchestrator Phase 1 calls `update_macro_cache(write_db=True)`, which
  iterates all 3 config dicts nightly. Self-healing but **not self-announcing** (nothing
  pages you; only the audit shows a dead feed).

### Portfolio page SHIPPED (new: CLI + 3 tables + page + Risk section)
- `trades` = **append-only fill log** (user's call over one-row-per-position → scale-ins
  / partial exits need no migration). Positions **DERIVED**, `avg_cost` weighted over
  **BUY fills only**.
- **Cash leg added mid-session (user REVERSED the earlier positions-only call).**
  `cash_flows` + cash **derived** from flows+fills (never a stored balance → can't drift
  from the log). NAV = cash + positions; **return is TIME-WEIGHTED** — `net_flow` per day
  is stripped in `returns()`. **Verified live: a 500k deposit → ret +0.0000%**, where the
  naive `pct_change` it replaces booked **+500%**; a real next-day mark-up still measured
  +1.82%.
- Built from a **competitor screenshot** the user shared. Analysed panel-by-panel against
  our DB rather than copied — it self-labels **"CONCEPT PREVIEW — SAMPLE DATA"** behind a
  £15/30d paywall (same trap as `macro_page_mock.html`). ≈⅓ real for us, ⅓ needed the
  cash leg, ⅓ needs data that doesn't exist. **Rejected deliberately**: cash/margin/theta/
  options (no data, user OK'd ignoring), supply-chain concentration (**zero edges**),
  "Style review 5.8/10 Balanced" (**an invented composite**).
- **Score (raw) + cohort columns** (the user's idea, and the one panel uniquely ours).
- **Risk section** (07-17): ATR(14)/ATR%, vol 20d/60d, 20d-50d S/R, **distances in ATR
  UNITS**, **1-ATR move as % of NAV**, true 52w hi/lo, mv-weighted book beta, top-3/sector.

## 📝 Files Changed
- `src/managers/portfolio_manager.py`: **NEW** — fill log, derived positions/cash, TWR.
- `scripts/portfolio.py`: **NEW** CLI — buy/sell/deposit/withdraw/positions/trades/nav.
- `scripts/pages/4_Portfolio.py`: **NEW** page + `_render_risk`.
- `tests/test_portfolio_manager.py`: **NEW** — 31 tests (3 mutation-checked).
- `scripts/dashboard_utils.py`: `load_portfolio` (+score/cohort/sector join), `load_cash`,
  `load_returns`, `load_nav_history`, `load_portfolio_risk`.
- `scripts/build_dashboard_db.py`: MANIFEST += `trades`, `cash_flows`, `nav_history`.
- `scripts/dashboard_uplift.py`: Portfolio mounted in nav.
- `docs/.../dashboard_uplift/README.md`: tracker + 2 build-log entries + files index.
- `docs/.../dashboard_uplift/portfolio_risk_section.md`: **NEW** design doc.

## 🚧 Work in Progress (CRITICAL)
- **Nothing committed.** 4 modified + 5 new files in the tree, for the user's review.
- ⚠️ **`nav_history` is NOT wired into the nightly** — NAV/returns only fill when
  `portfolio.py nav` is run by hand, so the series will have holes. Deliberately left for
  the user (which phase; whether it earns a nightly slot). **This is the top open item.**
- **Nothing wired into live `dashboard.py`.** The 3 redundant Today tables stay.
- `model_cards/m01_binary_v1_drift.json` still untracked/untouched (predates this thread).
- Pre-existing, NOT from this session: 7 failed / 26 errors
  (`test_phase1_backfill`, `test_feature_catalog`, + 4 collection-error modules).
- `_on_cloud()` creds false-positive still OPEN (carried from session 03).

## ⏭️ Next Steps
1. **Commit** this session (user's call — the tree is deliberately dirty).
2. **Decide the `nav_history` nightly wiring** (see WIP) — without it the NAV chart is
   holey the moment fills are logged.
3. **Track Record** — needs tradingagent to emit a **structured block** (ticker/direction/
   probability/horizon) beside the markdown prose. User confirmed reports are markdown
   files; parsing free prose into a Brier ledger would silently mis-score.
4. Optional: SPY-200d banner on Portfolio (reuse `weather_gauge`, don't recompute);
   score-decay column; benchmark-relative return (all listed in `portfolio_risk_section.md`).
5. Optional: COT (deferred); resolve `_on_cloud()` when there's cloud-container access.

## 💡 Context/Memory
- 🐛 **`update_series()` does NOT write the DB** — cache only. A silent no-op that cost an
  hour and that the last handover actively recommended. Also: **`macro_data.value` is NULL
  for all 69 symbols** — the populated column is `close` (an `AVG(value)` check returns NaN
  and looks like a broken ingest).
- 🐛 **pytest green ≠ the command works.** Unit tests never touch stdout, so 18 passing
  tests missed a CLI that **crashed on every successful trade** (✅ glyph vs Windows
  cp1252 under a bare `python.exe`). The writes had committed; only the print raised.
  **Driving the real CLI is what caught it.** → ASCII `[OK]`/`[ERR]`.
- ⚠️ **A verification command can itself be a false pass**: `grep -P` isn't supported in
  this locale, so a non-ASCII sweep printed "none" **without running**. Re-checked, then
  proved the fix under an actual cp1252 console.
- 🧪 **The ATR test was mutation-checked and the FIRST VERSION WAS WORTHLESS** — a
  constant true range makes every window average the same, so it passed with the window
  mutated 14→5. Fixed by varying TR per bar (ATR(14)=7.5 vs 5-bar=3.0). **A metric test
  must vary the input along the axis it claims to pin.** 2nd time this class hit this
  thread (cf session 04's bot-block test).
- 🐛 **`CREATE TABLE IF NOT EXISTS` silently skips an OLD-shape table** — the cash columns
  were a no-op until the (verified 0-row) `nav_history` was dropped. A schema change to a
  live table needs a real migration.
- ⚠️ **The model scores only ~751 of ~3,980 active tickers** (SEPA lifecycle universe) →
  a held name outside it renders **"—", never a stale score or a zero** (a zero reads as
  "model hates it"). Score is **RAW** (a rank, not a probability).
- ⚠️ **A true 52w level CANNOT be recomputed on the remote** — the slim DB windows
  `price_data` to ~172 bars. t3's `high_52w` is a **stored** value → READ it. Conversely
  ATR is computed in the loader (not read from t3's `atr_20d`) so the window is identical
  for every holding, including off-screen names.
- 🛑 **NO VaR/ES — and NOT for infra reasons** (~10 lines off `price_data`). It would
  mislead: needs a covariance matrix at book level, and with ~4 concentrated same-sector
  names the correlation term dominates; a window-fitted VaR prints calm right up to the
  regime that breaks it. **Don't re-propose.**
- **User framing (load-bearing):** entries/exits are **DISCRETIONARY**; the champion is
  only for expectation — *"it is a lottery"*. So: no divergence-from-champion panel, and
  every risk metric must resolve from `price_data` (all tickers), not t2/t3 (~2.4k/4.0k).
  The section **describes, never acts** — reinforced by the research having already
  falsified DD-brake / earnings-blackout / VIX de-risking on the cone.
- **The loader duplicates the manager's SQL/TWR math ON PURPOSE**: `ensure_schema()` opens
  a **WRITE** connection → exclusive lock vs the dashboard's readers, fatal on the
  read-only cloud container. Two tests pin the copies together.
- Verified: parity checked by opening `dashboard.duckdb` **directly** (bare connect) after
  rebuilding post-ingest; page driven end-to-end with **real** market data (PSNL/NVDA/KO
  incl. an off-screen holding); **381 passed**. Real book untouched: **0 rows** — all test
  data lived in temp copies, deleted.
- **No RESEARCH_LOG entry**: the ledger has **0** mentions of 07-16/07-17 — the
  dashboard-uplift thread has never been registered there (infra, not research questions).
  Kept session 04's precedent.
