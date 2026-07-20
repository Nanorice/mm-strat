# Sprint 15 — Research Layer & Knowledge Base

**Dates:** 2026-07-20 → TBD · **Status:** 📋 Planned · **Prev:** [sprint_14](../sprint_14/README.md)

> Sprint 14 built the *screening* half of the funnel and planned the dashboard that reads it.
> Sprint 15 builds the **research** half: make the external TradingAgents layer produce reports
> worth digesting, then digest them into a sector-partitioned knowledge base.

### The pipeline this sprint serves

```
daily pipeline → shortlist (top N by score × mcap) → TradingAgents reports
    → agentic digestion → knowledge base (sector chain maps + edges)
    → Discord briefing + saved reports → human review → decision
```

**Sprint 15 scope is step 3 only** — tune the report generator. Steps 2, 4, 5 are
documented so they aren't lost, but are explicitly *not* this sprint's work.

### Why step 3 first

The digestion layer's ceiling is set by report quality, and today's reports are
**generic by construction**: the fundamentals analyst's entire input is ~20 yfinance
ratios plus three numeric statement tables. It has never read a sentence the company
wrote about itself. No amount of downstream parsing recovers business facts that were
never in the input. Fix the source before building the consumer.

### Folder map
- **`plans/`** — planning docs (this sprint is plan-heavy by design).
- **`logs/`** — dated session handovers (`YYYY-MM-DD_NN_<slug>.md`).
- **`verdicts/`** — findings / reports (one per question).
- **`cells/`** — notebook-cell artifacts (`*_cells.md`).

### Plans
| Doc | Status | What |
|---|---|---|
| [`tradingagents_business_analyst.md`](plans/tradingagents_business_analyst.md) | 🔄 active | New `business_analyst` node + EDGAR text dataflow + `BusinessProfile` schema. **This sprint.** |
| [`agentic_digestion_layer.md`](plans/agentic_digestion_layer.md) | 🅿️ parked | Shortlist selector, ingest engine, `comprehend_reports` phase, sector chain maps, Discord briefing, forecast ledger. **Not this sprint** — recorded so it isn't lost. |

### Carried in from Sprint 14
- [`dashboard_uplift/research_layer_contract.md`](../sprint_14/plans/dashboard_uplift/research_layer_contract.md)
  — the `research_reports` table contract. Its open question ("what does the agent emit?")
  is **ANSWERED** in the business-analyst plan: markdown file tree on disk, no DB writes.
- [`dashboard_uplift/supply_chain_page.md`](../sprint_14/plans/dashboard_uplift/supply_chain_page.md)
  — the edge-sourcing blocker. Sprint 15 picks **Tier 1 (build)**, via the agent layer
  rather than a standalone engine. See the business-analyst plan for why.
- [`dashboard_uplift/equity_research_page.md`](../sprint_14/plans/dashboard_uplift/equity_research_page.md)
  — the read surface. Unblocked once reports land in a table.

### Open decisions
1. **10-K text extraction quality** — the make-or-break risk. Item-1 boundary detection on
   raw EDGAR HTML is where this quietly produces garbage. Gated by the cache + proof-read
   loop (see plan).
2. **Sector-ordered vs score-ordered shortlist** — a sector chain map completes only if
   names arrive sector-clustered; pure top-by-score scatters them. Flagged, not settled.
