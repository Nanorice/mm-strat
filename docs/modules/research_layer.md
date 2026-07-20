# Module: Research layer (`src/research_*.py`) — report ingestion & comprehension

> Verified against code 2026-07-20. Ingests the producer's report trees into
> DuckDB, scores the quotes they rest on, and logs the relations they claim.
> **No LLM and no network in this layer** — see §2, it is the most-asked question
> about it.

Pipeline position:

```
producer (fork; LLM lives here)  →  drop dir  →  research_report_engine   →  research_reports
                                                                             research_report_runs
                                                        ↓
                                            research_comprehension        →  research_relations
                                              (uses research_quote_fidelity)
                                                        ↓
                                            supply_chain_edges               NOT BUILT (§7)
```

---

## 1. The producer boundary

The upstream is **the producer** — the TradingAgents fork at
`github.com/Nanorice/TradingAgents`, branch `mm-strat-report`. Never call it
"TradingAgents" in prose; that name points at a repo containing none of this
work. See [`producer_deployment.md`](../architecture/producer_deployment.md).

It writes one directory per run:

```
<reports>/<TICKER>_<wallclock_stamp>/
  complete_report.md     → raw_md, the source of truth
  report.json            → typed agent output   (optional; null per agent = fell back)
  manifest.json          → run identity, trade_date, degraded_agents   (REQUIRED)
  1_analysts/ 2_research/ 3_trading/ 4_risk/ 5_portfolio/   → per-agent .md, NOT ingested (§6)
```

**`report_date` comes from `manifest.trade_date`, never the folder stamp.**
Backfilling a week of history in one evening makes those disagree on every row
and collapses the PK onto a single day.

---

## 2. Why there is no LLM here

The LLM ran upstream, in the producer: `openrouter`, `deepseek/deepseek-v4-pro`
(deep) + `deepseek/deepseek-v4-flash` (quick), ~19 calls / ~$0.09 / ~238k tokens
per run. It emitted **typed Pydantic objects**, already validated, into
`report.json`.

Running a second LLM over that output would re-derive fields that are already
structured, and would add a failure mode (a paraphrase, a dropped field) to data
that currently cannot acquire one. Ingestion is a JSON read because the thinking
is finished before mm-strat sees anything.

**Where an LLM genuinely belongs, and is not yet built:** resolving a disclosed
counterparty name to a ticker (`"Space Development Agency"` / `"SDA"` /
`"Prysmian Group S.p.A."` — fuzzy, no clean rule), and recovering structure from
a free-text fallback run. Both are *resolution* problems on unstructured input,
which is a different job from ingesting typed input.

---

## 3. `research_report_engine.py` — ingestion

Two tables, no interpretation.

| Table | Grain | PK |
|---|---|---|
| `research_reports` | canonical record per name per trade date | `(ticker, report_date, source)` |
| `research_report_runs` | every run that landed | `run_id` |

A same-day re-run **replaces** the parent and **keeps both children** — two runs
of one name on one trade date are a re-run, not two opinions, but the
corroboration step needs the non-canonical runs kept. `source` is always
`'tradingagent'`.

### Version gates — two namespaces, deliberately separate

- `ENVELOPE_SCHEMA_VERSION` (`'1.0'`) — the sidecar wrapper shape.
- `PAYLOAD_SCHEMA_VERSIONS` — per-agent model shape. **Inert**: the producer does
  not emit `agent_schema_versions` yet.

A renamed `BusinessProfile` field changes meaning without touching the wrapper,
so one number cannot speak for both. **Comparison is major-only** — the producer's
`SIDECAR_SCHEMA_VERSION` moved 1.0 → 1.1 (adding `degraded_agents`) with no
change here. Absent → baseline `1.0`; a major mismatch raises
`SchemaVersionError`, which is a **refusal, not a skip**.

### DQ rules at ingest

| Condition | Behaviour |
|---|---|
| no `manifest.json` | skip, warn (`NVDA_20260714_135243` is the standing example) |
| no `complete_report.md` | skip, warn — `raw_md` is the source of truth |
| missing `ticker`/`trade_date` | skip, warn |
| major schema-version mismatch | **raise** |
| `run_id` already in `research_report_runs` | no-op |

Re-running `ingest_drop_dir()` over the same tree returns `(0, n)`. Safe to
schedule — though no orchestrator phase calls it (§7).

### Known bug (open)

`parse_run_dir` maps `thesis = research_manager.recommendation`, a
`PortfolioRating` enum, so `thesis == conviction` on every row
("Underweight"/"Underweight"). The intended field is
`portfolio_manager.investment_thesis`, a free-text string. One line at
`research_report_engine.py:220` — **but fixing it does not backfill**, because
`run_id` dedup skips already-ingested runs.

---

## 4. `research_quote_fidelity.py` — the % number

**Quote fidelity** = of the N evidence quotes in a profile, how many appear
verbatim in the cached 10-K after normalization. Pure string containment. No
model judges it; no network.

Verification runs against the **sliced** section text
(`~/.tradingagents/cache/edgar/<TICKER>/<accession>/item{1,1a,7}.md`), not
`raw.htm`. Verdicts are therefore not reproducible across a re-slice — **persist
them, do not recompute on demand** (§5).

`normalize()` folds what carries no claim: case, every quote glyph to one,
dashes, and **all whitespace and list glyphs**. Three false negatives drove that
list, each of which made a clean run look fabricated:

| Bug | Cost | Cause |
|---|---|---|
| trailing full stop | 8.7pp | model ends a quote with a `.` the source lacks |
| quote-style swap | 35.7pp | filing `("Marvell," "MTI,")` vs model `('Marvell,' 'MTI,')` — both already straight, so curly→straight folding did nothing |
| lost block boundary | 6.5pp | sliced text reads `core rate.To offset` (no space at a paragraph break) and `including: •The loss` (bullet glued to its item) |

**A sub-100% score is diagnosed, not reported.** Bisect the longest matching
prefix of the failing quote against the filing; the divergence point names the
cause in one step. Then: a **layout** difference there is the checker's bug, a
**different continuation** is the model's.

Two flags are correct and deliberately kept:

- **GLW `watch_items[0]`** — the filing reads *"...growth opportunities through
  2026 and beyond. We therefore expect to increase both our capacity ... to
  achieve our goals, while sharing risk appropriately..."*; the model wrote
  *"...to achieve our goals, through 2026 and beyond."* Every word is in the
  filing; the sentence is not. A clause grafted between two sentences — the first
  true positive this checker produced, and proof the layout folding is not a
  loosening.
- **MRVL `cost_structure`** — `cost of goods sold 49.0 [for fiscal 2026]`. The
  figure is real; the bracket is the model's own gloss picking between two table
  columns. Stripping brackets would bless an inference wearing a quote's clothing.

The negative controls in `tests/test_research_quote_fidelity.py` are the point:
normalize too hard and everything passes, at which point the number is decoration.

---

## 5. `research_comprehension.py` — the observation log

`research_relations`, per
[`knowledge_base_schema.md`](../session_logs/sprint_15/plans/knowledge_base_schema.md)
§2.1. One row per relation per run, append-only, PK `(run_id, rel_idx)`. **This is
where `quote_verified` is persisted** — before it existed the checker computed the
verdict and discarded it, so the gate only ran when a human called it.

- **Idempotent by inheritance.** A `run_id` already in the table is skipped, so
  re-running over the whole history writes nothing. A run whose agent fell back
  to free text has no rows to key on and is re-read each time (one JSON parse).
- **`force=True` re-scores.** The one legitimate reason is a checker change —
  two happened on 2026-07-20, each altering verdicts that would otherwise stay
  wrong forever.
- **`quote_verified` is NULL, not False, when the filing is not cached.** A box
  without the EDGAR cache would otherwise report every quote as fabricated:
  "could not check" and "checked and failed" are different facts.
- **`strength` (agent's self-assessment) and `quote_verified` (our verdict) stay
  separate columns.** Collapsing them into one "confidence" destroys the only
  question worth asking — does the agent's confidence track reality?
- **`counterparty_key`** is the future dedup key: lowercase, punctuation to
  spaces, legal suffixes stripped (`Inc/Corp/Ltd/plc/GmbH/S.p.A.`…), whitespace
  collapsed. Punctuation must go **first** or `S.p.A.` never matches. An aggregate
  gets a synthetic key (`__top5_customers__`) so "top five customers = 49% of
  revenue" survives as a node instead of being dropped by a NULL.

### Relation directions

Four, all named from the **counterparty's** role relative to the subject company:

| `direction` | Means | Subject is the… |
|---|---|---|
| `customer` | the counterparty **buys from** the subject | seller |
| `supplier` | the counterparty **sells to** the subject | consumer |
| `partner` | joint venture, acquisition, collaboration | — |
| `competitor` | rival named in the filing | — |

⚠️ **`supplier` is read from the counterparty's side.** A row reading
`direction='supplier'` does **not** mean the subject is a supplier; it means the
subject consumes from that party. There is no separate "consumer" direction —
`supplier` *is* it.

Observed distribution (2026-07-20, n=3): GLW 9 competitor · MRVL 4 customer /
2 partner · RKLB 7 customer. **Zero suppliers across all three**, and it is not
an extraction failure: `Relation` requires a name **or** a percentage, and filings
name suppliers far more rarely than they name competitors (Item 1 has an explicit
"Competition" section) or disclose customer concentration (Reg S-K Item 101
forces it at ≥10%). GLW's concentration disclosure is purely qualitative — *"a
relatively small number of end customers"* — so it correctly produced no customer
edge.

**Supply dependencies are extracted, but not as relations.**
`chain_position.upstream_dependencies` holds them as input *categories*
(`'rare earth minerals'`, `'CMOS foundry capacity'`, `'helium'`) — a different
node type from a counterparty, and one `research_relations` does not read.

---

## 6. Read surface

`scripts/pages/7_Equity_Research.py` renders `research_reports.raw_md`.

- `split_report_sections` splits on exact agent names — a bare `^### ` split
  shreds bodies, which carry their own `###` headings — then strips one trailing
  heading per body, because part headings (`## II. Research Team Decision`) sit
  *between* two agent headings and would otherwise strand on the previous agent.
- `escape_markdown_dollars` — `st.markdown` reads `$…$` as inline LaTeX, so
  "from **$53** to **$271.78**" renders as run-together math.
- `fell_back_to_free_text` warns when `report.json` holds `null` for the section
  being viewed.

**The splitting is a consequence of the schema, not a choice.** The producer
already writes 13 standalone `.md` files, but ingestion persists only
`complete_report.md`, and the cloud dashboard has no filesystem — only the slim
DB. A `research_report_sections` table would delete the splitter outright.

---

## 7. Not built

| Thing | Gated on |
|---|---|
| `supply_chain_edges` | `n_runs_total > 1`; the corroboration harness has not run, so `confidence` would be decoration |
| corroboration harness | n runs of one name against the same cached filing |
| `research_claims` | nothing consumes it — non-relation evidence (watch items, risks, moat) has no persisted verdict, so **GLW's grafted quote is in the DB ungated** |
| `research_report_sections` | §6 |
| `ingest_reports` / `comprehend_reports` phases | `phase_registry.py` has no research entries; both run only when a human calls them |
| R2 transport | sync the **EDGAR cache** with the reports (otherwise the gate silently stops being a gate) and upload `manifest.json` **last** |
| `degraded_agents` consumption | the producer emits it as of schema 1.1; nothing here reads it |
| `dst_ticker` resolution | §2 — the real LLM job in this layer |
