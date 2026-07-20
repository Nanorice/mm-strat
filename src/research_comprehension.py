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
        # A trailing acronym gloss is not identity: "Space Development Agency
        # (SDA)" and "Space Development Agency" are one party. Strip it before
        # keying, or the paren's letters survive _NON_WORD and split the edge.
        name = re.sub(r'\s*\([^)]*\)\s*$', '', name)
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


def _load_filing_or_none(ticker: str, run_id: str) -> Optional[str]:
    """The cached filing text, or None when it is not cached — the one case where
    `quote_verified` must be NULL, not False. "Could not check" and "checked and
    failed" are different facts; a box without the EDGAR cache would otherwise
    report every quote as fabricated. The gate does not error, it stops gating."""
    try:
        return load_filing_text(ticker)[0]
    except FileNotFoundError:
        logger.warning(
            f"[Comprehension] {ticker} run {run_id}: no cached filing - rows "
            f"logged with quote_verified NULL. The gate cannot run without the "
            f"EDGAR cache; it does not error, it stops being a gate."
        )
        return None


def _verdict(quote: Optional[str], filing: Optional[str]) -> Optional[bool]:
    return None if filing is None or not quote else quote_is_grounded(quote, filing)


def _rows_for_run(run_id: str, ticker: str, report_date, key_facts_json: str) -> List[dict]:
    """One dict per relation in this run, with its quote scored."""
    profile = (json.loads(key_facts_json).get('agents') or {}).get('business_analyst')
    if not profile:
        return []
    filing = _load_filing_or_none(ticker, run_id)

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
            'quote_verified':    _verdict(quote, filing),
        })
    return rows


# A claim's human label lives under one of these, in this order (watch_item.name,
# key_risk.title, choke_point.description); single-dict fields (moat,
# cost_structure) have none and log NULL.
_LABEL_KEYS = ('name', 'title', 'description')


def _claim_rows_for_run(run_id: str, ticker: str, report_date, key_facts_json: str) -> List[dict]:
    """One dict per non-relation evidence-bearing claim in this run.

    Data-driven, not a hand-listed set of fields: every top-level profile field
    whose item(s) carry an `evidence.quote` becomes a gated claim, so a producer
    that adds a new evidenced section is covered without a code change here.
    `relations` is skipped — its evidence lives in research_relations. This is the
    table that gates non-relation claims like GLW's grafted watch_item, which
    `research_relations` structurally cannot see.
    """
    profile = (json.loads(key_facts_json).get('agents') or {}).get('business_analyst')
    if not profile:
        return []
    filing = _load_filing_or_none(ticker, run_id)

    rows, idx = [], 0
    for field, value in profile.items():
        if field == 'relations':
            continue
        for item in (value if isinstance(value, list) else [value]):
            if not isinstance(item, dict):
                continue
            evidence = item.get('evidence')
            if not isinstance(evidence, dict) or not evidence.get('quote'):
                continue
            quote, source_ref = evidence.get('quote'), evidence.get('source')
            rows.append({
                'run_id':         run_id,
                'claim_idx':      idx,
                'src_ticker':     ticker,
                'report_date':    report_date,
                'accession':      _accession(source_ref),
                'claim_type':     field,
                'label':          next((item[k] for k in _LABEL_KEYS if item.get(k)), None),
                'quote':          quote,
                'source_ref':     source_ref,
                'strength':       evidence.get('strength'),
                'quote_verified': _verdict(quote, filing),
            })
            idx += 1
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
        conn.execute("""
            CREATE TABLE IF NOT EXISTS research_claims (
                run_id          VARCHAR NOT NULL,
                claim_idx       INTEGER NOT NULL,
                src_ticker      VARCHAR NOT NULL,
                report_date     DATE    NOT NULL,
                accession       VARCHAR,
                claim_type      VARCHAR NOT NULL,
                label           VARCHAR,
                quote           VARCHAR,
                source_ref      VARCHAR,
                strength        VARCHAR,
                quote_verified  BOOLEAN,
                comprehended_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (run_id, claim_idx)
            )
        """)
        _ensure_edges_view(conn)
    finally:
        conn.close()


# Strength the agent asserted → the multiplier in the confidence formula
# (knowledge_base_schema.md §2.3). Unknown/missing folds to moderate, not zero:
# an absent label is not evidence of weakness.
_STRENGTH_SQL = """CASE lower(strength)
    WHEN 'strong' THEN 1.0 WHEN 'moderate' THEN 0.6 WHEN 'weak' THEN 0.3
    ELSE 0.6 END"""


def _ensure_edges_view(conn) -> None:
    """`supply_chain_edges` — the derived graph, per knowledge_base_schema.md §2.2.

    A view, not a table: it is a full GROUP BY recompute over research_relations
    on every read, so there is no stored copy to drift and no rebuild step to
    forget. The schema's §3.3 rebuild_supply_chain_edges() is the write-path
    version of the same projection; a view makes the recompute implicit.

    `dst_ticker` is NULL for now — resolving a counterparty name to a listed
    ticker is the one real LLM job in this layer and is deliberately deferred.

    ponytail: grain is (src_ticker, counterparty_key, direction, accession).
    The schema PK drops accession, but corroboration is per-filing (n_runs_total
    is scoped to accession), so a counterparty named in two different 10-Ks would
    yield two rows here — a stated-PK violation. Every ticker has exactly one
    accession today, so the grains coincide. Upgrade when a second filing lands:
    collapse to the latest accession per (src, key, direction).
    """
    conn.execute(f"""
        CREATE OR REPLACE VIEW supply_chain_edges AS
        WITH totals AS (
            SELECT src_ticker, accession, COUNT(DISTINCT run_id) AS n_runs_total
            FROM research_relations WHERE accession IS NOT NULL
            GROUP BY src_ticker, accession
        ),
        edges AS (
            SELECT
                src_ticker, counterparty_key, direction, accession,
                arg_max(counterparty_name, report_date)  AS counterparty_name,
                CASE WHEN starts_with(counterparty_key, '__top')
                     THEN 'aggregate' END                AS node_type,
                max(pct_revenue)                         AS weight,
                COUNT(DISTINCT run_id)                   AS n_runs_seen,
                COUNT(DISTINCT run_id) FILTER (quote_verified) AS n_verified,
                avg({_STRENGTH_SQL})                     AS strength_weight,
                min(report_date)                         AS first_seen,
                max(report_date)                         AS last_seen
            FROM research_relations WHERE accession IS NOT NULL
            GROUP BY src_ticker, counterparty_key, direction, accession
        )
        SELECT
            e.src_ticker, e.counterparty_key, e.direction,
            NULL::VARCHAR                                AS dst_ticker,
            e.counterparty_name, e.node_type, e.weight,
            e.n_runs_seen, t.n_runs_total, e.n_verified,
            -- multiplicative: any factor at zero zeroes the edge, so a repeated
            -- but unverified quote is not rescued by its repetition (§2.3).
            e.strength_weight
              * (e.n_verified::DOUBLE / e.n_runs_seen)
              * (e.n_runs_seen::DOUBLE / t.n_runs_total) AS confidence,
            e.first_seen, e.last_seen, e.accession
        FROM edges e JOIN totals t USING (src_ticker, accession)
        ORDER BY e.src_ticker, e.n_runs_seen DESC, e.direction, e.counterparty_key
    """)


def supply_chain_edges(db_path: str = None) -> List[dict]:
    """Read the derived graph. Ensures the view exists first (idempotent DDL)."""
    path = db_path or str(config.DUCKDB_PATH)
    ensure_tables(path)
    conn = db.connect(path, read_only=True)
    try:
        rows = conn.execute("SELECT * FROM supply_chain_edges").fetchall()
        cols = [d[0] for d in conn.description]
    finally:
        conn.close()
    return [dict(zip(cols, r)) for r in rows]


_RELATION_COLS = (
    'run_id', 'rel_idx', 'src_ticker', 'report_date', 'accession', 'direction',
    'counterparty_name', 'counterparty_key', 'aggregate_count', 'pct_revenue',
    'quote', 'source_ref', 'strength', 'quote_verified')
_CLAIM_COLS = (
    'run_id', 'claim_idx', 'src_ticker', 'report_date', 'accession', 'claim_type',
    'label', 'quote', 'source_ref', 'strength', 'quote_verified')


def _comprehend(table: str, row_fn, columns: Tuple[str, ...], path: str,
                force: bool) -> Tuple[int, int]:
    """Log every ingested run's rows into `table`. Returns (runs_processed, rows).

    Re-running writes nothing — a run already in `table` is skipped. A run whose
    agent fell back to free text has no rows to key on, so it is re-read (one JSON
    parse) and counted as processed every time; that is the honest reading of
    "processed", not a leak.

    `force` re-scores runs already logged. Not speculative: the fidelity checker
    was corrected twice on 2026-07-20 (quote-glyph folding, then layout folding),
    and each fix changed stored verdicts that would otherwise stay wrong forever.
    A checker change is the one reason to recompute.

    `table` and `columns` are module constants, never user input — the f-strings
    are safe.
    """
    collist = ', '.join(columns)
    placeholders = ', '.join(['?'] * len(columns))
    conn = db.connect(path)
    try:
        runs = conn.execute("""
            SELECT run_id, ticker, report_date, key_facts_json
            FROM research_report_runs
            WHERE key_facts_json IS NOT NULL
            ORDER BY report_date, ticker
        """).fetchall()
        done = {r[0] for r in conn.execute(
            f"SELECT DISTINCT run_id FROM {table}").fetchall()}

        processed = written = 0
        for run_id, ticker, report_date, key_facts_json in runs:
            if run_id in done and not force:
                continue
            rows = row_fn(run_id, ticker, report_date, key_facts_json)
            if force:
                conn.execute(f"DELETE FROM {table} WHERE run_id = ?", [run_id])
            processed += 1
            for r in rows:
                conn.execute(
                    f"INSERT INTO {table} ({collist}) VALUES ({placeholders})",
                    [r[c] for c in columns])
                written += 1
        conn.commit()
    finally:
        conn.close()

    logger.info(f"[Comprehension] {table}: {processed} runs -> {written} rows")
    return (processed, written)


def comprehend_runs(db_path: str = None, force: bool = False) -> Tuple[int, int]:
    """Log the relations of every ingested run into `research_relations`."""
    path = db_path or str(config.DUCKDB_PATH)
    ensure_tables(path)
    return _comprehend('research_relations', _rows_for_run, _RELATION_COLS, path, force)


def comprehend_claims(db_path: str = None, force: bool = False) -> Tuple[int, int]:
    """Log the non-relation evidenced claims of every run into `research_claims`.

    The sibling of `comprehend_runs` for everything that is not a counterparty
    edge — watch items, risks, choke points, moat, cost structure — so the quote
    gate covers the claims `research_relations` structurally cannot see.
    """
    path = db_path or str(config.DUCKDB_PATH)
    ensure_tables(path)
    return _comprehend('research_claims', _claim_rows_for_run, _CLAIM_COLS, path, force)


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
