# Session Handover: 2026-07-18 (session 09) — switch-over SHIPPED · 🛑 TIER-0 DB INCIDENT

## 🛑 READ THIS FIRST — the main database was destroyed

**`data/market_data.duckdb` lost its deep history.** `price_data` now spans
**2025-11-06 → 2026-07-16** (695,655 rows / **172 distinct dates** / 4,172 tickers)
instead of ~23 years. Caused by **me**, this session.

**Restore from `sh019`.** Verify before trusting any copy:

```python
duckdb.connect('data/market_data.duckdb', read_only=True) \
  .execute('select count(distinct date) from price_data').fetchone()
# real DB ≈ 5,800   ·   damaged copy = 172
```

⚠️ **Check sh019 for the same damage** — it holds R2 credentials too, so any
process there that set `DASHBOARD_DB_PATH` would have hit the identical fate.

### What happened
Verification runs used `DASHBOARD_DB_PATH=data/market_data.duckdb`. Importing
`dashboard_utils` runs `_ensure_local_db()` **at module scope**; `_on_cloud()`
returned true on the dev box because it only checked **R2 credentials**; the pull
downloads the slim `dashboard.duckdb` and `os.replace`s it onto **whatever
`DASHBOARD_DB_PATH` names**. Three latent conditions, one command.

### Forensics (don't re-derive)
- The file is a **HYBRID, not a clean overwrite**: 28 tables match the slim DB, but
  `pipeline_runs` (810 vs 813) and `t2_screener_features` (472,159 vs 469,429)
  differ, and **5 non-MANIFEST tables survived** (`feature_catalog`,
  `model_feature_sets`, `forced_promotions`, `screener_criteria_versions`,
  `table_write_log`) — impossible from a straight `os.replace`.
- `data/market_data.r2etag` and `data/dashboard.r2etag` hold the **same ETag**
  (`9177a44e…-94`) — proof the pull targeted the main path.
- Main's `pipeline_runs` stops at `sector_breadth` **10:22:03** (07-17); the slim
  continues to `dashboard_db` 10:23:44 → `r2_sync` 10:25:42 → `model_card` 10:27:49.

### 🔍 Why it stayed invisible (the important lesson)
**`macro_data` is MANIFEST-`full`** — 214,732 rows / 69 symbols, byte-identical in
both DBs. So the Macro S3 board rendered **perfectly** off the destroyed database,
which is exactly what prompted the user's question ("the macro dashboard still has
the new indicator time series, was that overwritten?"). **A page that looks right
is not evidence the data is intact.** Only the *windowed* tables (`price_data`,
`t2`, `t3`) reveal the loss — and `price_data`'s 172-date span sat in my own
supply-chain output for hours, misread as a slim-DB characteristic.

## ✅ Fixes shipped (user's two rules)

> 1. *"Dashboard is read-only. Why would it trigger any data write?"*
> 2. *"Never let remote DB write back to local. Communication is ONE WAY only."*

**Data flow is now, by construction:**
`local main DB → build_dashboard_db → slim DB → R2 → remote viewer`

- **Barrier 1 — `_on_cloud()` rewritten.** Requires an explicit
  **`DASHBOARD_PULL_FROM_R2=1`** opt-in that only the Streamlit Cloud deployment
  sets. **Credentials grant nothing** (they only ever meant "can reach R2").
  ⚠️ **Streamlit Cloud must set this secret**, or the remote silently stops
  refreshing. The local→R2 **upload** (`sync_dashboard_db.py`) still gates on
  creds — deliberately untouched, it's the legitimate direction.
- **Barrier 2 — destructive-overwrite guard.** `_ensure_local_db()` raises
  `RuntimeError("Refusing R2 pull: …")` when `target.name != "dashboard.duckdb"`,
  **before** `_r2_client()` is constructed. Either barrier alone would have
  prevented the incident.
- **`tests/test_r2_pull_guard.py` (NEW, 7 tests)** — mutation-checked (removing the
  guard fails 2; removing the opt-in fails 1). They deliberately **do not import
  `dashboard_utils`** — importing it under creds IS the dangerous action — and
  assert on the source instead. My first two attempts DID import it and failed for
  harness reasons; the third approach is the correct one.
- **`.env.example` + `dashboard.py` docstring** carry the one-way rule and a
  🛑 never-do-this on `DASHBOARD_DB_PATH`.

**Verified across 4 scenarios**: dev/no-vars → reads full DB, no pull · dev+creds+
main-path (**the incident**) → no pull attempted · cloud opt-in+slim path → pull
proceeds · opt-in+wrong path → **refused**.

⬜ **DEFERRED (structural, the real fix for rule 1)**: `_ensure_local_db()` and
`_ensure_asset_dirs()` still run at **module scope**, so `import dashboard_utils`
remains a provisioning action rather than a read. Both are inert without the opt-in,
so the blast radius is closed — but the clean fix is an explicit
`bootstrap_remote()` called only from the cloud entrypoint. Marked in-file.

## ✅ Also shipped: the dashboard switch-over is DONE

Live `dashboard.py` now runs a **two-tier `st.navigation`**; the "Today" monolith is
retired and `dashboard_uplift.py` is deleted.

- **Decide**: Macro *(default landing)* · Screening · Session activity · Portfolio ·
  Supply chain · Equity research
- **Workshop**: Dataset EDA · Model Lab · Backtest Studio · Pipeline Health

**Triage of the 13 Today sections — 4 carried, 5 dropped** (evidence in
`plans/dashboard_uplift/README.md`). Two README premises were **wrong**:
- 🛑 *"Screener Watchlist → Portfolio"* was never a migration — `screener_watchlist`
  (38,648 algorithmic sessions) vs `trades` (**0 rows**, the real book) are different
  populations. Folding them would have mixed simulated sessions into a real NAV.
- 🛑 The 13-section count **missed `render_vip_watchlist`** — a 9th orphan.

**New pages**: `5_Session_Activity.py` · `6_Supply_Chain.py` · `7_Equity_Research.py`.
**Promoted** (git mv, history preserved): `3_Model_Lab_v2.py` → `3_Model_Lab.py`,
`4_Backtest_Studio_v2.py` → `4_Backtest_Studio.py`; v1 files deleted.
**Model Lab** gained `render_live_monitoring()` (rank bump, prod-scoped, above the
registry selector).

- **Section #9 needed NO BUILD** — the watchlist table already existed on Screening;
  only the naming was wrong (VIP → **Watchlist**, `sepa_active` for the table above).
  *Reading the target file first turned a "build a page" task into a 3-line rename.*
- 🔁 **A wrong claim I made earlier this session, corrected**: the watchlist scoring
  gap is NOT "no features exist". `feature_pipeline.py:637` UNIONs `vip_watchlist`
  into the T3 candidate set. The real gap is **one join**: `v_d3_lifecycle`'s `wl`
  CTE INNER JOINs `screener_watchlist`, so a name with features but no SEPA *session*
  lands in no cohort. **Fix = INNER→LEFT JOIN on one view.** Deferred by the user.
- **Cohort-Return dropped on methodology**, not on the reason proposed: `cohort` lives
  on `daily_predictions` (from `v_d3_lifecycle`), so it does NOT die with
  `screener_watchlist` — **two unrelated things called "cohort"**. It was dropped
  because its median band contradicts the sprint's tail-first conclusion.

## 🐛 Open — user feedback on the deployed dashboard (NOT yet addressed)

1. **Supply-chain render differs from the standalone mock.** I chose a Plotly heatmap
   over the mock's d3 chord (CDN dependency + chord reads ordinally at 11 sectors).
   User expected the mock's look — **revisit; my call may have been wrong.**
2. **Model Lab**: rank-bump colours **too colourful** (palette is
   `Alphabet + Light24`, one hue per ticker — needs a muted//single-hue scheme);
   Overview section **font needs adjustment**; **label cone missing** (⚠️ this is the
   DB incident — `cone_cells` is absent from the damaged main DB); **Plots / Report
   (MD) look stale** (likely the same data loss — re-check after restore).
3. **Backtest Studio**: run list **not pointing at the new backtests**. User's steer:
   *"instead of moving the pointer, make sure the backtest run results are properly
   cached."* — a caching-design question, not a path fix.

## 📝 Files Changed
**New**: `scripts/pages/5_Session_Activity.py`, `scripts/pages/6_Supply_Chain.py`,
`scripts/pages/7_Equity_Research.py`, `tests/test_r2_pull_guard.py`.
**Deleted**: `scripts/dashboard_uplift.py`, old `3_Model_Lab.py`, old
`4_Backtest_Studio.py`.
**Modified**: `scripts/dashboard.py` (two-tier nav; `page_today` retained but
**unrouted** — dead code kept one cycle, deletion pass pending),
`scripts/dashboard_utils.py` (`_on_cloud` rewrite + guard + 2 supply-chain loaders),
`scripts/pages/3_Screening.py` (naming), `scripts/pages/3_Model_Lab.py`
(live monitoring), `.env.example`, and the docs below.

**Docs synced**: `plans/dashboard_uplift/README.md` (triage + build log + switch
section), `manual_for_me.md`, `comprehensive_methodology.md`,
`docs/modules/dashboard.md`, `data_flow_legend.md`.

**NOT COMMITTED** — user reviews first.

## ⏭️ Next session
1. **Restore the DB from sh019** and re-verify (`price_data` date count). Everything
   else is downstream of this.
2. Re-check feedback items 2 and 3 **after** restore — the missing cone and stale
   plots are probably data loss, not code.
3. Rank-bump palette + Overview typography; revisit the supply-chain render.
4. Backtest run **caching** design (user's framing, not a pointer move).
5. Deployment scope: how the app is served/restarted on `sh019`; confirm the cloud
   app sets `DASHBOARD_PULL_FROM_R2=1`.
6. Optional cleanup: delete the unrouted `page_today` block; move module-scope
   provisioning into `bootstrap_remote()`.

## 💡 Context/Memory
- Suite: **393 passed / 14 failed** (+7 new guard tests). The 14 were verified
  **pre-existing** by stashing all changes and re-running on a clean tree.
  ⚠️ The documented baseline said **7**; it has drifted to 14–15 over prior sessions
  (`test_backtest_smoke`, `test_forward_parity` are newer arrivals) — worth its own
  look; none are dashboard tests.
- All 10 pages driven via `AppTest` against **both** DBs → 0 exceptions (20 runs).
  Booting the app only renders the *default* page — every route was driven
  individually, because a broken non-default page is invisible to a boot check.
- Memory written: `project_r2_pull_destroyed_main_db` (supersedes the older
  `project_on_cloud_creds_false_positive` as the operative rule).
