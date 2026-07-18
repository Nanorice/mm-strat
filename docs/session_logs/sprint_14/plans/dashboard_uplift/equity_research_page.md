# Equity Research page (`/equity-research`) — STUB

> Sprint 14, dashboard uplift. **Requested 2026-07-18 (user). Placeholder is fine for
> now** — ship the read surface, fill it as the agentic pipeline produces reports.

---

## What it is

The **read surface for single-name markdown reports**. One step in the knowledge-base
pipeline the user framed this session:

> `screening → shortlist → agentic markdown report → agentic digestion → knowledge base`

Screening produces the shortlist; an agentic pass writes a per-name markdown report; a
second agentic pass digests those reports into structured knowledge (which is also where
supply-chain **edges** come from — see `supply_chain_page.md`). This page is where a
human reads step 3.

## Scope for the first pass (placeholder)

- **Ticker picker** → render that name's markdown report.
- **Empty state that tells the truth**: "no report for TICKER yet", not a blank panel.
- Nothing else. No scoring of the report, no NLP, no summary generation.

## Open questions (do not guess — confirm with the user)

1. ~~**Where do reports live?**~~ ✔️ **ANSWERED by `research_layer_contract.md`**: the
   `research_reports` table, whose **`raw_md VARCHAR`** column is specified as *"full
   report markdown (source of truth)"*. So the page reads `research_reports.raw_md` —
   do **not** invent a file-directory convention. ⚠️ The table is a *contract*, not yet
   built — confirm it exists before wiring a loader; until then the page renders its
   empty state.
2. **Who writes them?** tradingagent is the assumed producer
   (`research_layer_contract.md` open question 1: *what does it emit, can it write DuckDB
   or drop a file?*). Still unanswered — it sizes the ingest side.
3. **Slim-DB / remote**: if reports are files they will **not** reach the remote app
   (same constraint as backtest trades/rejections — dev-box-local). If they're a table
   they need a MANIFEST entry (`project_dashboard_remote_parity`). Decide per the answer
   to Q1.

## Constraints carried in

- **Tier 1 or Tier 2?** It's a *reading* surface for decision support → Tier 1
  (cream/serif, `style.md`), unlike the Model Lab / Studio workshop pages.
- Ship as a **new shadow page**, mounted in `dashboard_uplift.py` — never edit live
  `dashboard.py` before switch-over.
- Placeholder means placeholder: an honest empty state beats a fabricated report.
