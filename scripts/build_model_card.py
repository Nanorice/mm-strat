"""CLI: build a model card for a trained model.

Usage:
  python scripts/build_model_card.py --model m01_binary/v1
  python scripts/build_model_card.py --model m01_binary/v1 --output model_cards/m01_binary_v1.html
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Make src importable when run as a script.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.evaluation.model_card.builder import ModelCardBuilder  # noqa: E402


DEFAULT_DB = ROOT / "data" / "market_data.duckdb"
DEFAULT_MODELS_DIR = ROOT / "models"
DEFAULT_OUTPUT_DIR = ROOT / "model_cards"


def _resolve_model_path(model_id: str) -> Path:
    """Accept either 'm01_binary/v1' or a full file path to model.json."""
    p = Path(model_id)
    if p.is_file():
        return p
    candidate = DEFAULT_MODELS_DIR / model_id / "model.json"
    if candidate.exists():
        return candidate
    raise FileNotFoundError(
        f"Could not resolve model_id={model_id!r}; tried {candidate}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a strategy-free model card")
    parser.add_argument("--model", required=True,
                        help="Model id (e.g. m01_binary/v1) or path to model.json")
    parser.add_argument("--output", default=None,
                        help="Output HTML path; defaults to model_cards/<slug>.html")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="Path to DuckDB file")
    parser.add_argument("--start-date", default=None)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--no-trend-ok", action="store_true",
                        help="Skip trend_ok filter (load all SEPA rows)")
    parser.add_argument("--skip-sepa-match", action="store_true",
                        help="Skip A3 v_d3_deployment reconciliation (saves ~60s; "
                             "the cache-vs-deployment match is verified by "
                             "scripts/verify_model_card_prereqs.py)")
    parser.add_argument("--feature-version", default="v3.1")
    parser.add_argument("--mode-b", action="store_true",
                        help="Build the stateful Mode B pool for Section D "
                             "(re-scores t3_sepa_features over the window — "
                             "minute-scale, cached to mode_b_cache/)")
    parser.add_argument("--mode-b-cache-dir", default=str(ROOT / "mode_b_cache"),
                        help="Directory for Mode B parquet cache "
                             "(default: mode_b_cache/)")
    parser.add_argument("--mode-b-force-recompute", action="store_true",
                        help="Ignore the Mode B parquet cache and re-score")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )

    model_path = _resolve_model_path(args.model)
    output_path = Path(args.output) if args.output else None
    output_dir = output_path.parent if output_path else DEFAULT_OUTPUT_DIR

    builder = ModelCardBuilder(
        model_id=args.model,
        model_path=model_path,
        db_path=Path(args.db),
        output_dir=output_dir,
        start_date=args.start_date,
        end_date=args.end_date,
        apply_trend_ok_filter=not args.no_trend_ok,
        feature_version=args.feature_version,
        skip_sepa_match=args.skip_sepa_match,
        build_mode_b=args.mode_b,
        mode_b_cache_dir=Path(args.mode_b_cache_dir),
        mode_b_force_recompute=args.mode_b_force_recompute,
    )
    card = builder.build()
    html_path, json_path = builder.render(card, html_path=output_path)
    print(f"[OK] Wrote {html_path}")
    print(f"[OK] Wrote {json_path}")
    if card.card_void:
        print("[WARN] Card is VOID due to Section A blocking failure", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
