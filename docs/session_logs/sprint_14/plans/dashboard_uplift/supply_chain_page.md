# Supply-Chain Page (`/supply-chain`) — Design & Data-Bridge Plan

> Sprint 14, dashboard uplift. Planning doc only (no implementation).
> **The hardest page: we have nodes, zero edges.** The design is settled; the
> plan is dominated by *sourcing the edge data*, not rendering it.
> Original spec preserved at the bottom under "Appendix: raw spec".

---

## What it is

A **market dependency map** — the thesis that "the market is not a list of
sectors, it is a dependency system." Customer→supplier relationships extracted
from 10-K filings, rendered as an interactive **chord diagram**: whole-market
view (cross-sector capital flow across GICS sectors) + per-company ego view
(one name's up/down-stream). The alpha thesis: supply-chain transmission is an
overlooked edge — a chip fab's capacity change propagates up/down-stream to
names you aren't watching.

---

## Data reality check — THE defining constraint

Verified against `market_data.duckdb`, 2026-07-16:

- **Edge tables: NONE.** No `supply_chain`, `relation`, `edge`, `customer`,
  `supplier`, `peer`, `segment`, `network` table anywhere.
- **Edge columns: NONE.** No `customer`/`supplier`/`segment`/`geography` column
  in any of the 49 tables.
- **Nodes: strong.** `company_profiles` — 3,941 active non-ETF tickers with
  `sector` (native Yahoo, 11 real) + `industry` (149), `market_cap`.
- **EDGAR engines hit the WRONG surface for edges.** `edgar_engine` and
  `fundamental_edgar_engine` query the **structured XBRL / `companyfacts` API**
  (`data.sec.gov/api/xbrl/...`). That API is financial line-items only —
  **it does not contain customer/supplier relationships.** Those live in
  **10-K free text** (Item 1 "significant customers", Item 1A risk factors,
  MD&A concentration notes) — a full-text extraction problem the current
  engines don't touch.

**Consequence.** This is **not a dashboard task and not a one-session task.** The
render (chord diagram) is ~1–2 days of d3. The *edges* are a multi-week
extraction project. The page's entire value == the edge data. **Do not build the
real page until edges exist.** Ship a labelled mock first (below) to lock the
format, then treat edges as a standalone research thread.

---

## Design (settled — matches theta, style per `style.md`)

**Composition**
- Centered serif headline *"The market is not a list of sectors."* + subline
  *"It is a dependency system."*
- Row of sub-chain pill links above the graph: HBM, DDR, NAND, Storage,
  Packaging, AI Compute, AI Net, Power → `/supply-chain/<chain>` (stubbed).
- **SVG chord diagram** (~720px), subtle 60px cream grid backdrop (CSS).
- Meta line (mono): `N companies · N edges · $NNT · 11 sectors`.
- Floating hint: *"Click a sector to explore — Try Information Technology."*
- Mobile: "Best viewed on desktop" + static preview + force-render button.

**Render** (d3, no animation lib)
- `d3.chord().padAngle(0.02).sortSubgroups(descending)` on an 11×11 sector matrix.
- Inner arc ring (`innerR=270,outerR=290`) per sector, sector-colored.
- Outer sub-chain ring (`innerR=298,outerR=316`) over the IT arc for HBM/DDR/…
- Ribbons `d3.ribbon().radius(268)`, source-sector color @ ~0.35 opacity.
- Mono arc labels ("Name" + "N cos"), auto-flipped past π; ochre uppercase
  sub-chain labels.

**Interaction**
- Hover sector arc → its ribbons full-opacity, others →0.06, other arcs →0.35;
  tooltip: sector · companies · total dependency weight.
- Hover ribbon → that ribbon @0.85, both endpoint arcs lit; tooltip
  `Source → Target · weight`.
- Click sector → `/supply-chain/<sector>` (stub); click sub-chain → chain-lane stub.
- Keyboard: arcs `tabIndex=0`, Enter=click, focus ring `--ring`.
- CSS `transition: opacity 180ms`; `viewBox` + `ResizeObserver` for resize.

**Ego view (per-company)** — theta's individual lens. One node centered, its
suppliers on one side, customers on the other, edge weight = revenue
concentration. Deferred to after market-level edges exist.

---

## The edge-data problem — options, cheapest → hardest

Ranked by cost. Each yields a `supply_chain_edges` table:
`(src_ticker, dst_ticker, weight, direction, source_type, as_of, confidence)`.
Sector matrix for the chord = aggregate edges up to `company_profiles.sector`.

### Tier 0 — Correlation proxy (SHIP THE MOCK ON THIS)
- **What:** sector×sector return-correlation matrix from `price_data` (rolling
  252d). Renders the chord **today**, zero sourcing.
- **Honest caveat (house style):** this is **co-movement, not dependency** —
  correlation ≠ a supply relationship. Caption must say so. Good enough to lock
  the *format* and answer the platform question; **not** the real product.

### Tier 1 — EDGAR 10-K "significant customers" extraction (the real MVP)
- **Source:** SEC 10-K full text. Reg S-K Item 101 requires disclosing any
  customer ≥10% of revenue. Names are in Item 1 / MD&A / segment notes.
- **How:** EDGAR full-text search API (`efts.sec.gov/LATEST/search-index`) +
  the filing document endpoint (`data.sec.gov/.../<accession>.txt`). Your
  `cik_map` already resolves ticker↔CIK. Parse "significant customers" / "10% of
  net revenue" passages → named customer → resolve back to a ticker.
- **Edge yield:** directional (supplier discloses customer), weighted (the % if
  stated). Sparse — only ≥10% concentrations are mandated — but **real** and
  high-signal (exactly the alpha thesis). Realistically a few hundred edges
  across S&P 500, matching theta's "~649 edges."
- **Cost:** the actual project. Full-text fetch + NER/name-resolution +
  ticker-matching + a QA pass. Multi-week. This is a **new engine**
  (`supply_chain_engine.py`), not a dashboard change.

### Tier 2 — Vendor edge feed (buy instead of build)
- FactSet Revere / Bloomberg SPLC / S&P Capital IQ supply-chain relationships —
  clean directional edges with revenue exposure. **Paid.** If budget exists this
  collapses Tier 1's weeks into an import job. Evaluate cost vs. the extraction
  effort before committing to Tier 1.

### Tier 3 — LLM-assisted extraction (augment Tier 1)
- Feed 10-K Item 1 / MD&A chunks to an LLM to extract
  `{supplier, customer, %rev, product}` triples with a confidence score. Higher
  recall than regex (catches unnamed-threshold prose), needs a verification gate
  (hallucinated tickers). Layer on Tier 1 once the plumbing exists; **not** a
  cold start.

---

## Sub-chains (HBM/DDR/NAND/…)

The named lanes (AI Compute, Power, Packaging…) are **thematic groupings**, not
GICS — a hand-authored mapping of tickers → chain, curated once
(`supply_chain_lanes` table or a static config). Independent of the edge
extraction; can be authored anytime. These drive the outer ring + pill links.

---

## Build order (recommendation)

1. **Mock now (Tier 0 render + fake matrix).** Standalone HTML/d3 chord, like
   `macro_page_mock.html`. Locks the format + answers "does this justify a real
   front-end?" (chord + hover-dimming is the clearest yes-case for leaving
   Streamlit). **All the design above is testable with zero edge data.**
2. **Author the sub-chain lane map** (static, cheap, independent).
3. **Decide edges: build (Tier 1) vs buy (Tier 2).** This is a budget/time call
   for the user — flag it, don't assume. If build: stand up
   `supply_chain_engine.py` as a *separate research thread*, not inside this page.
4. **Real page** only after `supply_chain_edges` is populated + QA'd. Ego view
   after that.

**Platform note:** this page (chord, network, hover-dimming, ego graph) is the
strongest case in the whole uplift for a real front-end over Streamlit — but it's
also the **last** to have data. Sequence accordingly: it validates the platform
direction but must not gate it.

---

## Appendix: raw spec (original)

```
Supply Chain (/supply-chain) — new. 美股供应链图谱 578 节点/3000 依赖关系；
从 10-K 提取标普 500 客户-供应商关系 → 可交互网络图；全景(11 GICS 跨板块资金流)
+ 个体 ego view。供应链传导 = 被忽略的 alpha 来源。
Format: d3-chord/d3-shape/d3-scale SVG chord (~720px), grid backdrop.
Headline "The market is not a list of sectors." / "It is a dependency system."
Pills: HBM DDR NAND Storage Packaging AI-Compute AI-Net Power → /supply-chain/$chain.
Meta: "514 companies · 649 edges · $68.4T · 11 sectors". Hint card. Mobile fallback.
Data(mock): 11 sectors {id,label,companies,color}; symmetric 11×11 matrix
  (IT/Comm/Industrials heaviest); sub-chain arcs {id,label,parentSector,arcSpan}.
Render: chord padAngle .02 sortSubgroups desc; arc ring 270/290; sub-chain ring
  298/316; ribbon radius 268 @.35; mono arc labels flip past π; ochre sub labels.
Interaction: hover arc dims others to .06/.35 + tooltip; hover ribbon .85 +
  src→tgt tooltip; click sector→/supply-chain/$sector stub; click chain→chain-lane
  stub; tabIndex 0 Enter=click; opacity 180ms; viewBox + ResizeObserver.
Stubs: supply-chain.$sector.tsx; supply-chain.design-lab.chain-lane.tsx (Zod ?chain=).
Components: desk/* (AppSidebar, DecisionCard, RangeBar, RegimeBanner, FilterChips);
  supply-chain/* (ChordGraph, ChainPills, MobileFallback, SectorTooltip);
  landing/*; SiteHeader in __root.tsx.
```
