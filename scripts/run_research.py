"""Digest producer reports that have landed in the drop dir:
ingest -> comprehend -> supply_chain_edges, then print the graph.

    python scripts/run_research.py             # digest everything new
    python scripts/run_research.py TBI AMD SHC  # ...and summarise just these

The producer runs separately (its own repo + venv + spend, ~15 min / ~$0.10 a
name); this is the mm-strat side and is free + idempotent — ingest and
comprehend both no-op on a run_id already seen, so re-running is safe.

The shortlist selector that would *choose* the tickers ([1] in
agentic_digestion_layer.md) is not built, so the list is passed by hand. This
script is that hand-off, for now.

Requires the DuckDB write lock — close the Streamlit dashboard first, or the
ingest step fails with "used by another process".
"""

import argparse
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')  # counterparty names carry accents (Kinéis)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.research_comprehension import comprehend_runs, supply_chain_edges
from src.research_report_engine import ResearchReportEngine


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('tickers', nargs='*', help='limit the edge summary to these')
    args = ap.parse_args()
    tickers = {t.upper() for t in args.tickers}

    print('ingest:    ', ResearchReportEngine().ingest_drop_dir(), flush=True)
    print('comprehend:', comprehend_runs(), flush=True)

    edges = supply_chain_edges()
    if tickers:
        edges = [e for e in edges if e['src_ticker'] in tickers]
    scope = f" for {sorted(tickers)}" if tickers else ""
    print(f"\n{len(edges)} edges{scope}", flush=True)
    for e in edges:
        conf = '   -' if e['confidence'] is None else f"{e['confidence']:.2f}"
        seen = f"{e['n_runs_seen']}/{e['n_runs_total']}"
        print(f"  {e['src_ticker']:6} {e['direction']:11} {seen:>5} conf {conf:>5}  "
              f"{e['counterparty_name'] or e['counterparty_key']}", flush=True)


if __name__ == '__main__':
    main()
