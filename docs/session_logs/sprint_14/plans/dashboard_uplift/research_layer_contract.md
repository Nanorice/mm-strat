# Research Comprehension Layer — Contract Stub

> Sprint 14, dashboard uplift. Planning doc only (no implementation).
> The seam between the **externally-deployed tradingagent** and **this repo**.
> Settles *where the boundary is*; extraction/pattern logic is deferred.

---

## Ownership decision (settled)

```
[tradingagent]         →  writes  →  [THIS repo: comprehension layer]  →  feeds
 (other box/repo,          research_reports    ingest → extract → cross-name       model +
  runs on top names/day)   (landing table)     patterns → research_signals         dashboard
```

- **Agent stays external.** It writes one thing — its report — into
  `research_reports`, exactly as `data_engine` writes prices. It knows nothing of
  this repo's internals. Coupling it in would break the engine/pipeline/manager
  layering (CLAUDE.md First Principles).
- **Comprehension layer = core repo work.** It's compute on data we own — same
  shape as `feature_pipeline`. A new orchestrator phase (`comprehend_reports`)
  reads `research_reports`, writes `research_signals`. This is ours to build.
- **The table is the contract.** Nail the schema now; both sides target it.
  Everything downstream (extraction, ticker-resolution, pattern-mining) is
  deferred implementation.

**Scope guard:** the layer's job is "understand names & market," *not* "build the
supply-chain graph." Relationship edges may fall out of the reports later
(supply-chain Tier 3), but that's a bonus downstream — don't let it redefine
this layer's purpose.

---

## Contract: `research_reports` (agent writes)

The boundary. Agent inserts one row per report per name per day.

| Column | Type | Note |
|---|---|---|
| `ticker` | VARCHAR | resolves to `company_profiles` |
| `report_date` | DATE | as-of date the agent ran |
| `source` | VARCHAR | e.g. `tradingagent` |
| `raw_md` | VARCHAR | full report markdown (source of truth) |
| `summary` | VARCHAR | agent's own short summary (optional) |
| `thesis` | VARCHAR | one-line investment thesis (optional) |
| `conviction` | VARCHAR/DOUBLE | agent's stance/score (optional) |
| `key_facts_json` | JSON | any structured fields the agent already extracts |
| `run_id` | VARCHAR | agent run correlation |
| `ingested_at` | TIMESTAMP | set on write |

PK `(ticker, report_date, source)`. Only `ticker`/`report_date`/`source`/`raw_md`
are required; the rest are best-effort — **this repo re-extracts from `raw_md`**
regardless, so a thin agent still works.

---

## Downstream (this repo, deferred)

- **`comprehend_reports` phase:** read new `research_reports` → extract structured
  facts (LLM/parse) → cross-name patterns → write **`research_signals`**
  (ticker, report_date, signal_type, value, evidence). Schema TBD at build.
- **News feed / reading list** = a *view* over `research_reports` +
  `earnings_calendar` (upcoming) + screening P(HR). No new data — a join.
- **Forecast ledger** (`forecasts`) — separate track; the tradingagent's
  conviction calls scored by the existing Brier/cone machinery → theta's Track
  Record page. Highest-leverage because the scoring already exists.

---

## Open question for the user

**What does the tradingagent actually emit today?** The schema above is the
*target*; confirm the agent's real output fields so `key_facts_json` /
`conviction` map cleanly, and whether it can write DuckDB directly or needs a
drop-file (JSON/MD) → ingest step on this box. That answer sizes the ingest side.
