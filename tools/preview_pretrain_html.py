"""Dev-only: cache the slow pretrain analytics once, re-render HTML fast.

First run computes everything (load + warmup + IC/MI/redundancy ~minutes) and
pickles the PretrainReport-shaped artifacts. Subsequent runs (--cached) skip
straight to build_html_report so HTML/layout tweaks iterate in seconds.

NOT part of the pipeline — delete-able. tools/ per file-structure rules.
"""

import pickle
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src.evaluation.data_quality import run_quality_gate, warmup_clip
from src.evaluation.feature_signal import (
    compute_ic,
    compute_mutual_information,
    compute_redundancy,
    days_active_by_class,
    return_horizon_stats,
    target_distribution,
    weekly_ticker_activity,
)
from src.evaluation.html_report import build_html_report
from src.evaluation.pretrain_report import _select_feature_cols
from src.evaluation.training_data_loader import (
    DEFAULT_MFE_BINS,
    derive_target_class,
    load_pretrain_data,
)

CACHE = ROOT / "docs" / "reports" / "_preview_cache.pkl"
OUT = ROOT / "docs" / "reports" / "pretrain_audit_trades_preview.html"


def compute() -> dict:
    df = load_pretrain_data(mode="trades")
    df = warmup_clip(df)
    df["target_class"] = derive_target_class(df, bins=DEFAULT_MFE_BINS)
    feats = _select_feature_cols(df)
    quality = run_quality_gate(df, feats, mode="trades")
    td = target_distribution(df["target_class"])
    ic_df = compute_ic(df, feats, "target_class")
    mi_df = compute_mutual_information(df, feats, "target_class")
    corr, pairs = compute_redundancy(df, feats)
    mfe = df.drop_duplicates(subset=["trade_id"])["mfe_pct"]
    art = dict(
        mode="trades",
        n_rows=len(df),
        n_features=len(feats),
        quality=quality,
        target_dist=td,
        mfe_series=mfe,
        return_stats=return_horizon_stats(df),
        weekly_activity=weekly_ticker_activity(df),
        days_active=days_active_by_class(df, target_col="target_class"),
        corr_matrix=corr,
        redundant_pairs=pairs,
        ic_df=ic_df,
        mi_df=mi_df,
    )
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    with open(CACHE, "wb") as fh:
        pickle.dump(art, fh)
    print(f"[CACHE] wrote {CACHE}")
    return art


def main() -> int:
    use_cache = "--cached" in sys.argv
    if use_cache and CACHE.exists():
        with open(CACHE, "rb") as fh:
            art = pickle.load(fh)
        print(f"[CACHE] loaded {CACHE}")
    else:
        art = compute()
    build_html_report(output_path=OUT, **art)
    print(f"[OK] {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
