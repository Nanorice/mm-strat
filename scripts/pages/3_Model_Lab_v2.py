"""Model Lab (uplift) — C1 stage page: registry browser + population EDA + label cone.

Shadow-nav revision of 3_Model_Lab.py. The live page is a card browser with no
population view. This adds, per cone_and_studio_design.md §1/§2:
  - C1 currency banner — this whole page is a LABEL claim ('the label ranks the
    tail'), never a trade-edge claim ('this makes money'). That's the Studio (C3).
  - Funnel tab — full → trend_ok → breakout compression, score dist, churn/tenure.
  - Label-outcome tab — forward-return distribution + regime clustering + sector/size.
    (Both surface the sprint_summary EDA PNGs — data/model_output_eda/sprint_summary.)
  - Label cone tab — the buy-and-hold equity fan (basket_paths), rendered live from
    cone_cells (engine='basket_paths'). Different object from the strategy cone;
    metric is fwd_return, NOT Sharpe. Framing: the TAIL is the signal, median misleads.

Tier 2 (workshop) — dense/mono, deliberately NOT theta-styled. The live 3_Model_Lab.py
is untouched until switch-over (hard constraint §6).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from dashboard_utils import load_models_table, load_cone_cells

MODEL_CARDS_DIR = ROOT / "model_cards"
EDA_DIR = ROOT / "data" / "model_output_eda" / "sprint_summary"

# Home-run threshold — a fwd-return tail event (fwd100 > 30% in the sprint EDA).
HOME_RUN = 0.30


# ── artifacts_path resolution (copied verbatim from the live page) ────────────

def _model_card_slug(artifacts_path: str | None) -> str | None:
    if not artifacts_path:
        return None
    parts = Path(artifacts_path.replace("\\", "/")).parts
    if len(parts) < 2:
        return None
    return f"{parts[-2]}_{parts[-1]}"


def _resolve_artifacts_dir(artifacts_path: str | None) -> Path | None:
    if not artifacts_path:
        return None
    parts = Path(artifacts_path.replace("\\", "/")).parts
    if "models" in parts:
        rel = Path(*parts[parts.index("models"):])
        p = ROOT / rel
    else:
        p = Path(artifacts_path)
        if not p.is_absolute():
            p = ROOT / artifacts_path
    return p if p.exists() else None


# ── C1 currency banner ───────────────────────────────────────────────────────

def render_c1_banner() -> None:
    st.info(
        "**Currency C1 · label claim (buy-and-hold proxy).** Everything here asks "
        "*is the label worth anything on the population?* — it licenses *\"the label "
        "ranks the tail\"*, **never** *\"this makes money\"*. That is the Studio's "
        "question (C3, exit-P&L). The **label cone is a buy-and-hold fan, not a "
        "backtest** — no slots, no rotation. **The tail is the signal; the median "
        "misleads** (the sprint's own conclusion — a median-first read here would "
        "contradict it).",
        icon="🔵",
    )


# ── PNG-group tabs (Funnel, Label outcome) ───────────────────────────────────

def _render_png_group(stems: list[str], captions: dict[str, str]) -> None:
    """Surface pre-rendered sprint_summary EDA PNGs. Same pattern as the live
    page's _render_plots_tab — the EDA is saved matplotlib, not recomputed here."""
    if not EDA_DIR.exists():
        st.info(f"No EDA artifacts on this host (`{EDA_DIR.relative_to(ROOT)}` "
                "missing — dev-box research output, not synced to the remote).")
        return
    shown = 0
    for stem in stems:
        png = EDA_DIR / f"{stem}.png"
        if not png.exists():
            continue
        st.markdown(f"**{captions.get(stem, stem)}**")
        st.image(str(png), use_container_width=True)
        shown += 1
    if shown == 0:
        st.info("No matching EDA PNGs found for this tab.")


FUNNEL_STEMS = ["s1_funnel", "s1_scores", "s1_churn_count", "s1_tenure", "s1c_supply_gauge"]
FUNNEL_CAPS = {
    "s1_funnel": "The funnel — full → trend_ok → breakout (~100× compression) + supply drift",
    "s1_scores": "prob_elite distribution per tier — is breakout just the high-score tail of trend?",
    "s1_churn_count": "Top-5 day-over-day overlap count (0–5), raw vs score-gated",
    "s1_tenure": "Name tenure in the top-5 — how long a name survives once it enters",
    "s1c_supply_gauge": "Breakout supply/day — the deploy-more gauge",
}

OUTCOME_STEMS = ["s2_lottery", "s2_regime_charts", "s3_sector_dist", "s3_size_rs", "q3_gated_vs_rejected"]
OUTCOME_CAPS = {
    "s2_lottery": "The lottery — forward-return distribution across 4 horizons, raw vs score-gated",
    "s2_regime_charts": "Worst-decile start-days marked against index MAs — regime clustering of the losers",
    "s3_sector_dist": "Per-sector fwd100 distribution, regime-split",
    "s3_size_rs": "Size × RS — small-cap × strong-RS has the higher HOME-RUN rate (the median inverts)",
    "q3_gated_vs_rejected": "Gated vs rejected names — what the score gate keeps out",
}


# ── Label cone (live, from cone_cells engine=basket_paths) ────────────────────

def render_label_cone() -> None:
    """The label cone: every start-day's buy-and-hold basket forward return. C1.

    NOT the strategy cone (C3, Sharpe). The metric is fwd_return; we lead with the
    HOME-RUN RATE and tail stats, not the median (design §2 — median is the wrong
    lens, the edge is a tail phenomenon). Reads cone_cells engine='basket_paths'."""
    st.subheader("Label Cone — buy-and-hold forward returns (the C1 fan)")

    try:
        allc = load_cone_cells(engine="basket_paths")
    except Exception as e:
        st.info(f"No label-cone rows — run `python scripts/build_label_cone_cache.py`. ({e})")
        return
    if allc.empty:
        st.info("No `basket_paths` rows in `cone_cells` — run "
                "`python scripts/build_label_cone_cache.py`.")
        return

    arms = sorted(allc["arm"].unique().tolist())
    default = arms.index("label_baseline") if "label_baseline" in arms else 0
    arm = st.selectbox("Fan variant (regime-gate × score-gate)", arms, index=default,
                       key="ml2_label_arm")
    c = allc[allc["arm"] == arm].sort_values("start")
    if c.empty:
        st.info("No cells for this variant.")
        return

    ret = c["total_return"].dropna()  # fwd_return; sharpe is NULL for basket_paths
    home_run_rate = float((ret > HOME_RUN).mean() * 100)
    median = float(ret.median())
    mean = float(ret.mean())
    p95 = float(ret.quantile(0.95))
    pct_neg = float((ret < 0).mean() * 100)

    # Tail-first tiles: home-run rate leads, median demoted to a contrast.
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric(f"Home-run rate (>{HOME_RUN:.0%})", f"{home_run_rate:.0f}%",
              help="Share of start-days whose basket returned >30% — the TAIL, the signal.")
    m2.metric("p95 return", f"{p95:+.0%}", help="95th-percentile start-day — the upside tail.")
    m3.metric("Mean", f"{mean:+.1%}", help="Mean is tail-sensitive — read WITH the home-run rate.")
    m4.metric("Median (misleading)", f"{median:+.1%}",
              help="The median is the WRONG lens — the edge is a tail phenomenon, "
                   "the median can invert. Shown only as a contrast.")
    m5.metric("% negative", f"{pct_neg:.0f}%")

    st.caption(f"Engine: `basket_paths` · score scale: `{c['score_scale'].iloc[0]}` "
               f"(calibrated — a gate of 0.20 is the model's ~coin-flip line, NOT raw "
               f"0.20) · {len(c)} deployed start-days · horizon 150d, SL 15%, "
               f"buy-and-hold (no rotation). **This is a C1 label proxy, not a backtest.**")

    # The fan as a fwd-return distribution — the tail made visual.
    fig = go.Figure()
    fig.add_histogram(x=ret, nbinsx=50, marker_color="#5b6cff")
    fig.add_vline(x=0, line=dict(color="#999", width=1))
    fig.add_vline(x=HOME_RUN, line=dict(color="#2e7d32", dash="dash"),
                  annotation_text=f"home-run {HOME_RUN:.0%}", annotation_position="top")
    fig.add_vline(x=median, line=dict(color="#c62828", dash="dot"),
                  annotation_text=f"median {median:+.1%}", annotation_position="bottom")
    fig.update_layout(
        title=f"Start-day basket forward return — {arm} (the lottery)",
        height=320, xaxis_title="Basket fwd return", xaxis_tickformat=".0%",
        yaxis_title="# start-days", margin=dict(l=40, r=20, t=50, b=30),
    )
    st.plotly_chart(fig, use_container_width=True)

    # fwd_return over start date — the regime ride (which eras threw home-runs).
    cc = c.dropna(subset=["total_return"]).copy()
    cc["start_dt"] = pd.to_datetime(cc["start"])
    fig2 = go.Figure()
    fig2.add_scatter(x=cc["start_dt"], y=cc["total_return"], mode="markers",
                     marker=dict(size=5, color="#5b6cff"), name="start-day return")
    fig2.add_hline(y=0, line=dict(color="#999", width=1))
    fig2.add_hline(y=HOME_RUN, line=dict(color="#2e7d32", dash="dash"))
    fig2.update_layout(
        title="Forward return by start date — the regime ride (home-runs cluster in eras)",
        height=300, xaxis_title="Start date", yaxis_title="Basket fwd return",
        yaxis_tickformat=".0%", margin=dict(l=40, r=20, t=50, b=30),
    )
    st.plotly_chart(fig2, use_container_width=True)

    st.caption("Each point is one start-day's basket (top-5 by calibrated prob_elite, "
               "held to exit). Home-runs cluster in regime eras — a single start-date "
               "is one draw from this fan, never the verdict "
               "(project_champion_starttime_dependent).")

    # A pre-rendered fan overlay exists too — the actual equity paths, aligned at x=0.
    fan_png = EDA_DIR / "s5_fan.png"
    if fan_png.exists():
        with st.expander("Equity-path overlay (every start-day's path, aligned at entry)"):
            st.image(str(fan_png), use_container_width=True)
            st.caption("The 4 gated variants — a curve ending early shows the basket "
                       "fully exiting (the 'when do we stop' variable made visual).")


# ── registry table + card/plots/specs/diff tabs (copied from live page) ──────

def _render_registry_table(models: pd.DataFrame) -> str | None:
    st.subheader("Model Registry")
    fc1, fc2 = st.columns([1, 1])
    with fc1:
        statuses = ["All"] + sorted(models["status_flag"].dropna().unique().tolist())
        status_filter = st.selectbox("Status", statuses, index=0, key="ml2_status")
    with fc2:
        fvs = ["All"] + sorted(models["feature_version"].dropna().unique().tolist())
        fv_filter = st.selectbox("Feature version", fvs, index=0, key="ml2_fv")

    df = models.copy()
    if status_filter != "All":
        df = df[df["status_flag"] == status_filter]
    if fv_filter != "All":
        df = df[df["feature_version"] == fv_filter]
    if df.empty:
        st.info("No models match the filters.")
        return None

    show_cols = ["version_id", "status_flag", "model_type", "feature_version",
                 "training_date", "dataset_rows", "accuracy", "weighted_f1", "macro_f1"]
    table = df[show_cols].rename(columns={
        "version_id": "Version", "status_flag": "Status", "model_type": "Type",
        "feature_version": "Feat. Ver.", "training_date": "Trained",
        "dataset_rows": "Rows", "accuracy": "Acc",
        "weighted_f1": "wF1", "macro_f1": "macroF1",
    })
    styled = table.style
    for col in ["Acc", "wF1", "macroF1"]:
        if col in table.columns:
            styled = styled.format("{:.3f}", subset=[col], na_rep="—")
    if "Rows" in table.columns:
        styled = styled.format("{:,.0f}", subset=["Rows"], na_rep="—")
    st.dataframe(styled, use_container_width=True, height=340, hide_index=True)

    return st.selectbox("Select a model to inspect", df["version_id"].tolist(),
                        index=0, key="ml2_selected")


def _render_overview(row: pd.Series, art_dir: Path | None) -> None:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Status", row["status_flag"] or "—")
    c2.metric("Rows", f"{int(row['dataset_rows']):,}" if pd.notna(row["dataset_rows"]) else "—")
    c3.metric("Trained", str(row["training_date"]) if pd.notna(row["training_date"]) else "—")
    c4.metric("Type", row["model_type"] or "—")
    c5, c6, c7 = st.columns(3)
    c5.metric("Accuracy", f"{row['accuracy']:.3f}" if pd.notna(row["accuracy"]) else "—")
    c6.metric("Weighted F1", f"{row['weighted_f1']:.3f}" if pd.notna(row["weighted_f1"]) else "—")
    c7.metric("Macro F1", f"{row['macro_f1']:.3f}" if pd.notna(row["macro_f1"]) else "—")
    st.caption(f"Artifacts: `{row['artifacts_path']}`")
    if art_dir is None:
        st.warning("Artifacts directory does not exist on disk — metadata only.")
    else:
        st.caption(f"Resolved to: `{art_dir}` — "
                   f"{sum(1 for _ in art_dir.rglob('*') if _.is_file())} files")


def _render_model_card_tab(row: pd.Series) -> None:
    slug = _model_card_slug(row.get("artifacts_path"))
    if slug is None:
        st.info("No artifacts_path — cannot resolve a model card.")
        return
    html_path = MODEL_CARDS_DIR / f"{slug}.html"
    if not html_path.exists():
        st.info(f"No model card at `{html_path.relative_to(ROOT)}`.")
        st.caption(f"Build: `python -m src.evaluation.model_card.build "
                   f"--model {slug.replace('_', '/', 1)}`")
        return
    st.caption(f"📄 `{html_path.relative_to(ROOT)}` ({html_path.stat().st_size / 1024:.0f} KB)")
    try:
        components.html(html_path.read_text(encoding="utf-8"), height=900, scrolling=True)
    except OSError as e:
        st.error(f"Could not read model card HTML: {e}")


PLOT_GROUPS = [
    ("Performance", ["confusion_matrix", "confusion_matrix_normalized",
                     "roc_curves", "pr_curves", "topk_precision"]),
    ("Calibration", ["calibration_curves", "probability_distributions", "threshold_sweep"]),
    ("Stability", ["temporal_stability", "class_distribution"]),
    ("Features", ["feature_importance"]),
]


def _render_plots_tab(art_dir: Path | None) -> None:
    if art_dir is None:
        st.info("No artifacts directory.")
        return
    eval_dir = art_dir / "evaluation"
    search_dir = eval_dir if eval_dir.exists() else art_dir
    pngs = sorted(search_dir.rglob("*.png"))
    if not pngs:
        st.info(f"No PNGs under `{search_dir.relative_to(ROOT)}`.")
        return
    by_stem = {p.stem: p for p in pngs}
    consumed: set[str] = set()
    for group_label, stems in PLOT_GROUPS:
        members = [(s, by_stem[s]) for s in stems if s in by_stem]
        if not members:
            continue
        st.markdown(f"**{group_label}**")
        cols = st.columns(2)
        for i, (_, png) in enumerate(members):
            with cols[i % 2]:
                st.image(str(png), caption=png.stem.replace("_", " "), use_container_width=True)
            consumed.add(png.stem)
    other = [p for p in pngs if p.stem not in consumed]
    if other:
        st.markdown("**Other**")
        cols = st.columns(2)
        for i, png in enumerate(other):
            with cols[i % 2]:
                st.image(str(png), caption=str(png.relative_to(search_dir)),
                         use_container_width=True)


def _render_specs_tab(row: pd.Series) -> None:
    raw = row.get("specs_json")
    if not raw:
        st.info("No specs_json in registry.")
        return
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError) as e:
        st.error(f"Could not parse specs_json: {e}")
        st.code(str(raw))
        return
    st.json(parsed, expanded=2)


def _render_diff_tab(row: pd.Series, art_dir: Path | None) -> None:
    if art_dir is None:
        st.info("No artifacts directory.")
        return
    diffs_dir = art_dir / "diffs"
    if not diffs_dir.exists():
        st.info("No `diffs/` directory for this model.")
        st.code(f"python scripts/model_diff.py {row['version_id']} <other_version_id>",
                language="bash")
        return
    diff_files = sorted(diffs_dir.glob("*.txt"))
    if not diff_files:
        st.info("`diffs/` exists but contains no .txt files.")
        return
    choice = st.selectbox("Diff file", [d.name for d in diff_files], key="ml2_diff")
    try:
        st.code((diffs_dir / choice).read_text(encoding="utf-8"), language="diff")
    except OSError as e:
        st.error(f"Could not read diff: {e}")


def _render_report_md_tab(art_dir: Path | None) -> None:
    if art_dir is None:
        st.info("No artifacts directory.")
        return
    eval_dir = art_dir / "evaluation"
    search_dir = eval_dir if eval_dir.exists() else art_dir
    reports = sorted(search_dir.glob("report_*.md"), reverse=True)
    if not reports:
        st.info("No `report_*.md` files found.")
        return
    choice = st.selectbox("Report file", [r.name for r in reports], key="ml2_report")
    try:
        st.markdown((search_dir / choice).read_text(encoding="utf-8"))
    except OSError as e:
        st.error(f"Could not read report: {e}")


# ── Page entrypoint ──────────────────────────────────────────────────────────

st.title("Model Lab")
render_c1_banner()
st.caption("Browse registered models · population EDA · label cone. "
           "Read-only — promotion is CLI-only. Tier 2 (workshop).")

models = load_models_table()
if models.empty:
    st.warning("Registry is empty.")
    st.stop()

selected = _render_registry_table(models)
if selected is None:
    st.stop()

st.markdown("---")
row = models[models["version_id"] == selected].iloc[0]
art_dir = _resolve_artifacts_dir(row["artifacts_path"])
st.subheader(f"Selected: `{selected}`")

tabs = st.tabs(["Overview", "Model Card", "Funnel", "Label outcome",
                "Label cone", "Plots", "Report (MD)", "Specs", "Diff"])
with tabs[0]:
    _render_overview(row, art_dir)
with tabs[1]:
    _render_model_card_tab(row)
with tabs[2]:
    st.caption("The selection funnel — what pool are we actually picking from? "
               "(sprint consolidation EDA §1)")
    _render_png_group(FUNNEL_STEMS, FUNNEL_CAPS)
with tabs[3]:
    st.caption("Forward-return distribution + where the losers cluster. C1 — a label "
               "claim, not a trade result. (EDA §2/§3)")
    _render_png_group(OUTCOME_STEMS, OUTCOME_CAPS)
with tabs[4]:
    render_label_cone()
with tabs[5]:
    _render_plots_tab(art_dir)
with tabs[6]:
    _render_report_md_tab(art_dir)
with tabs[7]:
    _render_specs_tab(row)
with tabs[8]:
    _render_diff_tab(row, art_dir)
