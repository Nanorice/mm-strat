# Knowledge Base — schema and management workflow

> Sprint 15. Design doc for discussion, **not yet implemented**. Follows
> [`report_ingestion_and_knowledge_base.md`](report_ingestion_and_knowledge_base.md)
> steps 3–5. Written 2026-07-20 against the real RKLB payload on disk.
>
> The governing constraint, from the user: **running the same thing twice must
> not produce twice the edges.** Everything below follows from taking that
> literally.

---

## 1. The idempotency argument

The obvious design — parse relations, insert into `supply_chain_edges` — is
wrong, and it is wrong in a way that only shows up after the table has been
polluted. If insertion is the write path, then every guard against duplication
is application logic you must get right *every time*: an upsert key, a
"have I seen this run" check, a dedup pass. Miss one path and the graph
silently double-counts.

The fix is structural: **make the edge table a projection, not an accumulator.**

```
research_report_runs  (exists)      append-only, PK run_id
        ↓
research_relations    (to build)    append-only, PK (run_id, rel_idx)
        ↓  GROUP BY — full recompute, the only write path
supply_chain_edges    (to build)    PK (src_ticker, counterparty_key, direction)
```

Two properties make this idempotent without any dedup logic:

1. **The observation log dedups on `run_id`, which the engine already enforces.**
   `research_report_engine.ingest_run_dir` returns early when a `run_id` is
   present in `research_report_runs`. Relations inherit that for free — re-ingest
   the same drop dir, and nothing is inserted anywhere.
2. **The edge table is `CREATE OR REPLACE ... AS SELECT` over the log.** It is
   recomputed, never mutated. Running the rebuild twice produces byte-identical
   output because a `GROUP BY` over unchanged input is unchanged. There is no
   code path that can double an edge, because there is no code path that adds to
   an edge.

The consequence worth internalising: **a second run's new information is a
counter going up, not a row appearing.** Ten runs of GLW yield one
`GLW→Apple/customer` row with `n_runs_seen = 10`. That is exactly the
corroboration signal the observed extraction variance (14 vs 7 relations from
identical input) demands, and it falls out of the schema rather than being
bolted on.

---

## 2. Schema

### 2.1 `research_relations` — the observation log

One row per relation per run. Append-only. This is also where the verification
gate finally persists: `research_quote_fidelity` currently computes
`quote_verified` and **discards it**, because there is no table to put it in.

```sql
CREATE TABLE research_relations (
    run_id            VARCHAR NOT NULL,
    rel_idx           INTEGER NOT NULL,   -- position in the run's relations[]
    src_ticker        VARCHAR NOT NULL,
    report_date       DATE    NOT NULL,
    accession         VARCHAR,            -- filing this rests on, from evidence.source
    direction         VARCHAR NOT NULL,   -- customer|supplier|partner|competitor
    counterparty_name VARCHAR,            -- as disclosed; NULL for aggregates
    counterparty_key  VARCHAR,            -- normalized; the dedup key
    aggregate_count   INTEGER,            -- "top five customers" -> 5
    pct_revenue       DOUBLE,
    quote             VARCHAR,            -- verbatim, per the contract
    source_ref        VARCHAR,            -- "0001819994-26-000013 item1a ¶19"
    strength          VARCHAR,            -- weak|moderate|strong — the AGENT's claim
    quote_verified    BOOLEAN,            -- OUR check against the cached filing
    PRIMARY KEY (run_id, rel_idx)
);
```

`strength` and `quote_verified` are deliberately separate columns. The first is
the model's self-assessment; the second is our mechanical verdict. Collapsing
them into one "confidence" at this layer would destroy the ability to ask the
question that matters — *does the agent's confidence track reality?*

### 2.2 `supply_chain_edges` — the derived graph

```sql
CREATE TABLE supply_chain_edges (
    src_ticker        VARCHAR NOT NULL,
    counterparty_key  VARCHAR NOT NULL,
    direction         VARCHAR NOT NULL,
    dst_ticker        VARCHAR,          -- nullable: government, private, unresolved
    counterparty_name VARCHAR,          -- most recent surface form, for display
    node_type         VARCHAR,          -- listed|government|private|aggregate
    weight            DOUBLE,           -- pct_revenue when disclosed, NEVER imputed
    n_runs_seen       INTEGER,          -- corroboration numerator
    n_runs_total      INTEGER,          -- runs of (src_ticker, accession) — denominator
    n_verified        INTEGER,          -- of those, how many had a verified quote
    confidence        DOUBLE,
    first_seen        DATE,
    last_seen         DATE,
    accession         VARCHAR,
    PRIMARY KEY (src_ticker, counterparty_key, direction)
);
```

**The PK excludes `run_id` and every date.** That is the idempotency requirement
expressed in the schema itself, not in code.

Four decisions taken from the real payload:

**`n_runs_total` is scoped to `(src_ticker, accession)`, not to the ticker.**
Corroboration only means something across runs *of the same filing*. Comparing a
2025 10-K run against a 2026 10-K run is a time series, not agreement — and
conflating them makes a stale edge look well-supported, which is the exact
failure mode a confidence number is supposed to prevent.

**`counterparty_key` must be normalized, or the PK does not dedup.** The RKLB
filing names the same entity as "Space Development Agency" and "SDA" in adjacent
paragraphs. Two surface forms hitting a raw-name PK is the double-counting the
whole design exists to avoid. Normalization: lowercase, strip legal suffixes
(Inc/Corp/Ltd/plc/LLC), collapse whitespace, expand a small hand-maintained
alias table for the cases that matter (government bodies, mostly).

**Aggregates are nodes, not dropped rows.** The single strongest fact in the
RKLB extraction is `{counterparty: null, aggregate_count: 5, pct_revenue: 49.0}`
— "top five customers are 49% of revenue." There is no edge to draw and it is
still the most decision-relevant line in the profile. Give it a synthetic
`counterparty_key` (`__top5_customers__`, `node_type = 'aggregate'`) so it
renders as a node in the graph and survives every query that a NULL would drop.

**`weight` is never imputed.** `pct_revenue` when the filing discloses it, NULL
otherwise. A graph where thickness sometimes means "disclosed 38%" and sometimes
means "we guessed" is worse than one with thin grey edges.

### 2.3 Confidence

```
confidence = strength_weight × verified_rate × corroboration_rate

  strength_weight    weak 0.3 | moderate 0.6 | strong 1.0   (agent's claim)
  verified_rate      n_verified / n_runs_seen               (our check)
  corroboration_rate n_runs_seen / n_runs_total             (agreement)
```

Multiplicative, so any one of the three going to zero zeroes the edge — an
unverified quote should not be rescued by having been repeated. Deliberately
crude: **do not tune these weights until there is enough data to calibrate
against.** With one usable report the numbers are decoration.

`n_runs_total = 1` makes `corroboration_rate` trivially 1.0, which overstates a
single run. Until the corroboration harness runs n≥3, treat `confidence` as
provisional and **do not render single-run edges as solid** — see §4.

---

## 3. Management workflow

### 3.1 The pipeline

```
producer (fork, Hang or sh019)
    ↓  writes report tree
drop dir  →  R2  →  sh019                        transport (§3.2)
    ↓
research_report_engine.ingest_drop_dir()         EXISTS — dedups on run_id
    ↓  research_reports + research_report_runs
research_comprehension.py                        TO BUILD
    ├─ parse relations from key_facts_json
    ├─ score quotes (research_quote_fidelity, EXISTS but unwired)
    ├─ normalize counterparty_key
    └─ resolve dst_ticker (company_profiles.name, cik_map.company_name)
    ↓  research_relations
rebuild_supply_chain_edges()                     TO BUILD — full recompute
    ↓  supply_chain_edges
Supply-chain page network view                   placeholder EXISTS
```

Two orchestrator phases, not one, per the design doc's reasoning: ingest fails
loudly on malformed files and is cheap to retry; comprehension fails quietly on
extraction quality and is expensive to detect. Merging them hides the second
behind the first.

| Phase id | Does | Failure mode |
|---|---|---|
| `ingest_reports` | drop dir → `research_reports` | loud, cheap |
| `comprehend_reports` | → `research_relations` → `supply_chain_edges` | quiet, expensive |

**Neither exists.** `phase_registry.py` currently has zero research entries;
ingestion runs only when a human calls it.

### 3.2 Transport

R2 carries the drop dir and the EDGAR cache between boxes. Both are small —
**reports 965 KB, filing cache 52 MB** as of 2026-07-20, against a 10 GB tier.
Credentials, a boto3 client and a pull-on-boot pattern already exist
(`sync_dashboard_db.py`, `dashboard_utils`), so this is configuration, not
architecture.

Two rules:

- **Sync the EDGAR cache, not just the reports.** `research_quote_fidelity`
  scores quotes against `EDGAR_CACHE_DIR`. Reports without filings ingest fine
  and cannot be verified — the gate does not error, it just stops being a gate.
- **Upload `manifest.json` last.** A report tree is 15+ files and a partial
  upload is ingestable-looking. The engine already skips a run with no manifest,
  loudly. Ordering the upload so the manifest lands last makes a half-uploaded
  tree un-ingestable for free — no marker file, no completeness protocol.

### 3.3 Rebuild cadence

`supply_chain_edges` is a full recompute over `research_relations`. At any
plausible scale (thousands of relations) this is a sub-second `GROUP BY`, so
rebuild it on every `comprehend_reports` run rather than trying to update
incrementally. **Incremental update is the thing this design exists to avoid.**

### 3.4 Corroboration harness

Step 4 of the build order. n runs of one name against the *same cached filing*,
which is free of SEC fetches and deterministic on the input side. Its only job
is to populate `n_runs_total > 1` so `corroboration_rate` becomes meaningful.

Run it on 3–4 names before trusting any confidence number. Cost is ~$0.10/run.

---

## 4. What must be true before the graph is drawn

The network view is the most persuasive artifact in this project and the easiest
to mislead with. An Obsidian-style graph renders every edge as equally true; the
underlying data is emphatically not.

Gates, in order:

1. **Typed profiles must be reliable.** Currently 1 of 3 reports has a non-null
   `business_analyst`. Two producer bugs are fixed but the post-fix rate is
   unmeasured. n=1 is not a knowledge base.
2. **`quote_verified` must be persisted**, not computed and thrown away.
3. **`n_runs_total > 1`** on at least a few names, or confidence is decoration.
4. **Render confidence visually** — edge opacity or width by `confidence`, and
   unresolved counterparties (`dst_ticker IS NULL`) visibly distinct from
   resolved ones. A single-run unverified edge and a 5-of-5 verified edge must
   not look the same.

---

## 5. Open, deliberately

- **Build vs buy** for supply-chain data, open since 2026-07-18. This design
  does not resolve it; it means the "build" path has a working extractor if
  chosen.
- **Alias table for `counterparty_key`.** Hand-maintained, or fuzzy-match with a
  review queue? Roughly half of RKLB's named counterparties are government
  bodies (NASA, DARPA, NRO, SDA) that resolve to no ticker and drift in naming.
- **Retention.** `raw_md` at ~50 KB/row is the growth item; `research_relations`
  is small by comparison. Currently uncapped, and `research_reports` now also
  ships whole into `dashboard.duckdb` and therefore R2 — window it past ~2k rows
  (`ponytail:` marker in `build_dashboard_db.py`).
