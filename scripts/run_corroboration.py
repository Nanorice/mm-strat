"""Corroboration harness — run a name n times against the same cached filing.

Step 4 of the knowledge-base build order (`plans/knowledge_base_schema.md` §3.4).
Its only job is to make `n_runs_total > 1`, without which `corroboration_rate` is
trivially 1.0 and every confidence number is decoration.

The input is deterministic on our side: `fetch_10k` reads the EDGAR cache, so
repeated runs see byte-identical filing text and any variation in the output is
the model's, not the corpus's. That is the whole point — this measures extraction
stability, so a run that re-fetches the filing would be measuring two things.

    python scripts/run_corroboration.py GLW MRVL RKLB --runs 2

Each run costs ~$0.10. `--report-only` skips the producer and just re-reads what
is already in the DB.
"""

import argparse
import os
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from src import db
from src.research_comprehension import comprehend_runs
from src.research_report_engine import ResearchReportEngine

PRODUCER_DIR = Path(os.getenv(
    'PRODUCER_DIR', Path.home() / 'Documents' / 'projects' / 'TradingAgents'))


def run_producer(ticker: str) -> bool:
    """One producer run. Returns False on a non-zero exit, without raising —
    a single failed run must not lose the runs that already landed."""
    python = PRODUCER_DIR / '.venv' / 'Scripts' / 'python.exe'
    if not python.exists():
        raise FileNotFoundError(
            f"producer venv not found at {python}. Set PRODUCER_DIR, or see "
            f"docs/architecture/producer_deployment.md §3.2.")

    started = time.monotonic()
    proc = subprocess.run(
        [str(python), 'run_unattended.py', ticker],
        cwd=str(PRODUCER_DIR), capture_output=True, text=True,
        encoding='utf-8', errors='replace',
    )
    elapsed = time.monotonic() - started
    if proc.returncode != 0:
        print(f"   [ERR] {ticker} exit {proc.returncode} after {elapsed:.0f}s",
              flush=True)
        print((proc.stderr or '')[-600:], flush=True)
        return False
    print(f"   [OK] {ticker} in {elapsed:.0f}s", flush=True)
    return True


def agreement(db_path: str = None) -> dict:
    """Per (ticker, accession): how many runs saw each counterparty.

    `n_runs_total` is scoped to (src_ticker, accession), not to the ticker.
    Agreement only means something across runs of the *same filing* — comparing a
    2025 10-K run against a 2026 one is a time series, not corroboration, and
    conflating them makes a stale edge look well-supported.
    """
    conn = db.connect(db_path or str(config.DUCKDB_PATH), read_only=True)
    try:
        totals = dict(conn.execute("""
            SELECT src_ticker || '|' || accession, COUNT(DISTINCT run_id)
            FROM research_relations WHERE accession IS NOT NULL
            GROUP BY 1
        """).fetchall())
        rows = conn.execute("""
            SELECT src_ticker, accession, direction, counterparty_key,
                   any_value(counterparty_name)             AS name,
                   COUNT(DISTINCT run_id)                   AS n_seen,
                   COUNT(*) FILTER (quote_verified)         AS n_verified
            FROM research_relations WHERE accession IS NOT NULL
            GROUP BY src_ticker, accession, direction, counterparty_key
            ORDER BY src_ticker, n_seen DESC, direction, counterparty_key
        """).fetchall()
    finally:
        conn.close()

    out = defaultdict(list)
    for tkr, acc, direction, key, name, n_seen, n_ver in rows:
        out[(tkr, acc, totals.get(f'{tkr}|{acc}', 0))].append(
            {'direction': direction, 'key': key, 'name': name,
             'n_seen': n_seen, 'n_verified': n_ver})
    return out


def print_report(data: dict) -> None:
    for (tkr, acc, total), items in sorted(data.items()):
        stable = sum(1 for i in items if i['n_seen'] == total)
        print(f"\n{'='*74}\n{tkr}  accession={acc}  runs={total}  "
              f"distinct counterparties={len(items)}  seen in every run={stable}",
              flush=True)
        if total < 2:
            print("  (single run — corroboration_rate would be trivially 1.0)",
                  flush=True)
        for i in items:
            bar = f"{i['n_seen']}/{total}"
            print(f"   {bar:>5}  verified {i['n_verified']:>2}  "
                  f"{i['direction']:11s} {i['name'] or i['key']}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('tickers', nargs='+')
    ap.add_argument('--runs', type=int, default=2,
                    help='additional producer runs per ticker (default 2)')
    ap.add_argument('--report-only', action='store_true',
                    help='skip the producer; re-read what is already ingested')
    args = ap.parse_args()

    if not args.report_only:
        total = len(args.tickers) * args.runs
        print(f"{total} producer runs (~${0.10 * total:.2f}), "
              f"{args.runs} per name\n", flush=True)
        for ticker in args.tickers:
            for n in range(1, args.runs + 1):
                print(f"[{ticker} {n}/{args.runs}] running...", flush=True)
                run_producer(ticker)

        print("\nIngesting...", flush=True)
        print("  ", ResearchReportEngine().ingest_drop_dir(), flush=True)
        print("  comprehend:", comprehend_runs(), flush=True)

    print_report(agreement())


if __name__ == '__main__':
    main()
