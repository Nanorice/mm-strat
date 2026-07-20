# Industry study — the target state, and what the schema cannot yet express

> Sprint 15. **Design direction, not a build order.** Written 2026-07-20 against
> a worked example the user supplied: *The Shuffle Light — SpaceX 2万亿 IPO 能否
> 鸡犬升天* (25pp, 2026-05-06), a supply-chain study of SpaceX's pre-IPO
> ecosystem. Follows [`knowledge_base_schema.md`](knowledge_base_schema.md),
> which covers the per-company observation log this direction sits on top of.
>
> The format is not the target; the **content** is. What follows is an analysis
> of what that report does that our current extraction cannot, so the gaps are
> recorded before anything is built.

---

## 1. The goal, stated

Two deliverables, from the same substrate:

1. **A network** of relations *within and across* industries / sectors /
   subsectors — not one company's neighbours, but the topology of a segment.
2. **A per-segment report**: how the supply chain of (say) semiconductors
   actually works, who the major players are at each layer, and where the
   constraints sit.

Today `research_relations` holds 22 rows across 3 companies, each one a
disclosed pairwise relation from a single 10-K. The distance between that and
the reference report is not volume. It is **eleven structural gaps**, below.

---

## 2. What the reference report does that we cannot

### 2.1 Materiality is the whole thesis, and it points the wrong way

The report's opening argument: *being a supplier does not mean the stock moves.*

- **Linde** — $500M of announced capacity expansion specifically for SpaceX
  (liquid oxygen, nitrogen, argon), contracts and capital committed. Against
  $33B of revenue, SpaceX is <1%. The relation is real and the elasticity is nil.
- **Vicor** — $400M revenue, high-density DC-DC converters, a plausible fit for
  AI Sat Mini's megawatt-class power. Unconfirmed, and if it lands it is a large
  fraction of the company.

Our `Relation.pct_revenue` is *"percent of the **subject's** revenue this
relation represents"* — sourced from the subject's own 10-K, because Reg S-K
Item 101 forces the subject to disclose its customer concentration.

**The report needs the inverse: what share of the *counterparty's* revenue comes
from the subject.** That number lives in the *counterparty's* filing, not the
subject's. It is a different quantity from a different document, and no amount of
extracting harder from one 10-K produces it.

> **Implication.** Materiality is a **join across two companies' filings**, not a
> field. The knowledge base must be able to answer "how much of X's revenue is Y"
> by having ingested X, and that is only possible once coverage is broad enough
> that both ends of an edge are usually in the corpus. This is the strongest
> argument for prioritising *breadth of names* over depth per name.

### 2.2 The evidence axis and the impact axis are separate rankings

The report ranks on two dimensions and tiers on their product:

| Tier | Meaning | Example |
|---|---|---|
| high relation + high impact | contract evidence *and* material | Filtronic (SpaceX = 65–75% of revenue), STM, Innolux, Velo3D, Sphere |
| high relation + low impact | confirmed but diluted | SeAH (1–3%), Hexcel (3–8%), Linde, Wistron, Toray |
| potential + high-if-hit | unconfirmed, decisive if it lands | Redwire, Vicor, Mercury, RKLB/SolAero, Materion, Veeco |
| defence-cycle | different catalyst calendar | Karman, Kratos, L3Harris |
| short candidates | competed against or narrative-compressed | ASTS, Iridium, ViaSat, SATS post-IPO |

We have the first axis — `Evidence.strength` (`strong`/`medium`/`weak`/
`unverified`) plus our own `quote_verified`. **We have nothing on the second.**
A tiering like this is the actual output a reader wants, and it needs both.

### 2.3 One company is several counterparties

> *同一家公司的不同业务线要分开看* — "different business lines of one company
> must be looked at separately."

**Rocket Lab is simultaneously a competitor and a beneficiary.** Electron
competes with Falcon 9 directly — SpaceX winning hurts it. SolAero (GaAs
multi-junction cells) would be a supplier if AI Sat Mini picks GaAs. One ticker,
two edges, opposite signs. Netting them to a company-level edge destroys the
finding.

Our `Relation` is `company → company`. It must become **`segment → segment`**.
The producer already extracts `products` (the filing's own segment names) — they
are simply never linked to relations. Redwire is the same shape: ROSA is 15–25%
of revenue and is the real exposure; the Adcole star-tracker line is noise.

### 2.4 Conditional edges — the most decision-relevant kind

Much of the report's value is in edges that **do not exist yet**:

> "If AI Sat Mini selects GaAs, SolAero is a locked-in supplier. If it selects
> silicon or perovskite, SolAero's value is limited. There is no middle ground."
> (GaAs probability estimated ~30%.)

These are contingent on a future disclosure — the S-1, the routing decision. Our
schema records only what a filing has already stated. A knowledge base of
disclosed facts cannot hold "conditional on X, edge Y exists with probability p",
and that is where the alpha in this report lives.

### 2.5 Technology routes are nodes, not attributes

Silicon / GaAs / perovskite are **competing routes**, and the choice among them
determines which companies benefit. Same for centralised vs distributed satellite
compute — centralised favours rad-hard high-performance packaging (Mercury),
distributed favours rad-hard microcontrollers (Microchip).

This generalises the gap already recorded in
[`research_layer.md`](../../../modules/research_layer.md) §5:
`chain_position.upstream_dependencies` holds input *categories*
(`'rare earth minerals'`, `'CMOS foundry capacity'`), which are not counterparties
and which `research_relations` does not read. **A route/technology node is a third
node type** — neither a company nor a raw input, but a decision point that edges
hang off.

### 2.6 In-house capability is a negative edge, and it is a finding

> "SpaceX makes inter-satellite laser comms 100% in-house, 5000+ units in orbit,
> and plans to sell the technology. Therefore Mynaric, Coherent, Lumentum and
> IPG Photonics have **no** supply relation — and may be competed against in
> reverse."

Also: ~85% of rocket components are produced internally. Insourcing **is** the
structure of the chain — it decides which layers have an external market at all.
Our schema has no way to record "this layer is insourced, therefore no supplier
edge exists here," and absence-of-edge is currently indistinguishable from
absence-of-extraction.

### 2.7 Bottlenecks carry quantities

The report's MOCVD passage is the clearest example of chain reasoning:

> 100kW/satellite ÷ 30% GaAs efficiency ≈ 280 m² of cell per satellite. Even at
> 10,000 satellites (not the full million) that is 2.8M m², or ~930k m²/yr over
> three years — against global space-grade GaAs capacity of **under 100k m²/yr**.
> Closing that needs thousands of MOCVD reactors; Veeco's Compound Semiconductor
> segment did ~$60M in 2025.

Then it turns the constraint back on the thesis: the MOCVD gap is itself evidence
that **GaAs cannot serve the full-scale deployment**, so GaAs is likely confined
to early small batches. A capacity number propagates up the chain and revises a
probability.

Our `ChokePoint` is `description` + `constrains_subject` + evidence — prose only.
No capacity, no unit, no time horizon, nothing arithmetic can touch.

### 2.8 Explicit non-membership, with a reason

One Stop Systems is discussed at length **in order to exclude it**: OSS builds
ruggedised (temperature/vibration/shock) edge compute for ground and airborne
platforms; AI Sat Mini needs rad-hard (cosmic ray / high-energy particle)
survivability. Different engineering, no overlap.

**Recording why a plausible name is *not* in the chain is as valuable as
recording who is** — it is what stops the next reader re-deriving it. We have no
"considered and rejected, because…" concept anywhere.

### 2.9 Catalysts have a calendar, and it differs by edge type

> Short pre-IPO arbitrage funds: now → prospectus. Short direct competitors:
> prospectus → IPO+1mo. Long real supply-chain names: after Q3 earnings (that is
> when suppliers disclose SpaceX-related figures). Long defence names: Sept–Nov
> (congressional contract disclosure cycle).

And the standing observation that supply-chain stocks track **monthly launch
cadence**, not the IPO — SeAH fell 18.2% when cadence dropped from ~3/mo to 1/mo.
Each edge type has its own disclosure clock. Nothing in our schema carries a
"when would this be confirmed or refuted" field, though `WatchItem` is the
nearest existing hook.

### 2.10 The most levered names are usually not US-listed

Filtronic (FTC.L), Innolux (3481.TW), SeAH (058650.KS), Sphere (347700.KQ),
Wistron (3231.TW), Shenmao (3305.TW), Aixtron (Frankfurt), TSEC (Taiwan), plus
private Singfilm Solar.

Our universe is US equities and `cik_map` is SEC-only. **A graph that resolves
`dst_ticker` against US listings alone is systematically biased toward exactly the
diluted mega-caps the report tells you to ignore**, and drops the small foreign
names where the elasticity is. Non-resolvable and foreign-listed nodes must be
first-class, not dropped.

### 2.11 The centre of the study need not be listed at all

SpaceX files no 10-K. Every fact in the report is assembled from *counterparties'*
filings, contract announcements, regulatory filings (the FCC application for 1M AI
Sat Mini satellites), trade press, and appropriations bills.

Our extraction is 10-K-driven from a **listed subject**. Centring a study on
SpaceX, or on "the GaAs solar cell segment", inverts the direction of ingestion:
the node of interest is assembled from the edges pointing at it. A related case is
the **ownership** edge — EchoStar holds ~$11B of SpaceX stock, making SATS a
proxy rather than a supplier; that is a fourth relation kind we do not model.

---

## 3. What this implies for the build order

Nothing here changes the near-term plan; it changes what the near-term plan is
*for*. Read against [`knowledge_base_schema.md`](knowledge_base_schema.md):

1. **Breadth beats depth.** §2.1 makes counterparty-side materiality a join, and
   a join needs both ends ingested. Coverage of many names is worth more than
   more runs of few names — after the corroboration harness has established that
   extraction is stable at all.
2. **`supply_chain_edges` should be segment-grained from the start** (§2.3), or
   it will need a migration the first time a Rocket Lab appears. The producer
   already emits `products`; the link is the missing piece.
3. **Node type belongs in the schema now** (§2.5, §2.10, §2.11): `listed` /
   `private` / `government` / `aggregate` is already drafted — add `input`,
   `technology_route`, and treat foreign listings as resolved-but-not-US rather
   than unresolved.
4. **Absence needs a representation** (§2.6, §2.8). Insourced layers and
   reasoned exclusions are findings. Probably a separate table; certainly not a
   missing row.
5. **Conditional edges are a later layer, not a schema patch** (§2.4). They are
   derived from analysis over disclosed facts, not extracted from a filing.
   Keeping them out of `research_relations` preserves that table's meaning: *what
   a filing said*.
6. **A segment report is a different artifact from a company report.** The
   producer writes one report per ticker. A per-segment study is a fan-in over
   many tickers plus non-filing sources — a different agent with a different
   input contract, not a bigger `BusinessProfile`.

**Deliberately unresolved:** where the non-filing evidence (contract
announcements, FCC filings, trade press, appropriations) enters, and how it is
verified. `quote_verified` works because SEC filings are immutable and cached. A
news article is neither. The reference report's strongest claims — Filtronic's
£47.3M exclusive contract, Innolux's FOPLP order — rest on exactly that kind of
source. **Extending the corpus past EDGAR means the verification gate needs a
second design, and that is the hard problem this direction contains.**
