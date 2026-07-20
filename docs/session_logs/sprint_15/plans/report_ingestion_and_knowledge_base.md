# Report Ingestion → Knowledge Base — Design

> Sprint 15. Planning doc. Implementation lands in **mm-strat** (this repo).
> Closes the open question in
> [`research_layer_contract.md`](../../sprint_14/plans/dashboard_uplift/research_layer_contract.md):
> *"What does the tradingagent actually emit today?"*
>
> Written 2026-07-19 against a **real** completed run
> (`RKLB_20260719_212611`, run_id `186fa743cc20`), not a hypothetical one.

---

## Answering the contract's open question

The agent now emits three artifacts per run. All fields below were read off a
real run, not designed on paper.

```
<results_dir>/reports/<TICKER>_<wallclock_stamp>/
├── complete_report.md      # consolidated prose — the source of truth
├── report.json             # typed output of every structured agent   ← NEW
├── manifest.json           # run identity, models, usage, price       ← NEW
├── 1_analysts/{market,sentiment,news,fundamentals,business}.md
├── 2_research/{bull,bear,manager}.md
├── 3_trading/trader.md
├── 4_risk/{aggressive,conservative,neutral}.md
└── 5_portfolio/decision.md
```

`report.json`:
```json
{"schema_version": "1.0", "ticker": "RKLB", "trade_date": "2026-07-19",
 "agents": {"sentiment_analyst": {...}, "business_analyst": {...},
            "research_manager": {...}, "trader": {...},
            "portfolio_manager": {...}}}
```
An agent whose structured call fell back to free text appears as `null` —
*"ran and produced nothing typed"* is deliberately distinct from *"was not in
the graph"* (absent key).

`manifest.json`:
```json
{"schema_version": "1.0",
 "run_id": "186fa743cc20", "ticker": "RKLB", "trade_date": "2026-07-19",
 "generated_at": "...", "asset_type": "stock", "selected_analysts": [...],
 "models": {...}, "debate_rounds": {...},
 "usage": {"llm_calls": 19, "prompt_tokens": 191171,
           "completion_tokens": 32568, "reported_cost_usd": 0.067316},
 "price_snapshot": {"close": 67.62, "as_of": "2026-07-17", "source": "yfinance"}}
```

### The contract maps cleanly — no schema change needed

| `research_reports` column | Source | Notes |
|---|---|---|
| `ticker` | `manifest.ticker` | |
| `report_date` | `manifest.trade_date` | **Not** the folder stamp — see below |
| `source` | literal `'tradingagent'` | |
| `raw_md` | `complete_report.md` | |
| `summary` / `thesis` | `report.json → research_manager` | `rationale` / `recommendation` |
| `conviction` | `report.json → portfolio_manager.rating` | 5-tier enum, already typed |
| `key_facts_json` | `report.json` wholesale | |
| `run_id` | `manifest.run_id` | |
| `ingested_at` | set on write | |

**Why `trade_date` and not the folder name.** The folder is stamped with
wall-clock time; `research_reports` PKs on `(ticker, report_date, source)`.
Backfilling a week of history in one evening makes those disagree for every row,
and the PK would collapse to a single day. The manifest exists largely to make
this distinction unambiguous at the boundary.

---

## Why the agent does not emit the KB schema directly

Considered and rejected (user proposal, 2026-07-19): have the agent write a file
already shaped for `supply_chain_edges` / the knowledge base, removing the
mapping step here.

**It cannot.** `supply_chain_edges` requires `dst_ticker`. Resolving
`"Blacksky Holdings"` → `BKSY` needs `company_profiles.name` and
`cik_map.company_name`, which live in `market_data.duckdb` on this box. The agent
has neither. It would emit a half-filled schema and this repo would *still* run
resolution — the coupling is paid for and the work remains.

Three further costs:

- **Schema changes become cross-machine deploys.** Every KB column change would
  require shipping the agent to the ops box. This is exactly the coupling the
  contract settled against.
- **The producer would be verifying itself.** Quote fidelity is only meaningful
  when checked by the consumer against the cached filing.
- **Replay dies.** Re-interpreting relations from cached JSON is free;
  re-running the agent is LLM spend. Demonstrated 2026-07-19: the fidelity
  checker was re-scored three times over existing runs at zero cost while a
  false-negative bug was fixed.

**The valid part of the proposal is the shape, not the location.** The payload
was implicit — a consumer had to infer it from the keys present. So it is now
explicit and versioned, and both sides target it.

### The versioned payload contract

`report.json` and `manifest.json` carry `schema_version` (currently `"1.0"`,
constant `SIDECAR_SCHEMA_VERSION` in `tradingagents/reporting.py`). Minor bump =
additive, a consumer may ignore unknown keys. **Major bump = a key removed,
renamed, or changed meaning — ingest must reject the file loudly rather than
half-read it.** An ingest layer that guesses will keep succeeding silently on the
old shape long after the producer has moved on.

Division of labour, fixed:

| | Agent emits | mm-strat derives |
|---|---|---|
| Counterparty | name exactly as disclosed | `dst_ticker` via resolution |
| Claim support | verbatim `quote` + `source` + `strength` | `quote_verified` |
| Confidence | per-claim `strength` only | `confidence` (strength × verified × corroboration) |
| Identity | `run_id`, `trade_date` | `ingested_at`, PK enforcement |

The rule: **the agent emits what the filing says; this repo emits what we
conclude.** Anything requiring a table on this box, or a judgement about the
agent's reliability, is ours.

---

## Transport: drop-file, not direct DuckDB

**Recommendation: the agent writes files; mm-strat ingests them.** The agent
already does this — no change needed on its side.

Direct DuckDB writes from the agent are the wrong call on three counts:

1. **Single-writer discipline.** `market_data.duckdb` tolerates exactly one
   writer. The agent runs unattended and can overlap the nightly Prefect
   pipeline; a second writer either blocks the pipeline or is blocked by it.
   This constraint is already load-bearing across the repo.
2. **Layering.** The contract settled that the agent "knows nothing of this
   repo's internals." A DuckDB dependency is exactly that knowledge.
3. **Replay.** Files on disk can be re-ingested after an extraction bug. A
   direct write cannot — the failure is already in the table.

The report tree *is* the drop format. Nothing new to build agent-side.

**Open (needs a decision): how do files cross machines?** The agent runs on the
ITX/ops box, `market_data.duckdb` lives with the research box. Options: a synced
folder, an rsync/robocopy step, or running ingest on the ops box against a
shipped DB copy. Not resolvable from here — see Open Questions.

---

## Layering (per CLAUDE.md)

```
drop dir → research_report_engine.py → research_reports  (raw landing)
                                            ↓
           research_comprehension.py  → research_signals (compute)
                                            ↓
                                       supply_chain_edges (deferred)
```

- **`src/research_report_engine.py`** — an *engine*: fetches from one source
  (the drop dir), writes one raw table. Same shape as `edgar_engine`. It does
  **no** interpretation: parse, validate, insert, move on.
- **`src/research_comprehension.py`** — a *pipeline*: compute over data we own,
  same shape as `feature_pipeline`. Reads `research_reports`, writes
  `research_signals`.
- **Orchestrator phase** `comprehend_reports` in `phase_registry.py` — stable id,
  order after ingestion. Ingest itself can ride the existing `ingestion` phase or
  take its own id; prefer its own, so a drop-dir failure is legible in the
  heatmap rather than hidden inside ingestion.

Keeping ingest and comprehension separate matters because they fail differently:
ingest fails on malformed files (loud, cheap to retry), comprehension fails on
extraction quality (quiet, expensive to detect). Merging them would hide the
second behind the first.

---

## `research_reports` — landing table

Schema exactly as the contract specifies. Implementation notes:

- **PK `(ticker, report_date, source)`.** A same-day re-run must **replace**, not
  duplicate. `INSERT … ON CONFLICT DO UPDATE`, keeping the newer `run_id`. Two
  runs of the same name on the same trade date are a re-run, not two opinions.
- **`raw_md` is the source of truth.** Everything else is best-effort and
  re-derivable. If `report.json` is absent (older run, or every agent fell back
  to free text), the row still ingests with `key_facts_json = NULL`.
- **Ingest is idempotent and file-driven.** Track ingested run directories
  (a `research_report_files` log, or a marker file in the run dir). Re-running
  ingest over the same drop dir must be a no-op.
- **Never `SELECT *` on this table** — `raw_md` is ~40–60KB per row.

---

## The verification gate — the part that decides if any of this is real

The business analyst's `relations` are exactly the
`{counterparty, direction, %rev}` triples that `supply_chain_page.md` calls
**Tier 3 (LLM-assisted extraction)**, and that doc names the risk precisely:
*"needs a verification gate (hallucinated tickers)."*

Two independent gates, both cheap, both mechanical:

**Gate 1 — quote fidelity.** Every claim in `BusinessProfile` carries
`evidence.quote`, required to be verbatim from the filing. The cached filing is
on disk at `edgar/<TICKER>/<accession>/`. So each quote can be checked by string
containment against the source. A quote that does not appear **did not come from
the filing**, and every claim resting on it is discardable. This turns
"do we trust the model?" into a measured number per run.

Store the result: `research_signals` (or a column on the ingested facts) should
carry `quote_verified BOOLEAN`. Unverified claims must never reach the knowledge
base silently.

**Gate 2 — name→ticker resolution, deliberately outside the agent.** The agent
emits `"Blacksky Holdings"`, never `BKSY` — resolving names was kept out of the
agent on purpose so the verification step isn't checking the model's own guess.
Resolution sources already in the DB:
- `company_profiles.name` (4,176 rows)
- `cik_map.company_name`

This is a fuzzy-match problem with real failure modes: subsidiaries that aren't
listed ("Kinéis" is private), government bodies that are not companies at all
(NASA, DARPA, NRO, SDA — a large share of RKLB's counterparties), and name drift.
**An unresolved counterparty must be stored, not dropped** — "49% of revenue to
an unnamed top-five group" is a real, useful concentration fact even with no
edge to draw. Store `counterparty_name` always, `dst_ticker` nullable.

### Observed extraction variance — must be handled, not assumed away

Two runs of the same node over the same cached filing produced **14 relations and
7 relations**. Same model, same input. Implications:

- A single run is not a reliable extraction of a filing's relations.
- Edges need `confidence` and a `first_seen` / `last_seen`, not a boolean.
- Corroboration across runs is the cheap fix: a relation appearing in *k* of *n*
  runs is stronger than one appearing once. The filing is immutable and cached,
  so re-running is cheap and deterministic on the input side.

Do not build the knowledge base on single-run extraction.

---

## `supply_chain_edges` — deferred, but the shape is now known

Target from `supply_chain_page.md`:
`(src_ticker, dst_ticker, weight, direction, source_type, as_of, confidence)`

From one `Relation`:
- `src_ticker` = the subject company
- `dst_ticker` = resolved counterparty, **nullable**
- `direction` = `customer` / `supplier` / `partner` / `competitor`
- `weight` = `pct_revenue` when disclosed, else null (do **not** impute)
- `source_type` = `10k_item1` etc., from `evidence.source`
- `as_of` = filing period, from the cached `meta.json`
- `confidence` = f(`evidence.strength`, quote-verified, corroboration count)

Blocked upstream on the still-open **build vs buy** decision (open since
2026-07-18). This design does not resolve it; it just means Tier 1/Tier 3 now
have a working extractor if "build" is chosen.

---

## Build order

1. **`research_reports` table + `research_report_engine.py`.** Ingest only, no
   interpretation. Reject any file whose `schema_version` major differs from the
   one the engine was written against — loudly, naming the versions. Gate:
   re-running over the same drop dir is a no-op.
2. **Quote-fidelity checker.** Standalone and testable against cached filings —
   no LLM, no network. Run it over existing reports before building anything on
   top. **If fidelity is poor, stop here** — everything downstream inherits it.
3. **`research_signals` + `comprehend_reports` phase.** Only after (2) reports a
   number worth trusting.
4. **Corroboration harness** — n runs per name, relation frequency.
5. **`supply_chain_edges`** — only after the build-vs-buy call.

Steps 1 and 2 are independent of every open question below and can start now.

---

## Open questions

- **Cross-machine transport.** The agent runs on the ops box; the DB lives with
  research. Synced folder, copy step, or ingest-on-ops? Sizes the engine.
- **Which runs are canonical?** If a name is run several times in a day
  (deliberately, for corroboration), the PK keeps one row. Either add `run_id` to
  the PK, or keep `research_reports` one-per-day and put per-run extractions in a
  child table. **Recommend the child table** — the landing table stays the
  human-readable record, corroboration lives where it belongs.
- **Government and private counterparties.** ~Half of RKLB's named relations
  resolve to no ticker. Are they nodes in the knowledge base (useful: "how many
  names depend on DoD budget?") or dropped? Recommend keeping them as
  non-tradeable nodes.
- **Retention.** `raw_md` at ~50KB × names × days. 100 names daily for a year is
  ~1.8GB in one DuckDB table. Cap, compress, or archive cold rows to parquet.
