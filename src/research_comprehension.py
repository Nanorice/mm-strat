"""
Research comprehension — the observation log behind the knowledge base.

Reads the relations an agent extracted from a filing, scores each one's quote
against the cached filing text, and writes one row per relation per run into
`research_relations`. Per `plans/knowledge_base_schema.md` §2.1.

This is where `quote_verified` finally lands. `research_quote_fidelity` has been
computing it and throwing it away since it was written, because there was no
table to put it in — so the verification gate only ran when a human called it.

Append-only, one row per (run_id, rel_idx). Idempotent for the same reason
ingestion is: a run already in the table is skipped, so re-running over the whole
history inserts nothing. `supply_chain_edges` is a GROUP BY projection over this
log and is deliberately NOT built here — that layer needs n_runs_total > 1 to
mean anything, and the corroboration harness has not run.

No LLM, no network. The agent already did the extraction; this reads its output.
"""

import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import config
from src import db
from src.research_quote_fidelity import quote_is_grounded, load_filing_text

logger = logging.getLogger(__name__)

# Legal-form suffixes carry no identity — "Prysmian Group S.p.A." and "Prysmian
# Group" are one counterparty. Stripped for the dedup key only; the disclosed
# surface form is kept verbatim in counterparty_name.
_SUFFIXES = re.compile(
    r'\b(inc|incorporated|corp|corporation|co|company|ltd|limited|llc|lp|llp|'
    r'plc|nv|bv|ag|sa|se|spa|s\s*p\s*a|gmbh|kk|ab|as|oy|pte|pty)\b\.?',
    re.IGNORECASE,
)
_NON_WORD = re.compile(r'[^a-z0-9]+')


def counterparty_key(name: Optional[str], direction: str,
                     aggregate_count: Optional[int]) -> str:
    """The dedup key an edge will later group on.

    An aggregate ("our top five customers accounted for 49% of revenues") names
    no party and is still the most decision-relevant line in most profiles, so it
    gets a synthetic key and survives as a node rather than being dropped by a
    NULL.
    """
    if name:
        # Punctuation goes first: "Prysmian Group S.p.A." only matches the
        # suffix pattern once the dots are spaces, because \b sits on them.
        words = re.sub(r'\s+', ' ', _NON_WORD.sub(' ', name.lower())).strip()
        stripped = re.sub(r'\s+', ' ', _SUFFIXES.sub(' ', words)).strip()
        # A name that is *entirely* legal boilerplate keeps its raw form rather
        # than collapsing to the empty string and colliding with every other one.
        return stripped or words
    if aggregate_count is not None:
        return f'__top{aggregate_count}_{direction}s__'
    # ponytail: every unnamed non-aggregate counterparty of one direction shares
    # a key, so MRVL's two separate unnamed 10% customers will merge into one
    # edge. They are genuinely distinct parties and the filing does not identify
    # them; splitting them needs a disambiguator the disclosure does not carry.
    # Revisit when supply_chain_edges is built, not before.
    return f'__unnamed_{direction}__'


def _accession(source_ref: Optional[str]) -> Optional[str]:
    """The accession the evidence cites — first token of "<accession> <section> ¶n"."""
    return source_ref.split()[0] if source_ref else None


def _rows_for_run(run_id: str, ticker: str, report_date, key_facts_json: str) -> List[dict]:
    """One dict per relation in this run, with its quote scored.

    `quote_verified` is None — not False — when the filing is not cached. "We
    could not check" and "we checked and it failed" are different facts, and a
    box without the EDGAR cache would otherwise report every quote as fabricated.
    """
    profile = (json.loads(key_facts_json).get('agents') or {}).get('business_analyst')
    if not profile:
        return []

    try:
        filing, _ = load_filing_text(ticker)
    except FileNotFoundError:
        filing = None
        logger.warning(
            f"[Comprehension] {ticker} run {run_id}: no cached filing - relations "
            f"logged with quote_verified NULL. The gate cannot run without the "
            f"EDGAR cache; it does not error, it stops being a gate."
        )

    rows = []
    for idx, rel in enumerate(profile.get('relations') or []):
        evidence = rel.get('evidence') or {}
        quote = evidence.get('quote')
        source_ref = evidence.get('source')
        rows.append({
            'run_id':            run_id,
            'rel_idx':           idx,
            'src_ticker':        ticker,
            'report_date':       report_date,
            'accession':         _accession(source_ref),
            'direction':         rel.get('direction'),
            'counterparty_name': rel.get('counterparty'),
            'counterparty_key':  counterparty_key(
                rel.get('counterparty'), rel.get('direction'), rel.get('aggregate_count')),
            'aggregate_count':   rel.get('aggregate_count'),
            'pct_revenue':       rel.get('pct_revenue'),
            'quote':             quote,
            'source_ref':        source_ref,
            'strength':          evidence.get('strength'),
            'quote_verified':    None if filing is None or not quote
                                 else quote_is_grounded(quote, filing),
        })
    return rows


def ensure_tables(db_path: str = None) -> None:
    conn = db.connect(db_path or str(config.DUCKDB_PATH))
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS research_relations (
                run_id            VARCHAR NOT NULL,
                rel_idx           INTEGER NOT NULL,
                src_ticker        VARCHAR NOT NULL,
                report_date       DATE    NOT NULL,
                accession         VARCHAR,
                direction         VARCHAR NOT NULL,
                counterparty_name VARCHAR,
                counterparty_key  VARCHAR NOT NULL,
                aggregate_count   INTEGER,
                pct_revenue       DOUBLE,
                quote             VARCHAR,
                source_ref        VARCHAR,
                strength          VARCHAR,
                quote_verified    BOOLEAN,
                comprehended_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (run_id, rel_idx)
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS research_relations_tkr_idx "
            "ON research_relations (src_ticker, report_date)"
        )
    finally:
        conn.close()


def comprehend_runs(db_path: str = None, force: bool = False) -> Tuple[int, int]:
    """Log the relations of every ingested run. Returns (runs_processed, relations).

    Re-running writes nothing — a run already in `research_relations` is skipped.
    A run whose agent fell back to free text has no rows to key on, so it is
    re-read (one JSON parse) and counted as processed every time; that is the
    honest reading of "processed", not a leak.

    `force` re-scores runs already logged. Not speculative: the fidelity checker
    was corrected twice on 2026-07-20 (quote-glyph folding, then layout folding),
    and each fix changed stored verdicts that would otherwise stay wrong forever.
    A checker change is the one reason to recompute.
    """
    path = db_path or str(config.DUCKDB_PATH)
    ensure_tables(path)

    conn = db.connect(path)
    try:
        runs = conn.execute("""
            SELECT run_id, ticker, report_date, key_facts_json
            FROM research_report_runs
            WHERE key_facts_json IS NOT NULL
            ORDER BY report_date, ticker
        """).fetchall()

        done = {r[0] for r in conn.execute(
            "SELECT DISTINCT run_id FROM research_relations").fetchall()}

        processed = written = 0
        for run_id, ticker, report_date, key_facts_json in runs:
            if run_id in done and not force:
                continue
            rows = _rows_for_run(run_id, ticker, report_date, key_facts_json)
            if force:
                conn.execute("DELETE FROM research_relations WHERE run_id = ?", [run_id])
            processed += 1
            for r in rows:
                conn.execute("""
                    INSERT INTO research_relations
                        (run_id, rel_idx, src_ticker, report_date, accession,
                         direction, counterparty_name, counterparty_key,
                         aggregate_count, pct_revenue, quote, source_ref,
                         strength, quote_verified)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, [r[c] for c in (
                    'run_id', 'rel_idx', 'src_ticker', 'report_date', 'accession',
                    'direction', 'counterparty_name', 'counterparty_key',
                    'aggregate_count', 'pct_revenue', 'quote', 'source_ref',
                    'strength', 'quote_verified')])
                written += 1
        conn.commit()
    finally:
        conn.close()

    logger.info(f"[Comprehension] {processed} runs -> {written} relations")
    return (processed, written)


def fidelity_by_run(db_path: str = None) -> List[dict]:
    """Per-run relation counts and verified rate, straight from the log.

    The number that used to exist only in a human's terminal.
    """
    conn = db.connect(db_path or str(config.DUCKDB_PATH), read_only=True)
    try:
        rows = conn.execute("""
            SELECT src_ticker, report_date, run_id,
                   COUNT(*)                                    AS relations,
                   COUNT(*) FILTER (quote_verified)            AS verified,
                   COUNT(*) FILTER (quote_verified IS NULL)    AS uncheckable
            FROM research_relations
            GROUP BY src_ticker, report_date, run_id
            ORDER BY report_date DESC, src_ticker
        """).fetchall()
    finally:
        conn.close()
    cols = ['src_ticker', 'report_date', 'run_id', 'relations', 'verified', 'uncheckable']
    return [dict(zip(cols, r)) for r in rows]
