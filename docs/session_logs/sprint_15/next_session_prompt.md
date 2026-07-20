# Next-session prompt — research report ingestion (steps 1–2)

> Paste the block below as the opening message of the next session.
> Everything above the rule is context for you, not for the prompt.

**Why these two steps:** they are the only ones in the design doc's build order
that no open question blocks. Steps 3–5 depend on decisions listed at the end of
this prompt.

---

Implement **steps 1 and 2 only** of the build order in
`docs/session_logs/sprint_15/plans/report_ingestion_and_knowledge_base.md`:

1. `research_reports` landing table + `src/research_report_engine.py`
2. The quote-fidelity checker, as a real module in this repo

**NOT in scope:** `research_signals`, the `comprehend_reports` phase,
`supply_chain_edges`, name→ticker resolution, the corroboration harness. Step 3
onward is gated on step 2 producing a fidelity number worth trusting.

## Read first

- The design doc above — it is the spec. Do not re-derive the schema.
- `docs/session_logs/sprint_15/verdicts/edgar_section_slicing_proofread.md` —
  what the upstream cache is and why it is trusted.
- `.claude/CLAUDE.md` layering rules. Ingest is an **engine** (one source → one
  raw table, no interpretation), not a pipeline and not a manager.

## Ground truth to build against — do not invent fixtures

A real completed run is on disk. Use it, not a hand-written sample:

```
~/.tradingagents/logs/reports/RKLB_20260719_212611/
  complete_report.md   report.json   manifest.json   1_analysts/ … 5_portfolio/
```

`report.json` and `manifest.json` both carry `schema_version: "1.0"`.
`report.json.agents` maps agent name → model dump, or **null** where that agent
fell back to free text. Null and absent mean different things: null = "ran,
produced nothing typed"; absent = "was not in the graph". Preserve the
distinction.

Cached filings for the fidelity checker are at
`~/.tradingagents/cache/edgar/<TICKER>/<accession>/item{1,1a,7}.md`.

## Step 1 — engine

- `src/research_report_engine.py`, following `src/edgar_engine.py`'s shape:
  `_ensure_tables()` with `CREATE TABLE IF NOT EXISTS`, `db.connect(path)`,
  `try/finally: conn.close()`.
- Schema exactly as the design doc specifies. PK `(ticker, report_date, source)`.
  `report_date` comes from `manifest.trade_date` — **never** the folder's
  wall-clock stamp. A same-day re-run replaces; it does not duplicate.
- **Reject on major `schema_version` mismatch**, loudly, naming both versions.
  Silent half-reads of a changed shape are the failure this field exists for.
- Ingest must be idempotent: re-running over the same drop dir is a no-op.
- `raw_md` is 40–60KB/row. Never `SELECT *` on this table.
- A run missing `report.json` still ingests, with `key_facts_json` NULL.

## Step 2 — fidelity checker

A prototype already exists and works:
`C:\Users\sh019\Documents\projects\TradingAgents\scripts\eval_business_profile.py`.
Port the logic here (this repo is the consumer; verification belongs on the
consumer side). Reuse its approach, and keep its two hard-won details:

- **Strip edge punctuation before matching.** Models terminate quotes with a full
  stop the source lacks at that point. Verified: two deepseek quotes matched
  389/390 and 230/231 characters and failed only on a trailing `.`. Counting that
  as fabrication understated fidelity by 8.7pp — it reported 91.3% for a run that
  is actually 100%.
- **Keep the negative controls.** A real quote must pass; the same quote with one
  figure altered must fail; an invented sentence must fail. Without these the
  checker can silently become a rubber stamp.

Ellipsis-elided quotes are multiple fragments — check each. Normalise NFKC,
curly→straight quotes, en-dash→hyphen, collapse whitespace, lowercase.

Store `quote_verified` per claim. An unverified claim must never reach the
knowledge base silently.

## Verification before you report done

- Ingest the real RKLB run; row lands with `report_date = 2026-07-19`.
- Ingest it twice; still one row.
- Corrupt a copy's `schema_version` to `"2.0"`; ingest rejects it loudly.
- Fidelity checker on that run reports **100% (23/23 claims)**. Anything else
  means the port broke something — the number is known.
- `.venv/Scripts/python.exe -m pytest tests/` green.

## Environment

- This box is `sh019` — the **infra/ops box** running the live Prefect server and
  nightly scheduler. Be careful with anything touching them.
- `.venv/Scripts/python.exe`; tests in `tests/`.
- `data/market_data.duckdb` is single-writer. Use `src/db.py`'s `connect()`;
  `read_only=True` for any read-only inspection.
- The agent repo is a separate checkout at
  `C:\Users\sh019\Documents\projects\TradingAgents` with **its own** `.venv`.

## Known facts that should shape the design

- **Extraction varies run to run.** The same model over the same cached filing
  produced 14 relations once and 7 another time. Do not build anything that
  assumes one run is a complete extraction. This is why corroboration is a later
  step and why `confidence` is not a boolean.
- **Roughly half of RKLB's named counterparties resolve to no ticker** — NASA,
  DARPA, NRO, SDA, plus private firms. Storing the name is mandatory; a ticker is
  not.
- `company_profiles.name` (4,176 rows) and `cik_map.company_name` are the two
  resolution sources — for a later step, not this one.

## Decisions needed from the user — ask before step 1, they change the schema

1. **Cross-machine transport.** The agent writes on this box; is the drop dir
   synced, copied, or is ingest run here against a shipped DB? Sizes the engine.
2. **Canonical run when a name is run several times in a day.** Add `run_id` to
   the PK, or keep `research_reports` one-row-per-day and put per-run extractions
   in a child table? Recommend the child table — the landing table stays the
   human-readable record.
3. **Per-agent schema versioning.** `schema_version` currently describes the
   sidecar envelope, not `BusinessProfile` itself. If that schema gains or renames
   a field, this version will not capture it. Splitting it is cheapest **before**
   ingest is written.

Do not guess these. Ask, then build.
