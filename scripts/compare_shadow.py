"""Module A — historical prod-vs-shadow comparison report.

A1 (live): static ranking comparison over a flexible date range. Ranking is how
stocks are selected, so this answers the core question — do prod and shadow rank
the same universe differently, and by how much? Reads already-materialized RAW
scores from daily_predictions (no model loaded, no outcomes, leakage-free).

A2 (placeholder): strategy-backtest comparison — run a baseline strategy under
each model's ranking and compare realized performance. Blocked on backtest
finalization; emitted as a stub section so the report shape is stable.

Both models' scores must already be in daily_predictions. Materialize the shadow
first if needed:
    python scripts/backfill_daily_predictions.py --model-version-id <shadow_id>

Usage:
    python scripts/compare_shadow.py                          # prod vs registered shadow, last 1yr
    python scripts/compare_shadow.py --start 2016-01-01       # last decade
    python scripts/compare_shadow.py --shadow <id> --prod <id>
    python scripts/compare_shadow.py --output docs/session_logs/sprint_12/shadow_report.md
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from src.evaluation.shadow_compare import (
    ComparisonResult,
    compare_rankings,
    load_cohort_scores,
)
from src.model_registry import ModelRegistry

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("compare_shadow")

DB_PATH = str(config.DATA_DIR / "market_data.duckdb")
DEFAULT_OUTPUT = "docs/session_logs/sprint_12/shadow_comparison_report.md"


def _render_a2_placeholder() -> str:
    return (
        "## A2 — Strategy Backtest Comparison\n\n"
        "> [!NOTE]\n"
        "> **Placeholder.** Blocked on backtest finalization. Once the baseline\n"
        "> strategy is locked, this section will run it under each model's ranking\n"
        "> and report realized performance (return, drawdown, hit-rate) plus the\n"
        "> calibrated precision@T metrics. Calibration / win-label / OOS concerns\n"
        "> live here, not in A1.\n"
    )


def render_report(res: ComparisonResult, start: str, end: str) -> str:
    lines: list[str] = []
    lines.append("# Shadow Comparison Report (Module A)\n")
    lines.append(
        f"Prod `{res.prod_version_id}` vs Shadow `{res.shadow_version_id}` · "
        f"cohort `{res.cohort}` · {start} → {end}\n"
    )

    lines.append("## A1 — Static Ranking Comparison\n")
    if res.n_dates == 0:
        lines.append(
            "> [!WARNING]\n> No overlapping scored dates for both models in this "
            "range. Materialize the shadow with `backfill_daily_predictions.py "
            "--model-version-id <shadow>` then re-run.\n"
        )
        lines.append("\n---\n\n" + _render_a2_placeholder())
        return "\n".join(lines)

    lines.append(
        f"- Overlapping scored dates: **{res.n_dates}** "
        f"(prod rows: {res.n_rows_prod:,}, shadow rows: {res.n_rows_shadow:,})\n"
    )
    lines.append(
        "| Metric | Value | Reading |\n|:--|--:|:--|\n"
        f"| Mean Spearman (rank corr) | {res.mean_spearman:.3f} | "
        "1.0 = identical ordering; lower = the models sort the universe differently |\n"
        f"| Mean Jaccard @ top-10 | {res.mean_jaccard_at_10:.3f} | "
        "overlap of the two daily top-10 selection lists; 1.0 = same picks |\n"
        f"| Total per-day rank disagreements | {res.total_disagreements:,} | "
        "ticker-days where the rank differs at all |\n"
    )

    if res.mean_jaccard_at_10 >= 0.95 and res.mean_spearman >= 0.98:
        lines.append(
            "\n> [!NOTE]\n> The two models rank near-identically — the shadow "
            "would select essentially the same stocks. A switch is low-impact.\n"
        )

    lines.append("\n### Per-day divergence (tail)\n")
    tail = res.per_day.tail(15).to_markdown(index=False)
    lines.append(tail + "\n")

    lines.append("\n### Largest ranking disagreements\n")
    if res.top_disagreements.empty:
        lines.append("_None — the models agree on every ticker's rank._\n")
    else:
        disp = res.top_disagreements.copy()
        for c in ("prod_prob", "shadow_prob"):
            if c in disp.columns:
                disp[c] = disp[c].round(4)
        lines.append(disp.to_markdown(index=False) + "\n")

    lines.append("\n---\n\n" + _render_a2_placeholder())
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Historical prod-vs-shadow comparison.")
    ap.add_argument("--prod", default=None, help="Prod version_id (default: registry prod).")
    ap.add_argument("--shadow", default=None, help="Shadow version_id (default: registry shadow).")
    ap.add_argument("--cohort", default="breakout", choices=["breakout", "pre_breakout"])
    ap.add_argument("--start", default=None, help="Inclusive start YYYY-MM-DD (default: 1yr ago).")
    ap.add_argument("--end", default=None, help="Inclusive end YYYY-MM-DD (default: today).")
    ap.add_argument("--top-k", type=int, default=10)
    ap.add_argument("--output", default=DEFAULT_OUTPUT)
    args = ap.parse_args()

    reg = ModelRegistry(db_path=DB_PATH)
    prod_id = args.prod or reg.get_prod_version()
    shadow_id = args.shadow or reg.get_shadow_version()
    if not prod_id:
        logger.error("No prod model registered and --prod not given.")
        return 1
    if not shadow_id:
        logger.error("No shadow model designated and --shadow not given. "
                     "Run registry.set_shadow(<id>) first.")
        return 1
    if prod_id == shadow_id:
        logger.error("prod and shadow are the same version_id — nothing to compare.")
        return 1

    end = args.end or date.today().isoformat()
    start = args.start or (date.fromisoformat(end) - timedelta(days=365)).isoformat()

    logger.info("Comparing prod=%s vs shadow=%s [%s → %s] cohort=%s",
                prod_id, shadow_id, start, end, args.cohort)

    prod_df = load_cohort_scores(DB_PATH, prod_id, args.cohort, start, end)
    shadow_df = load_cohort_scores(DB_PATH, shadow_id, args.cohort, start, end)
    logger.info("Loaded prod=%d rows, shadow=%d rows", len(prod_df), len(shadow_df))

    res = compare_rankings(
        prod_df, shadow_df, prod_id, shadow_id, args.cohort, top_k=args.top_k
    )

    report = render_report(res, start, end)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")
    logger.info("Wrote report to %s (%d overlapping dates)", out_path, res.n_dates)
    print(f"[OK] Wrote {out_path} — {res.n_dates} dates, "
          f"mean Spearman {res.mean_spearman:.3f}, mean Jaccard@10 {res.mean_jaccard_at_10:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
