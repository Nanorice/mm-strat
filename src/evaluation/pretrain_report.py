"""Pre-training audit assembler — thin sequencer, not a god function.

Each step is an independent call from the other Phase-1 modules; this only
orders them and emits Markdown + figures. No analysis logic lives here.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Literal, Optional

import pandas as pd

from .data_quality import DataQualityReport, run_quality_gate, warmup_clip
from .feature_signal import (
    TargetDist,
    compute_ic,
    compute_mutual_information,
    compute_redundancy,
    days_active_by_class,
    return_horizon_stats,
    target_distribution,
    weekly_ticker_activity,
)
from .html_report import build_html_report
from .training_data_loader import (
    DEFAULT_MFE_BINS,
    derive_target_class,
    load_pretrain_data,
)

logger = logging.getLogger(__name__)

# Non-feature columns to exclude before signal analysis (model_proto.ipynb cell 20,
# lowercased). Metadata + raw price + outcome/leakage columns.
METADATA_COLS = {
    "ticker", "date", "feature_version", "trade_id", "is_new_trigger",
    "company_name", "fundamental_filing_date", "fiscal_period", "entry_date",
    "ingested_at", "updated_at",
    "cached_at",  # d2_training_cache artifact — absent from v_d2_training
}
RAW_PRICE_COLS = {"open", "high", "low", "close", "volume", "entry_price", "exit_price"}
LEAKAGE_COLS = {
    "mfe_pct", "mfe_date", "mae_pct", "mae_date", "return_at_exit", "return_pct",
    "exit_date", "exit_price", "sepa_exit_date", "holding_days", "days_observed",
    "sl_triggered", "sl_date", "sl_exit_date", "sl_pct",
}
# Derived target columns — must never appear in the feature set (model_proto
# BANNED_RAW_FEATURES). Added by derive_target_class, not present in the view.
TARGET_COLS = {"target_class", "target_label"}
FORBIDDEN_PATTERNS = ("mfe", "mae", "return_at_exit", "final_", "outcome_", "exit_", "result_")

DEFAULT_OUT_DIR = Path("docs/reports")


@dataclass
class PretrainReport:
    mode: str
    n_rows: int
    n_features: int
    quality: DataQualityReport
    target_dist: Optional[TargetDist]
    ic_df: pd.DataFrame
    mi_df: pd.DataFrame
    redundant_pairs: List[tuple]
    return_stats: pd.DataFrame = field(default_factory=pd.DataFrame)
    weekly_activity: pd.DataFrame = field(default_factory=pd.DataFrame)
    days_active: pd.DataFrame = field(default_factory=pd.DataFrame)
    corr_matrix: Optional[pd.DataFrame] = None
    mfe_series: Optional[pd.Series] = None
    markdown_path: Optional[Path] = None
    html_path: Optional[Path] = None
    figure_paths: List[Path] = field(default_factory=list)


def _select_feature_cols(df: pd.DataFrame) -> List[str]:
    """Feature columns = all cols minus metadata/raw-price/leakage and
    forbidden-pattern matches (model_proto.ipynb cell 20)."""
    exclude = METADATA_COLS | RAW_PRICE_COLS | LEAKAGE_COLS | TARGET_COLS
    feats = []
    for col in df.columns:
        if col in exclude:
            continue
        if any(pat in col for pat in FORBIDDEN_PATTERNS):
            continue
        feats.append(col)
    return feats


def _fmt_pct(x: float) -> str:
    return f"{x * 100:.2f}%"


def _build_markdown(rep: PretrainReport, mfe_bins) -> str:
    q = rep.quality
    lines: List[str] = []
    lines.append(f"# Pre-Training Data Audit — {rep.mode} mode")
    lines.append("")
    lines.append(f"_Generated {datetime.now():%Y-%m-%d %H:%M}_")
    lines.append("")
    lines.append(
        f"- Rows: **{rep.n_rows:,}** | Feature columns: **{rep.n_features}** "
        f"| Quality gate: **{'PASS' if q.passed else 'FAIL'}**"
    )
    lines.append("")

    # 1. Data Quality
    lines.append("## 1. Data Quality")
    lines.append("")
    top_null = q.null_rates[q.null_rates > 0].head(20)
    if len(top_null):
        lines.append("**Top null rates (>0):**")
        lines.append("")
        lines.append("| Column | Null rate |")
        lines.append("|---|---|")
        for col, rate in top_null.items():
            flag = " ⚠️ P0" if col in q.null_p0_cols else ""
            lines.append(f"| {col} | {_fmt_pct(rate)}{flag} |")
        lines.append("")
    else:
        lines.append("No null columns. ✅")
        lines.append("")

    lines.append(f"- Zero-variance cols: {q.zero_variance_cols or 'none'}")
    lines.append(
        f"- Infinite (>10%) cols: "
        f"{ {k: _fmt_pct(v) for k, v in q.infinite_cols.items()} or 'none'}"
    )
    lines.append(
        f"- Bad tickers ({len(q.bad_tickers)}): "
        f"{', '.join(q.bad_tickers) if q.bad_tickers else 'none'}"
    )
    lines.append(
        f"- Leakage columns ({len(q.leakage_cols)}): "
        f"{', '.join(q.leakage_cols) if q.leakage_cols else 'none'}"
    )
    lines.append("")
    if q.warnings:
        lines.append("**Warnings:**")
        lines.append("")
        for w in q.warnings:
            lines.append(f"- {w}")
        lines.append("")

    # Action Required
    lines.append("### Action Required (upstream feature_pipeline.py fixes)")
    lines.append("")
    if q.action_required:
        lines.append("```")
        for a in q.action_required:
            lines.append(a)
        lines.append("```")
    else:
        lines.append("None — no P0 violations.")
    lines.append("")

    # 2. Target Distribution
    if rep.target_dist is not None:
        td = rep.target_dist
        lines.append("## 2. Target Distribution")
        lines.append("")
        lines.append(f"MFE bins: `{mfe_bins}`")
        lines.append("")
        lines.append("| Class | Count | Proportion |")
        lines.append("|---|---|---|")
        for cls in td.counts.index:
            lines.append(
                f"| {cls} | {td.counts[cls]:,} | {_fmt_pct(td.proportions[cls])} |"
            )
        lines.append("")
        lines.append(f"- Imbalance ratio (max/min): **{td.imbalance_ratio:.2f}**")
        lines.append("")

    # 3. Feature Signal
    lines.append("## 3. Feature Signal")
    lines.append("")
    if not rep.ic_df.empty:
        lines.append("**IC top 30 (Spearman vs target_class):**")
        lines.append("")
        lines.append("| Feature | IC | abs(IC) | p-value | low-signal |")
        lines.append("|---|---|---|---|---|")
        for _, r in rep.ic_df.head(30).iterrows():
            lines.append(
                f"| {r['feature']} | {r['spearman_ic']:.4f} | {r['abs_ic']:.4f} "
                f"| {r['pval']:.2e} | {'yes' if r['low_signal'] else ''} |"
            )
        lines.append("")
    if not rep.mi_df.empty:
        lines.append("**MI top 30 (mutual_info_classif):**")
        lines.append("")
        lines.append("| Feature | MI |")
        lines.append("|---|---|")
        for _, r in rep.mi_df.head(30).iterrows():
            lines.append(f"| {r['feature']} | {r['mi_score']:.4f} |")
        lines.append("")
    lines.append(f"**Redundant pairs |r| > 0.80 ({len(rep.redundant_pairs)}):**")
    lines.append("")
    if rep.redundant_pairs:
        lines.append("| Feature A | Feature B | abs(corr) |")
        lines.append("|---|---|---|")
        for a, b, v in rep.redundant_pairs[:50]:
            lines.append(f"| {a} | {b} | {v:.4f} |")
        if len(rep.redundant_pairs) > 50:
            lines.append("")
            lines.append(f"_... and {len(rep.redundant_pairs) - 50} more_")
    else:
        lines.append("None above threshold.")
    lines.append("")

    if rep.figure_paths:
        lines.append("## Figures")
        lines.append("")
        for p in rep.figure_paths:
            lines.append(f"- ![{p.stem}]({p.name})")
        lines.append("")

    return "\n".join(lines)


def run_pretrain_audit(
    mode: Literal["dense", "trades"] = "trades",
    mfe_bins=DEFAULT_MFE_BINS,
    class_names: Optional[tuple] = None,
    output_path: Optional[Path] = None,
    emit_markdown: bool = False,
    label_set_name: Optional[str] = None,
) -> PretrainReport:
    """Sequence the Phase-1 checks and emit a self-contained HTML report.

    1. load_pretrain_data(mode)
    2. trades: warmup_clip + derive_target_class
    3. run_quality_gate (raises DataQualityError on P0)
    4. trades: target_distribution + MFE/days-active/return/weekly analytics
    5. compute_ic / compute_mutual_information / compute_redundancy (+ corr matrix)
    6. assemble standalone HTML (chart-first); optional Markdown sidecar

    Args:
        mode: "dense" (t3_sepa_features, no target) or "trades" (v_d2_training).
        mfe_bins: target binning, default = notebook bins.
        output_path: HTML path. Defaults to docs/reports/pretrain_audit_<mode>_<ts>.html.
        emit_markdown: also write the legacy Markdown sidecar (default off).
    """
    df = load_pretrain_data(mode=mode)

    target_col = None
    if mode == "trades":
        df = warmup_clip(df)
        df["target_class"] = derive_target_class(df, bins=mfe_bins)
        target_col = "target_class"

    feature_cols = _select_feature_cols(df)

    quality = run_quality_gate(df, feature_cols, mode=mode)

    td = None
    ic_df = pd.DataFrame()
    mi_df = pd.DataFrame()
    redundant_pairs: List[tuple] = []
    corr_matrix: Optional[pd.DataFrame] = None
    return_stats = return_horizon_stats(df)
    weekly_activity = weekly_ticker_activity(df)
    days_active = pd.DataFrame()
    mfe_series: Optional[pd.Series] = None

    if mode == "trades":
        cn_kwargs = {"class_names": class_names} if class_names else {}
        td = target_distribution(df[target_col], **cn_kwargs)
        ic_df = compute_ic(df, feature_cols, target_col)
        mi_df = compute_mutual_information(df, feature_cols, target_col)
        corr_matrix, redundant_pairs = compute_redundancy(df, feature_cols)
        days_active = days_active_by_class(df, target_col=target_col, **cn_kwargs)
        if "mfe_pct" in df.columns:
            mfe_series = df.drop_duplicates(
                subset=["trade_id"] if "trade_id" in df.columns else None
            )["mfe_pct"]

    rep = PretrainReport(
        mode=mode,
        n_rows=len(df),
        n_features=len(feature_cols),
        quality=quality,
        target_dist=td,
        ic_df=ic_df,
        mi_df=mi_df,
        redundant_pairs=redundant_pairs,
        return_stats=return_stats,
        weekly_activity=weekly_activity,
        days_active=days_active,
        corr_matrix=corr_matrix,
        mfe_series=mfe_series,
    )

    # Resolve output paths (HTML is the primary artifact)
    if output_path is None:
        DEFAULT_OUT_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        ls_suffix = f"_{label_set_name}" if label_set_name and label_set_name != "default" else ""
        output_path = DEFAULT_OUT_DIR / f"pretrain_audit_{mode}{ls_suffix}_{ts}.html"
    else:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

    build_html_report(
        mode=mode,
        n_rows=rep.n_rows,
        n_features=rep.n_features,
        quality=quality,
        target_dist=td,
        mfe_series=mfe_series,
        return_stats=return_stats,
        weekly_activity=weekly_activity,
        days_active=days_active,
        corr_matrix=corr_matrix,
        redundant_pairs=redundant_pairs,
        ic_df=ic_df,
        mi_df=mi_df,
        output_path=output_path,
    )
    rep.html_path = output_path
    logger.info("Pre-train audit (HTML) written: %s", output_path)

    if emit_markdown:
        md_path = output_path.with_suffix(".md")
        md_path.write_text(_build_markdown(rep, mfe_bins), encoding="utf-8")
        rep.markdown_path = md_path
        logger.info("Pre-train audit (Markdown sidecar) written: %s", md_path)

    return rep
