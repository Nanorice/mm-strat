"""Model Lab — registry browser with embedded HTML report + PNG fallback.

Read-only in v1: no promote/archive buttons. Promotion remains a CLI action
via ModelRegistry().set_prod(version_id).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from dashboard_utils import load_models_table

MODEL_CARDS_DIR = ROOT / "model_cards"


def _model_card_slug(artifacts_path: str | None) -> str | None:
    """Derive the model_card filename slug from artifacts_path.

    Card files are written as `<name>_<version>.{html,json}` where
    `<name>/<version>` is the last two path components of artifacts_path
    (matches model_id in the card JSON, slashes replaced with underscores).
    """
    if not artifacts_path:
        return None
    # Normalize backslashes first: registry rows from the Windows dev box store
    # backslash paths, which a PosixPath on the cloud host treats as ONE part
    # (slug -> None). Mirror _resolve_artifacts_dir's normalization.
    parts = Path(artifacts_path.replace("\\", "/")).parts
    if len(parts) < 2:
        return None
    return f"{parts[-2]}_{parts[-1]}"


def _resolve_artifacts_dir(artifacts_path: str | None) -> Path | None:
    """Resolve artifacts_path to a local dir. Registry rows store either a
    project-relative path or a Windows-absolute one (dev box). On any host we
    re-anchor to ROOT by taking the path tail from the first 'models' segment,
    so absolute dev-box paths resolve against the synced models/ tree on cloud.
    """
    if not artifacts_path:
        return None
    parts = Path(artifacts_path.replace("\\", "/")).parts
    if "models" in parts:
        rel = Path(*parts[parts.index("models"):])  # models/.../<ver>
        p = ROOT / rel
    else:
        p = Path(artifacts_path)
        if not p.is_absolute():
            p = ROOT / artifacts_path
    return p if p.exists() else None


def _render_registry_table(models: pd.DataFrame) -> str | None:
    st.subheader("Model Registry")

    fc1, fc2 = st.columns([1, 1])
    with fc1:
        statuses = ["All"] + sorted(models["status_flag"].dropna().unique().tolist())
        status_filter = st.selectbox("Status", statuses, index=0)
    with fc2:
        fvs = ["All"] + sorted(
            models["feature_version"].dropna().unique().tolist()
        )
        fv_filter = st.selectbox("Feature version", fvs, index=0)

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
    table = df[show_cols].copy()
    rename = {
        "version_id": "Version", "status_flag": "Status", "model_type": "Type",
        "feature_version": "Feat. Ver.", "training_date": "Trained",
        "dataset_rows": "Rows", "accuracy": "Acc",
        "weighted_f1": "wF1", "macro_f1": "macroF1",
    }
    table = table.rename(columns=rename)

    styled = table.style
    for c in ["Acc", "wF1", "macroF1"]:
        if c in table.columns:
            styled = styled.format("{:.3f}", subset=[c], na_rep="—")
    if "Rows" in table.columns:
        styled = styled.format("{:,.0f}", subset=["Rows"], na_rep="—")

    st.dataframe(styled, use_container_width=True, height=340, hide_index=True)

    # Selector
    selected = st.selectbox(
        "Select a model to inspect",
        df["version_id"].tolist(),
        index=0,
        key="model_lab_selected",
    )
    return selected


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
        st.warning("Artifacts directory does not exist on disk — this model has metadata "
                   "but no rendered plots, report, or diff. Likely a stub registry entry.")
    else:
        st.caption(f"Resolved to: `{art_dir}` — "
                   f"{sum(1 for _ in art_dir.rglob('*') if _.is_file())} files")


def _render_model_card_tab(row: pd.Series) -> None:
    """Embed the Model Card HTML rendered by the evaluation framework.

    Looks for `model_cards/<slug>.html` where slug = <name>_<version> derived
    from the registry row's artifacts_path.
    """
    slug = _model_card_slug(row.get("artifacts_path"))
    if slug is None:
        st.info("No artifacts_path on this registry row — cannot resolve a model card.")
        return

    html_path = MODEL_CARDS_DIR / f"{slug}.html"
    if not html_path.exists():
        st.info(f"No model card found at `{html_path.relative_to(ROOT)}`.")
        st.caption(
            "Generate one with `python -m src.evaluation.model_card.build "
            f"--model {slug.replace('_', '/', 1)}` "
            "(replace the first `_` with `/` to get the model_id)."
        )
        return

    st.caption(
        f"📄 `{html_path.relative_to(ROOT)}` "
        f"({html_path.stat().st_size / 1024:.0f} KB)"
    )
    try:
        content = html_path.read_text(encoding="utf-8")
        components.html(content, height=900, scrolling=True)
    except OSError as e:
        st.error(f"Could not read model card HTML: {e}")


PLOT_GROUPS: list[tuple[str, list[str]]] = [
    # (group label, list of stem names ordered the way we want them displayed)
    ("Performance",  ["confusion_matrix", "confusion_matrix_normalized",
                      "roc_curves", "pr_curves", "topk_precision"]),
    ("Calibration",  ["calibration_curves", "probability_distributions",
                      "threshold_sweep"]),
    ("Stability",    ["temporal_stability", "class_distribution"]),
    ("Features",     ["feature_importance"]),
]


def _render_plots_tab(art_dir: Path | None) -> None:
    if art_dir is None:
        st.info("No artifacts directory.")
        return

    eval_dir = art_dir / "evaluation"
    search_dir = eval_dir if eval_dir.exists() else art_dir

    # Recursive — picks up sub-folder plots like evaluation/full_eval/ablation/*.png
    pngs = sorted(search_dir.rglob("*.png"))
    if not pngs:
        st.info(f"No PNGs found under `{search_dir.relative_to(ROOT)}`.")
        return

    st.caption(
        f"Plots are written by `src/evaluation/classification_evaluator.py` "
        f"(`ClassificationEvaluator.evaluate()`) during training. "
        f"Source: `{search_dir.relative_to(ROOT)}` · {len(pngs)} file(s)."
    )

    # Bucket by group. Use a stem-based lookup; whatever doesn't match a known
    # plot ends up in "Other" (preserves discoverability of new/ad-hoc plots).
    by_stem: dict[str, Path] = {p.stem: p for p in pngs}
    consumed: set[str] = set()

    for group_label, stems in PLOT_GROUPS:
        members = [(s, by_stem[s]) for s in stems if s in by_stem]
        if not members:
            continue
        st.markdown(f"**{group_label}**")
        cols = st.columns(2)
        for i, (_, png) in enumerate(members):
            with cols[i % 2]:
                st.image(str(png), caption=png.stem.replace("_", " "),
                         use_container_width=True)
            consumed.add(png.stem)

    other = [p for p in pngs if p.stem not in consumed]
    if other:
        st.markdown("**Other**")
        st.caption("Plots not in the standard groups — typically from sub-folder "
                   "evaluations like ablation studies.")
        cols = st.columns(2)
        for i, png in enumerate(other):
            with cols[i % 2]:
                label = str(png.relative_to(search_dir))
                st.image(str(png), caption=label, use_container_width=True)


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
        st.caption("To generate one, run:")
        st.code(f"python scripts/model_diff.py {row['version_id']} <other_version_id>",
                language="bash")
        return

    diff_files = sorted(diffs_dir.glob("*.txt"))
    if not diff_files:
        st.info("`diffs/` exists but contains no .txt files.")
        return

    choice = st.selectbox("Diff file", [d.name for d in diff_files])
    chosen = diffs_dir / choice
    try:
        st.code(chosen.read_text(encoding="utf-8"), language="diff")
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
    choice = st.selectbox("Report file", [r.name for r in reports])
    try:
        st.markdown((search_dir / choice).read_text(encoding="utf-8"))
    except OSError as e:
        st.error(f"Could not read report: {e}")


# ── Page entrypoint ──────────────────────────────────────────────────────────

st.title("Model Lab")
st.caption("Browse registered models · view pretrain audit · inspect plots / specs / diffs. "
           "Read-only — promotion is CLI-only in v1.")

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

tabs = st.tabs(["Overview", "Model Card", "Plots", "Report (MD)", "Specs", "Diff"])
with tabs[0]:
    _render_overview(row, art_dir)
with tabs[1]:
    _render_model_card_tab(row)
with tabs[2]:
    _render_plots_tab(art_dir)
with tabs[3]:
    _render_report_md_tab(art_dir)
with tabs[4]:
    _render_specs_tab(row)
with tabs[5]:
    _render_diff_tab(row, art_dir)
