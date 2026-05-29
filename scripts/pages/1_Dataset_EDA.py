"""Dataset EDA — embeds the pretrain audit report rendered per model.

Placeholder for a richer EDA dashboard (target distribution, class imbalance,
feature drift per label set). For now: dropdown of registered models that
have a pretrain_audit.html on disk, embed that HTML.

Replaces the retired Feature Time Series page (third-party tools like
TradingView / Finviz cover candle + indicator charting better).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from dashboard_utils import load_models_table


def _pretrain_html_for_row(row: pd.Series) -> Path | None:
    """Return the pretrain_audit.html path for a registry row, or None."""
    ap = row.get("artifacts_path")
    if not ap:
        return None
    p = Path(ap)
    if not p.is_absolute():
        p = ROOT / ap
    candidate = p / "pretrain_audit.html"
    return candidate if candidate.exists() else None


# ── Page ─────────────────────────────────────────────────────────────────────

st.title("Dataset EDA")
st.caption(
    "Pretrain audit report per registered model — target distribution, "
    "class balance, feature/target relationships. "
    "Dropdown lists registry models with a `pretrain_audit.html` artifact."
)

models = load_models_table()
if models.empty:
    st.warning("Registry is empty.")
    st.stop()

# Build the per-model availability map
options: list[tuple[str, Path]] = []
for _, row in models.iterrows():
    html = _pretrain_html_for_row(row)
    if html is not None:
        options.append((row["version_id"], html))

if not options:
    st.info(
        "No registered model has a `pretrain_audit.html` on disk. "
        "Generate one with `python scripts/run_pretrain_audit.py "
        "--model <version_id> --mode trades`."
    )
    st.stop()

# Default to the prod model if it has one, otherwise the most recently trained
prod_with_audit = [vid for vid, _ in options
                   if models.loc[models["version_id"] == vid, "status_flag"].iloc[0] == "prod"]
default_idx = 0
if prod_with_audit:
    default_idx = next(
        (i for i, (vid, _) in enumerate(options) if vid == prod_with_audit[0]), 0
    )

selected = st.selectbox(
    "Model (feature set)",
    [vid for vid, _ in options],
    index=default_idx,
    help="Each pretrain audit is keyed by the model's feature set. Switching "
         "models re-renders the EDA against that feature set.",
)

html_path = dict(options)[selected]
row = models[models["version_id"] == selected].iloc[0]

st.caption(
    f"Status: **{row['status_flag'] or '—'}** · "
    f"Feature ver.: `{row.get('feature_version') or '—'}` · "
    f"Trained: {row.get('training_date') or '—'} · "
    f"Source: `{html_path.relative_to(ROOT)}` "
    f"({html_path.stat().st_size / 1024:.0f} KB)"
)

st.markdown("---")

# TODO (next session, per dashboard_pipeline_tasks.md):
# - Switch from per-model embedded HTML to a regenerable EDA keyed by
#   feature set id (not model). Once data quality is confirmed, run weekly/daily.
# - Investigate t3_sepa_features load perf for live EDA queries.
# - Hand off bad-ticker filtering to Phase 1 (don't filter in training).
# - Add DoD price-change audit to Phase 1.

try:
    content = html_path.read_text(encoding="utf-8")
    components.html(content, height=900, scrolling=True)
except OSError as e:
    st.error(f"Could not read pretrain audit HTML: {e}")
