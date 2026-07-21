# Dashboard — mobile pass + Model Lab consolidation

**Opened:** 2026-07-21 · **Status:** 🔄 active (first slice shipped) · **Owner:** dashboard

Backlog for the dashboard read surfaces, opened after the remote-boot incident on
2026-07-21 (see [`logs/2026-07-21_03_dashboard_boot_fix_and_mobile.md`](../logs/2026-07-21_03_dashboard_boot_fix_and_mobile.md)).
Two threads run through it:

1. **Mobile** — the app is read on a phone and was built at desktop width. Fixed
   pixel grids, 17-column tables and label-over-widget forms all fail below 640px.
2. **Model Lab consolidation** — the page has accumulated tabs (Overview, Plots,
   Report md, funnel, label outcome, label cone) from stale analytics. The model
   card is the artifact that matters; the rest needs justifying or deleting.

---

## Done (2026-07-21)

| # | Item | Where |
|---|---|---|
| — | Equity Research: 13-section radio → collapsible expanders; mobile CSS (title tracking, unbreakable accession tokens, table scroll) | `pages/7_Equity_Research.py` |
| — | Macro: S1 regime grid 7→2 cols, S2 heatmap 4→2 cols, S3 board scrolls | `pages/2_Macro.py` |
| — | Macro S3 on mobile: history sparkline column dropped, name column 24%→38%, row padding 13→10px (median row 64px → 56px) | `pages/2_Macro.py` |
| 1 | Finviz links restored on Screening; one `finviz_url()`/`finviz_ticker_col()` for all 5 tables, on the current `/stock?t=` URL form | `dashboard_utils.py` |
| 2 | Ticker column pinned (frozen left) on every wide table | Screening, Session Activity, Pipeline Health, main |
| 3 | Screening default order: fresh → triggered → score | `pages/3_Screening.py` |
| — | Screening filters: selectbox label inline with its control, capped at 220px (block height 68px → 40px); stacked again below 640px | `pages/3_Screening.py` |
| 7 | Model Lab metrics — the columns are holdout-TEST metrics, NULL by design under `--no-holdout`; page now falls back to `specs_json.val_metrics` and labels them **(val)**. Not a backfill: val ≠ test | `pages/3_Model_Lab.py` |
| 10c | Backtest Studio sector — narrower than triaged. Run-browser frames already carry `sector`; the **2,850+ cone-cell** parquets don't, and the cell zoom is where the filter reads. `attach_sector()` joins `company_profiles` at read (100% ticker match, 5–7 sectors/cell) | `pages/4_Backtest_Studio.py` |
| — | `test_sweep_sync_filter` was red on main since 633eec4 — `_ASSET_DIRS` became a `{prefix: Path}` dict, test still unpacked 2-tuples | `tests/` |
| 4 | Watchlist status — **decided: leave blank.** No Weinstein stage-4 ("distribution") exists anywhere in the repo; the derived `removed`/`watching` values were reading as claims the infra can't support | `pages/3_Screening.py` |

---

## Open — user feedback, 2026-07-21

### A. Dataset EDA — evaluate before regenerating
The only report on disk is `pretrain_audit_trades_20260529_180647.html` (53 days old
as of 2026-07-21). **Regenerating is not the task.** Evaluate first:

- **Content** — is the pretrain audit still asking the right questions? It predates
  the current label set and the T3 universe widening. A stale question re-run on
  fresh data is still the wrong report.
- **Format** — the embedded Plotly renders poorly in the page's iframe. The model
  card's static-HTML approach reads better for charts this simple (see B).

Only after that decision: regenerate, and per the long-run rule, smoke-test a small
batch first.

### B. Model card — static HTML, not interactive Plotly
The card's charts are simple enough that interactivity buys nothing and costs the
Plotly bundle plus an iframe that doesn't reflow. Render them as plain HTML/SVG.
Folds together with the card's mobile pass (item E below) — same file,
`scripts/build_model_card.py`.

### C. Model Lab — fold into the card, drop the rest
Assess each surface for **marginal value over the model card**. Anything that
survives moves *into* the card; anything that doesn't gets deleted, not hidden.

- `Report (md)` tab, `Plots` tab — from stale analytics; assess.
- Funnel, label outcome, label cone — currently missing even locally.
- **Overview section — probably not needed at all.** Default the page to the model
  card tab instead.

### D. Watchlist status — blank
Settled. See Done table.

---

## Open — carried from the 2026-07-21 triage

| # | Item | Size | Blocker |
|---|---|---|---|
| 10a | Backtest Studio: Sharpe distribution is unreadable — the -32 floor flattens everything. Smaller bins + clipping, or a log axis | S | taste call |
| 6 | Model Lab bump chart: unreadable on mobile, low information on desktop. A slope/dumbbell chart fits rank *change*; a waterfall is for additive decomposition and is probably the wrong tool | M | design |
| E | Model card HTML not adaptive on mobile — plus its `components.html` host has a fixed 900px height | M | pairs with B |
| — | Remaining fixed-height iframes: Dataset EDA (900), Macro S2 (1400), Model Lab (900). A content-following height needs a JS→Streamlit round trip | M | — |

---

## Notes for whoever picks this up

- **Verify at both widths.** Every mobile change here was measured in-browser at
  375×812 *and* 1280×800 — a media query that fixes the phone and quietly changes
  the desktop is the failure mode.
- **Measure, don't assume, on row height.** Inlining the S3 name and symbol *looked*
  like it would save a line; measured, it made rows taller (64px → 72px) because the
  text run then wraps mid-name. The stacked version shipped.
- **Streamlit's `st.dataframe` is a canvas**, not DOM. Cell contents can't be asserted
  from the page; verify column config through the API and the rendered page state.
