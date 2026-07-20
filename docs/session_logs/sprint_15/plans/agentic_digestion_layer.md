# Agentic Digestion Layer — Parked Vision

> Sprint 15. **🅿️ PARKED — not this sprint's work.** Recorded so it isn't lost while
> the focus is tuning the report generator
> ([`tradingagents_business_analyst.md`](tradingagents_business_analyst.md)).
> Nothing here should be built until reports are worth digesting.

---

## Where this sits

```
daily pipeline → [1] shortlist → TradingAgents reports → [2] ingest → [3] comprehend
    → [4] sector knowledge base → [5] Discord briefing → human review → decision
```

Sprint 15 owns the *report generation* between [1] and [2]. Everything numbered here
is downstream and deferred.

---

## [4] first: the knowledge base is **sector-partitioned** — the organising decision

*(User, 2026-07-19: since this touches the supply chain of a sector, the digestion layer
should recognise names by sector and build that up with each incremental company report.)*

This is the right shape and it inverts the naive design. The unit of knowledge is **not
the company** — it's the **sector chain map**, which each company report incrementally
fills in.

```
sector_chain_map (sector, layer, …)      ← the accumulating artifact
    └─ layers per serenity taxonomy: downstream demand · system integrators · modules
       · chips/devices · process & packaging · equipment & testing · materials
       · infrastructure
    └─ per layer: known occupants, bottleneck severity, evidence, coverage %
```

Each new company research does one of three things:
1. **Fills a layer** — places a name in a chain layer with evidence.
2. **Adds an edge** — a disclosed counterparty relation.
3. **Revises a bottleneck** — strengthens or contradicts an existing judgment.

**Consequences worth stating now:**

- **A completed sector is the deliverable**, not a pile of reports. This gives an honest
  progress metric (coverage % per sector per layer) instead of a report count.
- **Contradiction handling is a first-class requirement.** Two reports on the same sector
  will disagree about who's the bottleneck. The map must hold competing claims with
  evidence strength and dates, not last-write-wins. Design for it up front — retrofitting
  it is much harder.
- **Everything is date-stamped and never overwritten.** (User: "cache the bias with a date
  stamp.") The map is a time series of judgments; a superseded view stays readable. This
  is also what lets the layer's own bias be audited later.
- ⚠️ **This tensions with the shortlist rule.** A sector map completes only if names
  arrive **sector-clustered**; a pure top-N-by-score feed scatters one name each across
  eight sectors and no map ever completes. Either sector-order the queue or accept that
  maps fill slowly and unevenly. **Unsettled — flag, don't assume.**

---

## [1] Shortlist selector — does not exist yet

Phase 7.4 writes `daily_predictions`, but **nothing ranks and cuts it**. Needed:
- Top N by score × market cap, N set by *digestion capacity*, not model confidence
  (user: the limit is how many reports can be digested per day; grows as the pipeline
  gets more efficient).
- **Cooldown** — don't re-run a name within N days unless its score moved materially.
  Re-litigating an unchanged thesis nightly burns tokens for nothing.
- Emits `shortlist.json`. **Do not import one repo into the other** — the two checkouts
  have separate venvs. File hand-off, separate scheduled task.

## [2] Ingest — `src/research_ingest_engine.py`

Pure I/O, no interpretation. Watches the drop directory, resolves ticker →
`company_profiles`, writes `research_reports` per the Sprint 14 contract
([`research_layer_contract.md`](../../sprint_14/plans/dashboard_uplift/research_layer_contract.md)).
Idempotent on `(ticker, trade_date, source)`.

**Contract question now answered:** the agent emits a **markdown file tree on disk**
(`reports/<TICKER>_<YYYYMMDD_HHMMSS>/`), plus a `report.json` sidecar once Sprint 15 adds
it. It cannot write DuckDB and should not — single-writer discipline. Drop-file → ingest.

## [3] Comprehend — new orchestrator phase

`comprehend_reports`, ~phase 7.55 (after `scoring`, before `dashboard_db`). Reads new
`research_reports` → writes `research_signals`.

Given the `report.json` sidecar, most of this is **promotion, not extraction** — the
typed fields are already typed. LLM work is limited to what's genuinely unstructured.

Two additions beyond the Sprint 14 contract:
- **`forecasts` row per report** — rating + price target + horizon, so the existing
  Brier/cone machinery scores the agent's calls. Highest-leverage item: the scoring
  already exists.
- **`language` field** — so the briefing layer knows whether to translate.

**Name→ticker resolution lives here**, not in the agent. Filings name counterparties in
prose ("our largest customer, a major North American telecommunications provider") —
resolution is fuzzy, needs a confidence score and an unresolved bucket. An unresolved
counterparty is still valuable as a named node; do not drop it.

## [5] Discord briefing

`_discord_send` already exists ([`flows/daily_pipeline_flow.py:70`](../../../../flows/daily_pipeline_flow.py))
and is reusable. **But a 117KB report does not fit a Discord message** — the briefing is
generated from `research_signals` (rating, thesis line, top risk, watch items) with a
link to the full report. Never paste the report.

---

## Dependencies before any of this starts
1. Reports carry structured fields worth promoting (Sprint 15).
2. EDGAR section extraction proof-read and trusted (Sprint 15 gate).
3. Sector-order vs score-order settled.
4. `research_reports` table actually created — today it is a contract, not a table.
