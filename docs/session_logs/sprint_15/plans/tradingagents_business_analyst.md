# TradingAgents: `business_analyst` node — Design Plan

> Sprint 15. Planning doc. The work lands in the **TradingAgents repo**
> (`C:\Users\sh019\Documents\projects\TradingAgents`), not mm-strat.
> Verified against both repos 2026-07-19.

---

## The problem, precisely

The current report is generic because the fundamentals analyst has **no prose input**.

Verified ([`fundamentals_analyst.py:18-23`](../../../../../TradingAgents/tradingagents/agents/analysts/fundamentals_analyst.py)):
its four tools are `get_fundamentals`, `get_balance_sheet`, `get_cashflow`,
`get_income_statement`. `get_fundamentals` is a yfinance `.info` call returning ~20
scalar ratios (PE, PEG, beta, 52w high, market cap…); the other three return numeric
statement tables.

**The model has never seen a sentence the company wrote about itself.** It infers a
business narrative from ratios, which produces confident, plausible, unspecific prose.
Confirmed empirically: the RKLB report (`reports/RKLB_20260714_142349/`) contains
**zero** occurrences of supplier / customer / concentration / upstream / downstream.

There is **no EDGAR tooling anywhere** in `tradingagents/dataflows/` (all 16 modules
checked). This node is the first thing in the system that would read filing text.

### Answering the user's question directly
> *"is this node now reading the financial statement word by word?"*

**No.** It reads a summary ratio table, not documents. The `business_analyst` node is
what introduces word-by-word reading — and only of *narrative* sections (Item 1, 1A,
MD&A), never the numeric statements, which stay with the fundamentals node where the
structured yfinance data is better than parsing tables out of HTML.

---

## Scope decision: new node, not a bigger fundamentals prompt

| | fundamentals_analyst | **business_analyst** (new) |
|---|---|---|
| Input | yfinance numerics | 10-K narrative text |
| Output | financial condition | business model + chain position |
| Failure mode | stale/missing ratios | mis-sliced document sections |
| Cadence | every run | filing-cached, refreshes annually |

Different data, different failure modes, different refresh cadence → different node.
Merging them would create exactly the God-Class coupling CLAUDE.md's First Principles
warn against, and would re-fetch a 10-K on every run to answer questions whose answers
change once a year.

---

## Source-skill assessment (user asked about two repos)

### `agi-now/buffett-skills` — **borrow concepts, do not import**
- **Not pluggable.** It's a Claude Code skill (YAML frontmatter + progressive-disclosure
  `references/`). TradingAgents is LangGraph on OpenRouter/deepseek — no skill runtime.
  "Plugging in" = pasting prose into `system_message`.
- **Wrong output shape.** Its mandatory template opens with
  `## Conclusion [Buy/Don't Buy/Hold/Sell]` — a *decision*. The analyst nodes are *inputs*
  to a bull/bear debate → research manager → trader → risk → PM chain. Worse, the analyst
  prompt already instructs prefixing `FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL**`
  *"so the team knows to stop"* — a Buffett-style conclusion could **halt the graph at the
  first node**.
- **Unsourceable metrics.** Demands 10-yr average ROIC, owner earnings (needs a
  maintenance-capex split), cash-conversion. yfinance gives ~4y of annuals and no
  maintenance-capex breakout → the model emits numbers it cannot compute. A hallucination
  generator upstream of a knowledge base.
- **No LICENSE file** in the repo → default all-rights-reserved. Do not lift its text.
- **Genuinely useful:** the 5-moat taxonomy and — the good bit — judging moat **trend**
  (widening/stable/narrowing), not just level. These are standard value-investing canon;
  express them in our own words.

### `muxuuu/serenity-skill` — **much closer fit, MIT-licensed**
Purpose-built for supply-chain bottleneck research. Directly supplies the dimensions
buffett-skills lacks:
- **Chain layer decomposition**: downstream demand → system integrators → modules →
  chips/devices → process & packaging → equipment & testing → materials & consumables →
  infrastructure.
- **Bottleneck criteria**: supplier concentration, qualification/certification timelines,
  expansion difficulty & capital intensity, know-how, material purity, equipment
  specificity, customer lock-in, lead times.
- **Pricing power** framed as *proximity to the scarce layer* — which is exactly the
  user's "how strong is it in the supply chain."
- **Evidence-strength rating** (strong/medium/weak/unverified) + a named primary source
  per claim. Adopt this verbatim in spirit: it is the single best defence against a
  knowledge base of confident fiction.
- MIT license → its framework text may be adapted with attribution.

**Verdict:** skip buffett-skills as a dependency; take its moat-trend idea. Base the
node's chain reasoning on serenity's layer/bottleneck framework, attributed.

---

## Output contract: `BusinessProfile`

New Pydantic schema in `tradingagents/agents/schemas.py`, consumed via the existing
`bind_structured` / `invoke_structured_or_freetext` helpers (already proven on
`PortfolioDecision`). Every field carries evidence.

```
BusinessProfile
├── what_it_is: str                  # one paragraph, plain language
├── revenue_model: str               # how money is actually made
├── products: list[Product]          # name, % revenue if disclosed, description
├── customers: list[Customer]        # name, % revenue, is_disclosed_concentration
├── cost_structure: str              # main cost drivers, fixed/variable shape
├── moat: Moat                       # type(s), strength, TREND (widening/stable/narrowing)
├── chain_position: ChainPosition    # layer (serenity taxonomy), upstream/downstream deps
├── pricing_power: PricingPower      # rating + proximity-to-scarce-layer rationale
├── choke_points: list[ChokePoint]   # what constrains it / what it constrains
├── growth_expectation: str          # drivers + management guidance, explicitly sourced
├── key_risks: list[Risk]            # max 3, ranked
├── watch_items: list[WatchItem]     # named catalysts + expected timing
└── relations: list[Relation]        # counterparty, direction, %rev, confidence
```

Every leaf object carries `evidence: str` (the quoted passage) + `source: str`
(accession + section) + `strength: Literal["strong","medium","weak","unverified"]`.
**A field with no evidence must be emitted as null, not guessed.** This is the schema's
main job.

### `watch_items` — the RKLB test
The user's example: *"Neutron rocket test for RKLB."* This is the field that makes a
report worth reading. It must produce **named, dated, checkable** events (a specific
first-flight, a certification decision, a contract award), not "monitor execution."
Use it as the acceptance test: if a run's `watch_items` for RKLB don't name Neutron,
the node has failed regardless of what else it produced.

### `relations` — the supply-chain edge payload
Reg S-K Item 101 mandates disclosing any customer ≥10% of revenue. That disclosure is
the **only** systematically available edge source, and it lives in the text this node
now reads. Each `Relation` is one row toward `supply_chain_edges`
(`src_ticker, dst_ticker, weight, direction, source_type, as_of, confidence`) as specced
in [`supply_chain_page.md`](../../sprint_14/plans/dashboard_uplift/supply_chain_page.md).

⚠️ **Counterparty names are not tickers.** Name→ticker resolution is a separate,
error-prone step and belongs in the **digestion layer**, not here. This node emits the
name as disclosed. Do not resolve tickers inside the agent.

---

## The EDGAR dataflow + cache

New `tradingagents/dataflows/edgar_filings.py`. This is the actual engineering.

**Fetch:** EDGAR submissions API → latest 10-K accession → filing document.
Filings are **HTML/txt, not PDF** — no PDF path needed for 10-Ks. If a source ever *is*
a PDF, cache it byte-identical and mark the section slices as unavailable.

**Cache layout** (under `config["data_cache_dir"]`) — user requirement, and the gate on
extraction quality:

```
edgar/<TICKER>/<accession>/
├── raw.htm          # byte-identical as fetched — the proof-reading anchor
├── meta.json        # cik, accession, form, filing_date, period, fetched_at, url
├── item1.md         # cleaned: Business
├── item1a.md        # cleaned: Risk Factors
├── item7.md         # cleaned: MD&A
└── extract_log.json # section offsets, boundary regex that matched, char counts
```

**Why this shape:**
- `raw.htm` kept as-is → any cleaning bug is diagnosable after the fact without refetching.
- Cleaned `.md` per section → proof-read the *actual* model input, not a reconstruction.
- `extract_log.json` → makes silent slicing failure **visible**. A 200-char `item1.md`
  for a mega-cap is an obvious red flag; without the log you'd never look.
- Keyed by accession, not date → immutable, so a re-run is free and reproducible.

**The real risk: section boundary detection.** 10-K HTML is wildly inconsistent — item
headers appear in TOCs before the real section, in tables, with varied casing and
non-breaking spaces. Naive `"Item 1."` matching grabs the table of contents and yields
two paragraphs. Mitigations:
- Match the **last** plausible occurrence, not the first (skips the TOC).
- Assert extracted length is within a sane band; log loudly outside it.
- **Manual proof-read of the first ~10 tickers before any batch run** — non-negotiable.
  This is the step that determines whether the knowledge base is real.

---

## Supporting changes (small, high leverage)

1. **`report.json` sidecar.** `write_report_tree()` currently renders typed Pydantic
   objects to markdown and discards the objects — `render_pm_decision()` flattens
   `PortfolioDecision` (rating, price_target, time_horizon) into prose that the digestion
   layer would have to LLM-re-parse. Emit the model dumps alongside the markdown.
   ~30 lines; removes the digestion layer's main failure mode before it's written.
2. **Run manifest.** `run_id`, `trade_date` (the folder stamp is wall-clock, and the
   `research_reports` contract PKs on trade date), model IDs, token cost, and a
   **price snapshot as-of the report** — required later to score the call.
3. **`TRADINGAGENTS_OUTPUT_LANGUAGE=English`** in `.env`. Default is already English
   ([`default_config.py:108`](../../../../../TradingAgents/tradingagents/default_config.py));
   the local `.env` is overriding it, which is why the RKLB report is entirely Chinese.
4. **Handle structured-output fallback.** `invoke_structured_or_freetext` silently
   degrades to free text on any failure. "JSON absent" is a normal case downstream, not a bug.

---

## Integration points (verified 2026-07-19 — do not re-derive)

A new dataflow is **not** just a new module; it registers in three places:

1. **`dataflows/interface.py`** → `TOOLS_CATEGORIES` — add a `filings` category listing
   the new tool methods. `get_category_for_method()` raises if a method isn't in a category.
2. **`dataflows/interface.py`** → `VENDOR_METHODS` — `{method: {vendor: impl}}`, e.g.
   `"get_10k_sections": {"sec": get_10k_sections}`. `route_to_vendor()` raises on unknown methods.
3. **`default_config.py`** → `data_vendors` dict — add `"filings": "sec"`.

Then the agent-facing tool is a thin `@tool` wrapper in
`agents/utils/` (pattern: `fundamental_data_tools.py`, ~15 lines/tool) that calls
`route_to_vendor("get_10k_sections", ...)`.

Other facts already established:
- Cache root is `config["data_cache_dir"]` (`default_config.py:74`,
  env `TRADINGAGENTS_CACHE_DIR`). `stockstats_utils.py:150` is the existing
  `os.makedirs(..., exist_ok=True)` precedent.
- `dataflows/utils.py` has **no** caching helper — only `safe_ticker_component`
  (use it for path components), `save_output`, `get_current_date`. The filing cache
  is new code.
- `dataflows/errors.py` defines `NoMarketDataError` / `VendorRateLimitError`;
  `route_to_vendor` treats them specially. Reuse rather than inventing exceptions.
- **SEC requires a declared User-Agent** with contact info, and rate-limits to
  ~10 req/s. Set it explicitly or requests get blocked.

## Build order

1. `edgar_filings.py` + cache + **manual proof-read of ~10 tickers.** Gate: do not
   proceed until section slicing is trustworthy.
2. `BusinessProfile` schema + `render_business_profile()`.
3. `business_analyst` node; register in `graph/setup.py` + `conditional_logic.py`;
   add `business_report` to `agent_states.py` and to `write_report_tree`.
4. `report.json` sidecar + manifest.
5. Re-run RKLB. **Acceptance:** named customers (or an honest null), a chain-layer
   placement with evidence, and `watch_items` naming Neutron.

## Open questions
- **Which node consumes `business_report`?** Bull/bear both should. Check the debate
  prompts pick it up rather than silently ignoring a new state key.
- **Token cost.** Item 1 + 1A + MD&A is often 100k+ characters. Needs section truncation
  or a map-reduce summarize step, or a single run gets expensive. Measure before batching.
- **Non-10-K filers.** ADRs file 20-F, some names file 40-F. Out of scope for v1 — fail
  loudly with "no 10-K available", never silently produce an empty profile.
