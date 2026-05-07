"""Side-by-side diff of two trained model versions.

Resolves model identifiers via DuckDB `models` table first; falls back to
filesystem path (containing `metadata.json` + `evaluation/results.json`) if not
registered. Renders training config, hyperparameters, feature set, aggregate
metrics, per-class metrics, and feature-importance rank shifts to stdout. With
`--save`, writes a machine-readable JSON diff alongside model B's artifacts.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import duckdb
from rich.console import Console
from rich.table import Table
from rich import box

DB_PATH = Path(__file__).parent.parent / "data" / "market_data.duckdb"

# Force a non-legacy renderer on Windows so box-drawing chars don't crash cp1252.
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

console = Console(legacy_windows=False, width=180)


@dataclass
class ModelView:
    """Unified view of one model regardless of registration status."""

    identifier: str  # what the user passed in
    artifacts_path: Path
    is_registered: bool
    version_id: Optional[str] = None
    feature_set_id: Optional[str] = None
    specs: dict = field(default_factory=dict)
    registry_metrics: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    results: dict = field(default_factory=dict)
    features: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

def resolve_model(identifier: str, db_path: Path) -> ModelView:
    """Try DuckDB lookup first, then filesystem path."""
    if db_path.exists():
        view = _try_resolve_from_registry(identifier, db_path)
        if view is not None:
            return view

    return _resolve_from_filesystem(identifier)


def _try_resolve_from_registry(version_id: str, db_path: Path) -> Optional[ModelView]:
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        row = con.execute(
            """
            SELECT version_id, specs_json, artifacts_path, feature_set_id,
                   accuracy, weighted_f1, macro_f1, training_date, feature_version,
                   model_name, model_version, git_sha, status_flag, dataset_rows
            FROM models WHERE version_id = ?
            """,
            [version_id],
        ).fetchone()
        if row is None:
            return None

        specs = json.loads(row[1]) if row[1] else {}
        artifacts_path = Path(row[2])

        features: list[str] = []
        if row[3]:
            feat_rows = con.execute(
                "SELECT feature_name FROM model_feature_sets "
                "WHERE feature_set_id = ? ORDER BY ordinal",
                [row[3]],
            ).fetchall()
            features = [r[0] for r in feat_rows]

        # Fall back to specs.features if feature_set table is empty
        if not features and specs.get("features"):
            features = list(specs["features"])

        view = ModelView(
            identifier=version_id,
            artifacts_path=artifacts_path,
            is_registered=True,
            version_id=row[0],
            feature_set_id=row[3],
            specs=specs,
            registry_metrics={
                "accuracy": row[4],
                "weighted_f1": row[5],
                "macro_f1": row[6],
                "training_date": str(row[7]) if row[7] else None,
                "feature_version": row[8],
                "model_name": row[9],
                "model_version": row[10],
                "git_sha": row[11],
                "status": row[12],
                "dataset_rows": row[13],
            },
            features=features,
        )
    finally:
        con.close()

    _load_filesystem_artifacts(view)
    return view


def _resolve_from_filesystem(path_str: str) -> ModelView:
    path = Path(path_str)
    if not path.exists():
        raise FileNotFoundError(
            f"Model identifier '{path_str}' not found in registry and not a valid filesystem path"
        )
    if not path.is_dir():
        raise NotADirectoryError(f"Filesystem identifier must be a directory: {path}")

    view = ModelView(
        identifier=path_str,
        artifacts_path=path,
        is_registered=False,
    )
    _load_filesystem_artifacts(view)

    if not view.features and view.metadata.get("valid_features"):
        view.features = list(view.metadata["valid_features"])

    return view


def _load_filesystem_artifacts(view: ModelView) -> None:
    """Populate metadata/results from the artifacts dir if present.

    Looks at `<artifacts_path>` and one level deep (e.g. `v1/`) since
    train_mfe_classifier writes to `models/<name>/<version>/`.
    """
    candidates: list[Path] = [view.artifacts_path]

    # Tolerate the case where artifacts_path is a model-name dir holding versioned subdirs.
    if view.artifacts_path.is_dir():
        for child in sorted(view.artifacts_path.iterdir()):
            if child.is_dir() and (child / "metadata.json").exists():
                candidates.append(child)

    for cand in candidates:
        meta_path = cand / "metadata.json"
        if meta_path.exists() and not view.metadata:
            try:
                view.metadata = json.loads(meta_path.read_text())
                view.artifacts_path = cand  # promote to the actual leaf
            except json.JSONDecodeError:
                pass

        results_path = cand / "evaluation" / "results.json"
        if results_path.exists() and not view.results:
            try:
                view.results = json.loads(results_path.read_text())
            except json.JSONDecodeError:
                pass


# ---------------------------------------------------------------------------
# Section renderers
# ---------------------------------------------------------------------------

NA = "-"


def _fmt(v: Any) -> str:
    if v is None:
        return NA
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, float):
        return f"{v:.4f}" if abs(v) < 100 else f"{v:,.2f}"
    if isinstance(v, int):
        return f"{v:,}"
    if isinstance(v, list):
        return str(v)
    return str(v)


def _changed(a: Any, b: Any) -> str:
    if a is None and b is None:
        return NA
    if a == b:
        return NA
    return "[yellow]changed[/yellow]"


def _delta_str(a: Any, b: Any) -> str:
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        return _changed(a, b)
    if a == b:
        return NA
    diff = b - a
    sign = "+" if diff > 0 else ""
    return f"[yellow]{sign}{diff:.4f}[/yellow]"


def render_training_config(a: ModelView, b: ModelView) -> Table:
    """Section 1 — training config from metadata.json + registry."""
    table = Table(title="1. Training Config", box=box.SIMPLE_HEAD, show_lines=False)
    table.add_column("Field")
    table.add_column("Model A")
    table.add_column("Model B")
    table.add_column("Changed?")

    def get(view: ModelView, key: str, default: Any = None) -> Any:
        if key in view.metadata:
            return view.metadata[key]
        tc = view.specs.get("training_config", {})
        if key in tc:
            return tc[key]
        return view.registry_metrics.get(key, default)

    fields = [
        "split_mode",
        "min_date",
        "feature_version",
        "train_samples",
        "val_samples",
        "test_samples",
        "label_thresholds",
        "class_weighting",
        "num_boost_round",
        "early_stopping_rounds",
        "best_iteration",
    ]
    for fld in fields:
        va, vb = get(a, fld), get(b, fld)
        table.add_row(fld, _fmt(va), _fmt(vb), _changed(va, vb))

    # Temporal validation summary
    ta = (a.metadata.get("temporal_validation") or {}).get("all_valid")
    tb = (b.metadata.get("temporal_validation") or {}).get("all_valid")
    table.add_row(
        "temporal_validation.all_valid",
        _fmt(ta), _fmt(tb), _changed(ta, tb),
    )
    return table


def render_hyperparams(a: ModelView, b: ModelView) -> Table:
    """Section 2 — hyperparam diff."""
    table = Table(title="2. Hyperparameters", box=box.SIMPLE_HEAD)
    table.add_column("Param")
    table.add_column("Model A")
    table.add_column("Model B")
    table.add_column("Delta")

    ha = a.specs.get("hyperparameters", {}) or {}
    hb = b.specs.get("hyperparameters", {}) or {}
    keys = sorted(set(ha) | set(hb))
    if not keys:
        table.add_row("—", "no hyperparameters in registry for either model", "", "")
        return table

    for k in keys:
        va, vb = ha.get(k), hb.get(k)
        if va == vb:
            table.add_row(f"[dim]{k}[/dim]", _fmt(va), _fmt(vb), NA)
        else:
            table.add_row(k, _fmt(va), _fmt(vb), _delta_str(va, vb))
    return table


def render_feature_diff(a: ModelView, b: ModelView) -> Table:
    """Section 3 — added / removed / shared features."""
    set_a = set(a.features)
    set_b = set(b.features)
    only_a = sorted(set_a - set_b)
    only_b = sorted(set_b - set_a)
    shared = set_a & set_b

    table = Table(title="3. Feature Set Diff", box=box.SIMPLE_HEAD)
    table.add_column("Category")
    table.add_column("Count")
    table.add_column("Features")

    table.add_row(
        "[red]Only in A (removed in B)[/red]",
        str(len(only_a)),
        ", ".join(only_a) if only_a else NA,
    )
    table.add_row(
        "[green]Only in B (added in B)[/green]",
        str(len(only_b)),
        ", ".join(only_b) if only_b else NA,
    )
    table.add_row(
        "[dim]Shared[/dim]",
        f"{len(shared)} / A:{len(set_a)} B:{len(set_b)}",
        "",
    )
    return table


def render_aggregate_metrics(a: ModelView, b: ModelView) -> Table:
    """Section 4 — accuracy, F1, brier."""
    table = Table(title="4. Aggregate Metrics", box=box.SIMPLE_HEAD)
    table.add_column("Metric")
    table.add_column("Model A")
    table.add_column("Model B")
    table.add_column("Delta")

    def split_label(view: ModelView) -> str:
        sm = view.metadata.get("split_mode") or view.specs.get("training_config", {}).get("split_mode")
        return "Val" if sm == "no_holdout_85_15_0" else "Test"

    label = f"{split_label(a)}/{split_label(b)}"

    def get_metric(view: ModelView, key: str) -> Optional[float]:
        if view.results.get(key) is not None:
            return view.results[key]
        return view.registry_metrics.get(key)

    for key in ("accuracy", "weighted_f1", "macro_f1", "micro_f1"):
        va, vb = get_metric(a, key), get_metric(b, key)
        table.add_row(f"{key} ({label})", _fmt(va), _fmt(vb), _delta_str(va, vb))

    # Brier mean
    ba = (a.results.get("brier_score") or {}).get("mean")
    bb = (b.results.get("brier_score") or {}).get("mean")
    table.add_row("brier_score.mean", _fmt(ba), _fmt(bb), _delta_str(ba, bb))
    return table


def render_per_class(a: ModelView, b: ModelView) -> Table:
    """Section 5 — per-class precision/recall/f1/ROC-AUC."""
    table = Table(title="5. Per-Class Metrics", box=box.SIMPLE_HEAD)
    table.add_column("Class")
    for col in ("Prec A", "Prec B", "ΔP", "Rec A", "Rec B", "ΔR",
                "F1 A", "F1 B", "ΔF", "AUC A", "AUC B", "ΔA"):
        table.add_column(col, justify="right")

    rep_a = a.results.get("classification_report", {}) or {}
    rep_b = b.results.get("classification_report", {}) or {}
    auc_a = a.results.get("roc_auc_per_class", {}) or {}
    auc_b = b.results.get("roc_auc_per_class", {}) or {}

    classes = [c for c in rep_a if c not in ("accuracy", "macro avg", "weighted avg")]
    for c in rep_b:
        if c not in classes and c not in ("accuracy", "macro avg", "weighted avg"):
            classes.append(c)

    if not classes:
        table.add_row("—", *(["no per-class data"] + [""] * 11))
        return table

    def short(v: Optional[float]) -> str:
        return NA if v is None else f"{v:.3f}"

    def short_delta(va: Optional[float], vb: Optional[float]) -> str:
        if va is None or vb is None:
            return NA
        d = vb - va
        if d == 0:
            return NA
        sign = "+" if d > 0 else ""
        color = "green" if d > 0 else "red"
        return f"[{color}]{sign}{d:.3f}[/{color}]"

    for cls in classes:
        ra = rep_a.get(cls, {}) or {}
        rb = rep_b.get(cls, {}) or {}
        pa, pb = ra.get("precision"), rb.get("precision")
        rca, rcb = ra.get("recall"), rb.get("recall")
        fa, fb = ra.get("f1-score"), rb.get("f1-score")
        aa, ab = auc_a.get(cls), auc_b.get(cls)
        table.add_row(
            cls,
            short(pa), short(pb), short_delta(pa, pb),
            short(rca), short(rcb), short_delta(rca, rcb),
            short(fa), short(fb), short_delta(fa, fb),
            short(aa), short(ab), short_delta(aa, ab),
        )
    return table


def render_feature_importance_shift(a: ModelView, b: ModelView, top_n: int = 15) -> Table:
    """Section 6 — feature importance rank shift (XGBoost gain)."""
    table = Table(title=f"6. Feature Importance Rank Shift (top {top_n} by avg rank)", box=box.SIMPLE_HEAD)
    table.add_column("Feature")
    table.add_column("Rank A", justify="right")
    table.add_column("Rank B", justify="right")
    table.add_column("Move")

    fi_a = a.results.get("feature_importance") or []
    fi_b = b.results.get("feature_importance") or []
    if not fi_a and not fi_b:
        table.add_row("—", "no feature_importance in either results.json", "", "")
        return table

    # Sort by gain desc → rank
    def to_rank(items: list[dict]) -> dict[str, int]:
        sorted_items = sorted(items, key=lambda x: x.get("gain", 0), reverse=True)
        return {item["feature"]: i + 1 for i, item in enumerate(sorted_items)}

    rank_a = to_rank(fi_a)
    rank_b = to_rank(fi_b)
    all_features = set(rank_a) | set(rank_b)

    big = 10**9

    def avg_rank(f: str) -> float:
        return (rank_a.get(f, big) + rank_b.get(f, big)) / 2

    ordered = sorted(all_features, key=avg_rank)[:top_n]

    for f in ordered:
        ra, rb = rank_a.get(f), rank_b.get(f)
        if ra is None and rb is not None:
            move = f"[green][NEW][/green] (rank {rb})"
        elif ra is not None and rb is None:
            move = f"[red][REMOVED][/red] (was {ra})"
        elif ra == rb:
            move = NA
        else:
            d = ra - rb  # positive = moved up in B
            arrow = "UP" if d > 0 else "DOWN"
            color = "green" if d > 0 else "red"
            move = f"[{color}]{arrow} {abs(d)}[/{color}]"
        table.add_row(
            f,
            str(ra) if ra is not None else NA,
            str(rb) if rb is not None else NA,
            move,
        )
    return table


def render_shap_top(a: ModelView, b: ModelView, top_k: int = 5) -> Optional[Table]:
    """Section 6b — top-K SHAP features per class side-by-side, if available."""
    sa = (a.results.get("shap_summary") or {}).get("mean_abs_shap_per_class")
    sb = (b.results.get("shap_summary") or {}).get("mean_abs_shap_per_class")
    if not sa and not sb:
        return None

    table = Table(title=f"6b. SHAP Top-{top_k} Per Class", box=box.SIMPLE_HEAD)
    table.add_column("Class")
    table.add_column("Model A (feature: |shap|)")
    table.add_column("Model B (feature: |shap|)")

    classes = list((sa or {}).keys())
    for c in (sb or {}).keys():
        if c not in classes:
            classes.append(c)

    def fmt_list(lst: Optional[list]) -> str:
        if not lst:
            return NA
        return "\n".join(f"{x['feature']}: {x['mean_abs_shap']:.3f}" for x in lst[:top_k])

    for c in classes:
        table.add_row(c, fmt_list((sa or {}).get(c)), fmt_list((sb or {}).get(c)))
    return table


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------

def build_diff_payload(a: ModelView, b: ModelView, top_n: int) -> dict:
    """JSON-serializable dict capturing what the tables show."""
    set_a, set_b = set(a.features), set(b.features)

    fi_a = a.results.get("feature_importance") or []
    fi_b = b.results.get("feature_importance") or []
    rank_a = {item["feature"]: i + 1 for i, item in enumerate(
        sorted(fi_a, key=lambda x: x.get("gain", 0), reverse=True))}
    rank_b = {item["feature"]: i + 1 for i, item in enumerate(
        sorted(fi_b, key=lambda x: x.get("gain", 0), reverse=True))}

    return {
        "model_a": {
            "identifier": a.identifier,
            "version_id": a.version_id,
            "is_registered": a.is_registered,
            "artifacts_path": str(a.artifacts_path),
            "feature_set_id": a.feature_set_id,
            "n_features": len(a.features),
        },
        "model_b": {
            "identifier": b.identifier,
            "version_id": b.version_id,
            "is_registered": b.is_registered,
            "artifacts_path": str(b.artifacts_path),
            "feature_set_id": b.feature_set_id,
            "n_features": len(b.features),
        },
        "training_config": {
            "a": {**a.metadata, **(a.specs.get("training_config") or {})},
            "b": {**b.metadata, **(b.specs.get("training_config") or {})},
        },
        "hyperparameters": {
            "a": a.specs.get("hyperparameters") or {},
            "b": b.specs.get("hyperparameters") or {},
        },
        "feature_diff": {
            "only_in_a": sorted(set_a - set_b),
            "only_in_b": sorted(set_b - set_a),
            "shared_count": len(set_a & set_b),
        },
        "aggregate_metrics": {
            "a": {
                k: a.results.get(k) for k in
                ("accuracy", "weighted_f1", "macro_f1", "micro_f1")
            } | {"brier_mean": (a.results.get("brier_score") or {}).get("mean")},
            "b": {
                k: b.results.get(k) for k in
                ("accuracy", "weighted_f1", "macro_f1", "micro_f1")
            } | {"brier_mean": (b.results.get("brier_score") or {}).get("mean")},
        },
        "per_class": {
            "a": a.results.get("classification_report") or {},
            "b": b.results.get("classification_report") or {},
            "roc_auc_a": a.results.get("roc_auc_per_class") or {},
            "roc_auc_b": b.results.get("roc_auc_per_class") or {},
        },
        "feature_importance_ranks": {
            "a": rank_a,
            "b": rank_b,
            "top_n": top_n,
        },
    }


def save_diff(payload: dict, model_b: ModelView, save_text: Optional[str] = None) -> Path:
    out_dir = model_b.artifacts_path / "diffs"
    out_dir.mkdir(parents=True, exist_ok=True)
    fname_stem = (
        payload["model_a"]["version_id"]
        or Path(payload["model_a"]["identifier"]).name
        or "modelA"
    )
    json_path = out_dir / f"vs_{fname_stem}.json"
    json_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    if save_text is not None:
        (out_dir / f"vs_{fname_stem}.txt").write_text(save_text, encoding="utf-8")
    return json_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Diff two model versions side-by-side")
    p.add_argument("--model-a", required=True, help="version_id (DuckDB) or filesystem path")
    p.add_argument("--model-b", required=True, help="version_id (DuckDB) or filesystem path")
    p.add_argument("--top-n", type=int, default=15, help="Top N features in rank shift table")
    p.add_argument("--save", action="store_true", help="Write JSON diff to model B's diffs/")
    p.add_argument("--save-text", action="store_true",
                   help="Also write rendered tables as plain text alongside JSON")
    p.add_argument("--db", type=Path, default=DB_PATH)
    return p.parse_args()


def main() -> None:
    args = parse_args()

    try:
        view_a = resolve_model(args.model_a, args.db)
        view_b = resolve_model(args.model_b, args.db)
    except (FileNotFoundError, NotADirectoryError) as e:
        console.print(f"[red]ERROR:[/red] {e}")
        sys.exit(1)

    console.rule(f"[bold]Model A[/bold]: {view_a.identifier}  vs  [bold]Model B[/bold]: {view_b.identifier}")
    console.print(
        f"  A: registered={view_a.is_registered}  artifacts={view_a.artifacts_path}  "
        f"features={len(view_a.features)}"
    )
    console.print(
        f"  B: registered={view_b.is_registered}  artifacts={view_b.artifacts_path}  "
        f"features={len(view_b.features)}\n"
    )

    sections = [
        render_training_config(view_a, view_b),
        render_hyperparams(view_a, view_b),
        render_feature_diff(view_a, view_b),
        render_aggregate_metrics(view_a, view_b),
        render_per_class(view_a, view_b),
        render_feature_importance_shift(view_a, view_b, top_n=args.top_n),
    ]
    shap_table = render_shap_top(view_a, view_b)
    if shap_table is not None:
        sections.append(shap_table)

    for tbl in sections:
        console.print(tbl)
        console.print()

    if args.save or args.save_text:
        payload = build_diff_payload(view_a, view_b, top_n=args.top_n)
        text_dump = None
        if args.save_text:
            text_console = Console(record=True, width=160)
            for tbl in sections:
                text_console.print(tbl)
                text_console.print()
            text_dump = text_console.export_text()
        out = save_diff(payload, view_b, save_text=text_dump)
        console.print(f"[green]Saved diff to[/green] {out}")


if __name__ == "__main__":
    main()
