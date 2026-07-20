# Session Handover: 2026-07-20 (session 05)

## 🎯 Goal
Answer the four open questions carried out of session 03 — how to track the TradingAgents
work, where reports live and how they reach R2, the dashboard's report picker, and the
knowledge-base graph — then verify the producer fix by re-running MRVL.

## ✅ Accomplished

**The producer is a fork now, and the deployment path is written down**
- User forked to `github.com/Nanorice/TradingAgents`, branch `mm-strat-report`, one commit
  (`67285f3`) on upstream's v0.3.1. Tree clean, pushed. The risk named below is closed.
- Naming convention fixed: **"the producer"** in mm-strat prose, never "TradingAgents"
  (that name points at a repo containing none of this work). **Cite SHAs, not descriptions.**
- `docs/architecture/producer_deployment.md` — clone/venv/creds, the three things to check
  before spending on a batch, upstream rebase, and the transport decision that deploying on
  `Hang` forces.

**Dashboard: section picker + two rendering bugs**
- Report picker under the ticker selector, Business Analyst defaulted first, plus
  "Everything". Splits `raw_md` on exact agent names — a bare `^### ` split shreds the
  bodies, which carry their own `###` headings. Verified 13/13 sections, 100% coverage on
  the real GLW report.
- **The run-together words were Streamlit, not the producer.** `st.markdown` reads `$…$`
  as inline LaTeX; a report saying "from **$53** to **$271.78**" renders everything between
  the dollar signs as math with the spaces eaten. Escaped globally.
- **The Business Analyst JSON dump was a broken run, not a broken renderer.** RKLB (typed)
  renders as clean prose; GLW/MRVL (`business_analyst: null`) fell back to free text and the
  model happened to emit JSON. The page now detects the fallback and says so rather than
  letting a degraded run pass as a finished report.

**The R2 gap: `research_reports` was never in the slim-DB manifest**
- So the cloud dashboard's page 7 would have shown "the research layer isn't built yet"
  forever, no matter how many reports landed. Added to `build_dashboard_db.py`.

**MRVL rerun — the producer fix holds, and ingestion exercised its untested path**
- All five agents typed (`business_analyst` was NULL pre-fix), 6 relations, $0.106, 19 calls.
- Parent row **replaced** with the new `run_id`, **both** child runs kept — the
  replace-parent-keep-both-children path session 03 flagged as unexercised.

**Found and fixed a quote-fidelity false negative worth more than the rerun**
- MRVL first scored **60.7% (17/28)** against RKLB's 100%, which read as a real quality gap.
  It was not. The 10-K defines terms as `("Marvell," "MTI,")`; the model transcribed
  `('Marvell,' 'MTI,')` — every word verbatim, quote style swapped. `_PUNCT` folded
  curly→straight but never unified single vs double, and **both forms here were already
  straight**, so normalization did nothing. One line in the shared `normalize()`:
  **60.7% → 96.4%**, RKLB unchanged at 100%, all negative controls still pass.
- The one surviving flag is **correct and deliberately left**: the model quoted
  `cost of goods sold 49.0 [for fiscal 2026]`. The figure is real; the bracket is the model's
  own gloss picking between two table columns. Loosening the checker to strip brackets would
  silently bless an inference wearing a quote's clothing.

**Knowledge-base schema designed** (`plans/knowledge_base_schema.md`, for discussion)
- Idempotency by construction: `research_relations` (append-only, PK `(run_id, rel_idx)`)
  → `supply_chain_edges` (PK `(src_ticker, counterparty_key, direction)`, rebuilt as a
  `GROUP BY` projection, never mutated). A second run's new information is a counter going
  up, not a row appearing.

## 📝 Files Changed

**Committed by a parallel window mid-session** (see Work in Progress) — `18d3a16`, `3ccd01e`:
- `scripts/dashboard_utils.py`: `split_report_sections`, `escape_markdown_dollars`,
  `fell_back_to_free_text`.
- `scripts/pages/7_Equity_Research.py`: section picker, escaped render, fallback warning.
- `scripts/build_dashboard_db.py`: `research_reports` added to the manifest.
- `tests/test_report_sections.py`: **new** — 9 tests.
- `docs/architecture/producer_deployment.md`: **new**.
- `docs/session_logs/sprint_15/plans/knowledge_base_schema.md`: **new**.

**This session, uncommitted at time of writing:**
- `src/research_quote_fidelity.py`: fold every quote glyph to one in `normalize()`.
- `tests/test_research_quote_fidelity.py`: 2 regression tests for the fold.

**DB (live)**: MRVL parent row replaced (`run_id` `08ebf90143ce` → `5434877186fc`);
`research_report_runs` 3 → 4.

**Producer (`mm-strat-report`)**: no changes this session. Last commit `67285f3`.

## 🚧 Work in Progress (CRITICAL)

- **GLW is still a fallback row.** Only MRVL was re-run — the user authorized that one name.
  GLW's `business_analyst` is still NULL and the dashboard flags it. ~$0.11 to fix.
- **The post-fix structured success rate is 1 for 1** — not yet a rate. Two or three more
  names would make it one. Step 3 was gated on this number in session 03 and still is.
- **`thesis` still stores a rating.** All three rows have `thesis == conviction`
  ("Underweight"/"Buy"). `research_report_engine.py:220` maps
  `research_manager.recommendation`; `portfolio_manager.investment_thesis` is intended.
  Known since session 03, one line, still wrong in prod.
- **A parallel window committed this session's work again.** `18d3a16` and `3ccd01e` landed
  from another session while this one ran, exactly as session 03 warned. `git status` showed
  only 2 modified files despite 6 having been edited. **Verify against HEAD's content, not
  against `git log -1 -- <file>`** — that returns the last commit touching a file whether or
  not your edit is in it, and 18d3a16 predated this session.
- **`quote_verified` is still computed and discarded.** Nothing persists it; the verification
  gate runs only when a human calls it.

## ⏭️ Next Steps

1. **Fix the `thesis` mapping** — one line, wrong data in prod on every row.
2. **Emit `degraded_agents` in the producer's `manifest.json`** when a structured call falls
   back. ~10 lines. Do this *before* measuring the success rate, or the measurement rests on
   a signal the consumer infers from a null.
3. **Re-run GLW**, then 2–3 more names for a real post-fix rate.
4. `research_relations` + `comprehend_reports` phase — the table that finally persists
   `quote_verified`.
5. `ingest_reports` orchestrator phase; R2 transport for the drop dir **and the EDGAR cache**.

## 💡 Context/Memory

- **The business analyst is not flakier than the other structured nodes — it is ~30× larger.**
  Portfolio Manager, Trader, Research Manager and Sentiment all use the same
  `invoke_structured_or_freetext` path and ask for 3–5 flat fields with 0–1 validators.
  `BusinessProfile` asks for 17 fields, mostly lists of nested models, each carrying a
  verbatim quote, plus nested `Relation` (5 fields, 2 validators) × N. Pydantic fails the
  whole object on one bad element, so P(total failure) rises with relation count — which is
  why GLW (9 relations) failed deterministically while RKLB (7) passed. The fix reduces this;
  it does not eliminate it, and the fallback is still silent in the artifact.
- **A fidelity score below ~100% should be diagnosed as a checker bug first.** Two of these
  now: the trailing full stop (8.7pp, session 03) and the quote-style swap (35.7pp, today).
  Both were false negatives making a clean run look fabricated. A model that fabricates
  usually alters a *word*, which survives every normalization.
- **EDGAR filing text lives entirely outside DuckDB.** `market_data.duckdb` holds only
  `cik_map` (10,804 rows) — there is no `edgar_filings` table. Everything is at
  `~/.tradingagents/cache/edgar/<TICKER>/<accession>/` (`raw.htm`, sliced `item1/1a/7.md`,
  `meta.json`): 12 tickers, 11 accessions, 52 MB, one disk, no backup. It *is* reconstructible
  — SEC filings are immutable and `meta.json` carries the exact URL — but verification runs
  against the **sliced** text, so `quote_verified` is not reproducible across a cache rebuild
  if the slicing changes. Persist verdicts; don't recompute them on demand.
- **R2 is the right transport and I was wrong to reach for robocopy.** Both boxes have creds,
  a boto3 client and a pull-on-boot pattern; reports are 965 KB and the filing cache 52 MB
  against a 10 GB tier. Two rules: **sync the EDGAR cache too** (reports without filings
  ingest fine and silently cannot be verified — the gate does not error, it stops being a
  gate), and **upload `manifest.json` last** (the engine already skips manifest-less runs, so
  ordering makes a half-uploaded tree un-ingestable for free).
- **A test that asserts nothing passes.** The first version of the fold regression test
  replaced a word absent from the quote, so the substitution was a no-op and the assertion
  was vacuous. Caught only because the paired positive case made the pair contradictory.
