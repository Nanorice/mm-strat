#!/usr/bin/env python3
"""
Run the pre-training data audit and emit a self-contained HTML report.

Usage:
    python scripts/run_pretrain_audit.py --mode trades
    python scripts/run_pretrain_audit.py --mode dense
    python scripts/run_pretrain_audit.py --mode trades --out docs/reports/audit.html
    python scripts/run_pretrain_audit.py --mode trades --mfe-bins "2,10,30"
    python scripts/run_pretrain_audit.py --mode trades --markdown
"""

import argparse
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import numpy as np

from src.evaluation.data_quality import DataQualityError
from src.evaluation.pretrain_report import run_pretrain_audit
from src.evaluation.training_data_loader import DEFAULT_MFE_BINS


def _parse_mfe_bins(spec: str):
    """`"2,10,30"` -> notebook-style bins [(-inf,2,0),(2,10,1),(10,30,2),(30,inf,3)]."""
    edges = [float(x) for x in spec.split(",")]
    bounds = [-np.inf, *edges, np.inf]
    return [
        (bounds[i], bounds[i + 1], i)
        for i in range(len(bounds) - 1)
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Pre-training data audit")
    parser.add_argument(
        "--mode", choices=["dense", "trades"], default="trades",
        help="dense=v_d2_features (no target); trades=v_d2_training (default)",
    )
    parser.add_argument(
        "--mfe-bins", type=str, default=None,
        help='Comma-separated bin edges, e.g. "2,10,30" (default: notebook bins)',
    )
    parser.add_argument(
        "--out", type=str, default=None,
        help="Output HTML path (default: docs/reports/pretrain_audit_<mode>_<ts>.html)",
    )
    parser.add_argument(
        "--markdown", action="store_true",
        help="Also write the legacy Markdown sidecar next to the HTML",
    )
    args = parser.parse_args()

    mfe_bins = _parse_mfe_bins(args.mfe_bins) if args.mfe_bins else DEFAULT_MFE_BINS
    out = Path(args.out) if args.out else None

    print(f"[AUDIT] Running pre-train audit (mode={args.mode})...")
    try:
        rep = run_pretrain_audit(
            mode=args.mode, mfe_bins=mfe_bins, output_path=out,
            emit_markdown=args.markdown,
        )
    except DataQualityError as e:
        print(f"[FAIL] {e}")
        return 1

    print(f"[OK] {rep.n_rows:,} rows, {rep.n_features} features, "
          f"quality={'PASS' if rep.quality.passed else 'FAIL'}")
    if rep.quality.bad_tickers:
        print(f"   Bad tickers: {len(rep.quality.bad_tickers)}")
    if rep.quality.leakage_cols:
        print(f"   Leakage cols: {rep.quality.leakage_cols}")
    print(f"[REPORT] {rep.html_path}")
    if rep.markdown_path:
        print(f"   markdown: {rep.markdown_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
