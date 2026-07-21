# Sprint 15 — Research Log

This is the linear train-of-thought for the sprint, tracking questions and their resolution.

Started 2026-07-20 (retroactively, from session 04 — earlier sessions' questions are
reconstructed from their handovers and marked as such).

## Thread A: The blank-score seam (screening display vs model universe)

1. **Why are 666 of 672 Screening rows unscored?** → The prod model was promoted having only ever run as shadow, which scores the `breakout` cohort alone; the ~837 rows/day belonged to the now-archived prototype, and the d3 views join `status_flag='prod'`. [2026-07-20_02](logs/2026-07-20_02_screening_dates_and_scores.md)
2. **Why did the screening population never match the SEPA gate?** → It was `trend_ok ∨ breakout_ok` since 93497c9; the gate is AND. 42 of 79 "triggered" rows were breakouts failing C1–C9. [2026-07-20_02](logs/2026-07-20_02_screening_dates_and_scores.md)
3. **Can the remaining 13 blanks be scored, or are they structurally unscoreable?** → Structural, and now fixed: T3's universe was "ever opened a session", so a first-time setup was invisible until it triggered. Widened to ever-`trend_ok` (107 tickers / 0.6% of t3). Blanks 13 → 0. [2026-07-20_04](logs/2026-07-20_04_stage_semantics_and_t3_universe.md)
4. **Is the T3 gap structural or a materialization artifact?** → Both, ~40/60. 335 rows were stale-t3 (ticker in the universe, never materialized for that date); 566 were the true universe gap. The first needs a recompute, only the second needed the widening. [2026-07-20_04](logs/2026-07-20_04_stage_semantics_and_t3_universe.md)
5. **Is M01 valid on names with no session history?** ? **OPEN — see Open meta-questions.**

## Thread B: Stage semantics

6. **What does `triggered` actually mean?** → It meant "is breaking out today" (`breakout_ok`, a one-day event flag) where the intent was "has broken out" (a state). 403 of 630 rows were mislabelled `setup` while in an open session. Re-keyed to the open session. [2026-07-20_04](logs/2026-07-20_04_stage_semantics_and_t3_universe.md)
7. **How can a name fail `trend_ok` while its session stays open?** → By design: entry needs full C1–C9, exit only breaks on C1+C2+C6 (C9 RS flicker would shred one session into many). All 42 such names verified `trend_ok ∧ breakout_ok` at entry. [2026-07-20_04](logs/2026-07-20_04_stage_semantics_and_t3_universe.md)
8. **Does `set_shadow()` write a status the CHECK constraint rejects?** ⟳ No — the earlier claim was wrong. The live CHECK already allows `'shadow'`; only `ViewManager`'s `CREATE TABLE IF NOT EXISTS` DDL was stale, so it never touched the live table. **Read the DB's own DDL, not the code's.** [2026-07-20_04](logs/2026-07-20_04_stage_semantics_and_t3_universe.md)

## Thread C: Cross-view feature consistency

9. **Why do `score_from_t3` and `daily_predictions` disagree for 8 tickers?** → `fundamental_features` contains 939 duplicate `(ticker, filing_date)` pairs across 354 tickers; 602 are one populated row + one all-NULL twin. Both views dedupe with `ORDER BY fiscal_period DESC`, which **ties** — so each lands on a different twin arbitrarily. `v_d3_lifecycle` gets the real numbers, `v_t3_training` the NULLs. [2026-07-20_04](logs/2026-07-20_04_stage_semantics_and_t3_universe.md)
10. **Where should that be fixed — the views or the table?** ? **OPEN — see Open meta-questions.**

## Thread D: The research producer and its verification gate

11. **Why does the business analyst fall back to free text when the other structured nodes don't?** → Not flakiness: ~30× the schema surface. PM/Trader/Research Manager/Sentiment ask for 3–5 flat fields, 0–1 validators; `BusinessProfile` asks for 17, mostly lists of nested models, plus `Relation` (5 fields, 2 validators) × N. Pydantic fails the whole object on one bad element, so P(failure) rises with relation count — GLW (9) failed deterministically, RKLB (7) passed. [2026-07-20_05](logs/2026-07-20_05_producer_fork_and_kb_design.md)
12. **Is MRVL's 60.7% fidelity a real quality gap?** ⟳ No — a checker false negative. The filing writes `("Marvell," "MTI,")`, the model `('Marvell,' 'MTI,')`; `_PUNCT` folded curly→straight but never single→double, and both forms were already straight. Folding every quote glyph: 60.7% → 96.4%, RKLB unchanged. **Second such bug this sprint — diagnose a sub-100% score as a checker bug first.** [2026-07-20_05](logs/2026-07-20_05_producer_fork_and_kb_design.md)
13. **Is the last unverified MRVL claim a fabrication?** → No, and the flag is still correct. `cost of goods sold 49.0 [for fiscal 2026]` — figure real, bracket is the model's own gloss disambiguating two table columns. Left flagged; stripping brackets would bless an inference wearing a quote's clothing. [2026-07-20_05](logs/2026-07-20_05_producer_fork_and_kb_design.md)
14. **Is EDGAR filing text stored outside DuckDB?** → Entirely. The DB holds only `cik_map`; all text is the producer's on-disk cache (52 MB, 11 accessions, no backup). Reconstructible — filings are immutable, `meta.json` has the URL — but verification runs against the **sliced** text, so `quote_verified` is not reproducible across a re-slice. Persist verdicts. [2026-07-20_05](logs/2026-07-20_05_producer_fork_and_kb_design.md)
15. **How do edges stay idempotent across repeated runs?** → Make `supply_chain_edges` a `GROUP BY` projection over an append-only `research_relations` log keyed on `run_id`, never an accumulator. A second run increments a counter; it does not add a row. [plans/knowledge_base_schema.md](plans/knowledge_base_schema.md)
16. **What is the post-fix structured-output success rate?** → **8/9 (89%)**, measured over 3 names × 3 runs. The one miss is GLW — a fresh run fell back to free text. Confirms Q11: failure scales with relation count (GLW has 9), the producer fix reduced but did not eliminate it. `degraded_agents` (producer `aa627e1`) now makes each miss visible in the manifest. [2026-07-20_06](logs/2026-07-20_06_ingestion_harness_and_kb.md)
17. **What harness keeps the *other* producer nodes consistent?** → None — they are free text (`chain.invoke → content`, no schema), so they cannot fail a contract they don't have. The structured harness is one shared fn with a *silent* free-text fallback; the business analyst is just the only schema big enough for it to bite. The real gap was no degradation signal at all (structured → `null`, free-text → `""`, an empty section is omitted and looks clean). Closed by `degraded_agents`. [2026-07-20_06](logs/2026-07-20_06_ingestion_harness_and_kb.md)
18. **Is a single extraction run reliable?** → No. MRVL gave 2/4/6 relations from identical input across 3 runs. Justifies the append-only + corroboration-counted design retroactively; n=1 confidence is fiction. [2026-07-20_06](logs/2026-07-20_06_ingestion_harness_and_kb.md)
19. **Does GLW's one surviving fidelity flag mean the checker is still too strict?** ⟳ No — it is the **first true positive**. The model grafted a real clause from the previous sentence onto the next ("...to achieve our goals, through 2026 and beyond."). Every word real, the sentence invented. Two *other* GLW flags were checker bugs (lost block boundaries in sliced text); folding layout: 90.3 → 96.8%. Rule refined: layout difference at the divergence point = checker bug, different continuation = model. [2026-07-20_06](logs/2026-07-20_06_ingestion_harness_and_kb.md)
20. **Where does an LLM belong in the ingestion layer?** → Not over already-typed data (the producer emitted validated Pydantic; a second pass only subtracts). It belongs on *unstructured* input: `dst_ticker` name→ticker resolution, and recovering the free-text fallback runs. [research_layer.md](../../modules/research_layer.md) [2026-07-20_06](logs/2026-07-20_06_ingestion_harness_and_kb.md)
21. **Is `counterparty_key` strong enough to dedup an edge?** ⟳ **RESOLVED** — no, and now fixed. The trailing-`(...)` strip must run **before** the punctuation fold (`_NON_WORD` turns `(SDA)` into ` sda ` and the letters survive). Applied + `comprehend_runs(force=True)`: RKLB's SDA went 2/3 + 1/3 → **one row at 3/3**; NRO → one row at 2/3 (a true count, not a split). Now in memory `research-relations-comprehension`. [2026-07-21_02](logs/2026-07-21_02_edges_and_claims_gate.md)

23. **Table or view for `supply_chain_edges`?** → **View.** KB-schema §1 argues at length that insertion must be a full recompute for idempotency; a `CREATE OR REPLACE VIEW` makes that recompute *implicit*, so the property is unfalsifiable rather than merely enforced and §3.3's `rebuild_supply_chain_edges()` stops existing. 26 live edges. [2026-07-21_02](logs/2026-07-21_02_edges_and_claims_gate.md)

24. **How is an edge segment-grained when no segment field exists?** → `direction` *is* the discriminator we have: grain `(src_ticker, counterparty_key, direction, accession)` already gives one counterparty two rows when it is competitor *and* supplier, satisfying industry-study §2.3 (Q22) with existing columns. True line-of-business segmentation needs a producer field. `accession` in the grain is a knowing PK deviation (corroboration is per-filing; one 10-K per name today) — `ponytail:` marked. [2026-07-21_02](logs/2026-07-21_02_edges_and_claims_gate.md)

25. **Was the non-relation evidence ever gated?** → No — `research_relations` structurally sees only counterparty edges, so watch items, risks, moat, cost structure and evidenced products carried unchecked quotes (Q19's GLW graft among them). `research_claims` + `comprehend_claims()` closes it, **data-driven** over any field with an `evidence.quote` rather than a hand-listed set — which immediately caught RKLB's evidenced `products` dicts that no field list would have included. 162 claims, 158 verified. [2026-07-21_02](logs/2026-07-21_02_edges_and_claims_gate.md)

26. **Do the 4 claim flags mean the checker needs an ellipsis fix?** ⟳ **No — all 4 are true positives, and the obvious read was wrong.** Every flag diverged at a ` ... `, suggesting a legitimate elision the checker mishandles; but splitting on the ellipsis left **every** flag with a still-non-verbatim fragment. Bisecting *inside* the fragment gave the truth: the two known flags (GLW graft, MRVL bracket-gloss) plus two new genuine ones — a GLW `revenue_model` **unmarked** stitch of non-contiguous sentences, and RKLB `products` "…orbital rocket **in 2025**" where the filing sentence ends at "rocket". Refines Q19's rule: **a `...` is not evidence of a checker bug — bisect inside the fragment first.** [2026-07-21_02](logs/2026-07-21_02_edges_and_claims_gate.md)

27. **How should a finished report notify?** → **Compact Discord briefing + a link to the dashboard's Equity Research page** — not R2, not PDF, not markdown. A ~100 KB report does not fit a message, and the dashboard already renders it properly, so a second artifact duplicates a render for no reader the link doesn't serve. R2/PDF only earns its keep if the report must be readable with the dashboard down. **Designed, not built** — it should be built with the orchestrator phase that fires it. [2026-07-21_02](logs/2026-07-21_02_edges_and_claims_gate.md)

## Thread E: The industry-study end state

22. **What does the KB need that per-company extraction can't give?** ? **OPEN** — eleven structural gaps (`plans/industry_study_direction.md`), load-bearing ones: materiality is a *cross-company* join (counterparty-side revenue share lives in the counterparty's filing) → favour breadth over depth; one company is several counterparties (RKLB competitor+supplier) → edges must be segment-grained; absence is a finding (insourcing, reasoned exclusions); verifying non-EDGAR sources (contracts, press) needs a second gate design — a news article is not immutable. [2026-07-20_06](logs/2026-07-20_06_ingestion_harness_and_kb.md)

---

## Open meta-questions

- **Sector-order vs score-order for the shortlist queue — blocks the P0 selector.**
  Nothing ranks/cuts `daily_predictions` into a ticker list; today it is passed by hand
  (`research_layer.md` §8). But the ordering rule is a real fork, not an implementation
  detail: a pure top-N-by-score feed scatters one name each across eight sectors and
  **no sector chain map ever completes**, while sector-clustering the queue delays the
  highest-scoring names. `agentic_digestion_layer.md` flags this "Unsettled — flag,
  don't assume." Also needs: N set by *digestion capacity* (not model confidence), and a
  cooldown so an unchanged thesis isn't re-litigated nightly. **Get the call before building.**

- **Q3 (from [t3_universe_widening.md](plans/t3_universe_widening.md)): is M01 valid on
  first-time setups?** M01 trained on the SEPA population — every training row is a name that
  had already opened a session. The 12 first-time setups now receive scores, but no training
  feature has been checked for implicit conditioning on prior-session existence. If any is,
  those scores are out-of-distribution and the honest answer is to restore the blank and say
  why, not to keep a number that looks like the others. User has accepted them as
  placeholder-grade for non-`triggered` rows in the interim — that is a display decision, not
  a validity finding. **Method**: inspect `model_feature_sets` for session-derived features;
  compare the 12 names' feature distributions against the training population.

- **Where to fix the duplicate-fundamentals coin-flip (Q9)?** Two options. *Patch the views* —
  add a NULL-payload tiebreak (`ORDER BY (eps_diluted IS NULL AND revenue IS NULL), …`) to
  `ff_dedup` and the `v_t3_training` join; small, but must be applied in every consumer and
  the next new view will forget it. *Fix the table* — delete the empty twins where a populated
  sibling exists, so every consumer routes through clean data; correct but a destructive write
  to prod, and `d2_training_cache` would need a refresh since training data may embed the
  coin-flip. Root cause is upstream: why does the fundamentals engine write an empty shell at
  a slightly different `report_date` (2025-09-30 vs 2025-10-03)? **Answer that before choosing.**
  Related: 252 further pairs have two *populated* rows — those are tie-broken arbitrarily too,
  and no NULL check would catch them.
