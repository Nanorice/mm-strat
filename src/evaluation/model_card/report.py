"""Self-contained HTML renderer for the model card.

Follows the html_report.py pattern: inline styles, tables for everything,
no external assets. Phase 1 keeps the visuals deliberately plain — Plotly
charts come in Phase 2/3 (decile profiles, reliability diagrams).
"""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from .rubric import SectionResult

STATUS_COLOR = {
    "pass": "#2e7d32",
    "fail": "#c62828",
    "warn": "#f9a825",
    "n/a": "#757575",
}

VERDICT_COLOR = {
    "PASS": "#2e7d32",
    "MARGINAL": "#f9a825",
    "REJECT": "#c62828",
    "PENDING": "#757575",
}

BAND_COLOR = {
    "STRONG": "#1b5e20",
    "ACCEPTABLE": "#558b2f",
    "WEAK": "#f9a825",
    "BROKEN": "#c62828",
    "INSUFFICIENT": "#757575",
}

STYLE = """
<style>
:root { font-family: 'Segoe UI', Helvetica, Arial, sans-serif; color: #222; }
body { max-width: 1200px; margin: 32px auto; padding: 0 24px; line-height: 1.45; }
h1, h2, h3 { color: #1a1a1a; }
h1 { border-bottom: 2px solid #1f77b4; padding-bottom: 8px; }
.section { border: 1px solid #e0e0e0; border-radius: 8px; padding: 16px 20px; margin: 18px 0; }
.section.void { border-color: #c62828; background: #fff5f5; }
.section.placeholder { background: #fafafa; color: #888; }
.kv { display: grid; grid-template-columns: max-content 1fr; gap: 4px 16px; font-size: 14px; }
.kv dt { color: #555; }
.kv dd { margin: 0; }
.badge { display: inline-block; padding: 2px 10px; border-radius: 12px; color: white; font-size: 12px; font-weight: 600; }
.metric-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 12px; margin: 10px 0; }
.metric { background: #f8f9fa; border-radius: 6px; padding: 10px 12px; }
.metric .name { font-size: 12px; color: #555; }
.metric .value { font-size: 20px; font-weight: 600; }
.metric .detail { font-size: 11px; color: #777; }
table.grid { border-collapse: collapse; width: 100%; font-size: 13px; margin: 8px 0; }
table.grid th, table.grid td { border: 1px solid #e0e0e0; padding: 4px 8px; text-align: left; }
table.grid th { background: #f0f0f0; }
.gate-row { padding: 4px 0; }
.gate-row .badge { margin-right: 8px; }
.detail { color: #555; font-size: 13px; }
.banner { padding: 12px 16px; border-radius: 6px; margin: 12px 0; font-weight: 600; }
.banner.void { background: #c62828; color: white; }
.banner.ok { background: #e8f5e9; color: #1b5e20; }
.verdict-grid { display: grid; grid-template-columns: max-content max-content 1fr; gap: 4px 12px; }
</style>
"""


def _esc(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        if value != value:  # NaN
            return "—"
        return f"{value:.4f}" if abs(value) < 1000 else f"{value:.2e}"
    return html.escape(str(value))


def _badge(text: str, color: str) -> str:
    return f"<span class='badge' style='background:{color}'>{html.escape(text)}</span>"


def _gate_html(g) -> str:
    color = STATUS_COLOR.get(g.status, "#555")
    blocking = "blocking" if g.blocking else "warning"
    return (
        f"<div class='gate-row'>"
        f"{_badge(g.status.upper(), color)}"
        f"<strong>{html.escape(g.name)}</strong> "
        f"<span class='detail'>({blocking}) — {html.escape(g.detail)}</span>"
        f"</div>"
    )


def _metrics_html(metrics) -> str:
    if not metrics:
        return ""
    cells = []
    for m in metrics:
        cells.append(
            f"<div class='metric'>"
            f"<div class='name'>{html.escape(m.name)}</div>"
            f"<div class='value'>{_esc(m.value)}</div>"
            f"<div class='detail'>{html.escape(m.detail or '')}</div>"
            f"</div>"
        )
    return f"<div class='metric-grid'>{''.join(cells)}</div>"


def _table_html(title: str, rows: list[dict]) -> str:
    if not rows:
        return ""
    cols = list(rows[0].keys())
    head = "".join(f"<th>{html.escape(c)}</th>" for c in cols)
    body = "".join(
        "<tr>" + "".join(f"<td>{_esc(r.get(c))}</td>" for c in cols) + "</tr>"
        for r in rows
    )
    return (
        f"<h4>{html.escape(title)}</h4>"
        f"<table class='grid'><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
    )


def _rubric_html(scores: dict[str, int]) -> str:
    if not scores:
        return ""
    band_text = {0: "Poor (0)", 1: "Marginal (1)", 2: "Good (2)", 3: "Strong (3)"}
    cells = "".join(
        f"<tr><td>{html.escape(k)}</td><td>{band_text.get(v, str(v))}</td></tr>"
        for k, v in scores.items()
    )
    return (
        "<h4>Rubric scores</h4>"
        f"<table class='grid'><thead><tr><th>metric</th><th>band</th></tr></thead>"
        f"<tbody>{cells}</tbody></table>"
    )


def _section_html(s: SectionResult) -> str:
    cls = "section"
    if s.not_implemented:
        cls += " placeholder"
    if s.has_blocking_failure:
        cls += " void"

    header = (
        f"<h2>Section {s.name} — {html.escape(s.title)}</h2>"
        f"<p class='detail'>{html.escape(s.detail or '')}</p>"
    )
    if s.not_implemented:
        return (
            f"<div class='{cls}'>{header}"
            f"<p><em>Not yet implemented (placeholder for Phase 2/3).</em></p></div>"
        )

    gate_html = "".join(_gate_html(g) for g in s.gates)
    metrics_html = _metrics_html(s.metrics)
    rubric_html = _rubric_html(s.rubric_scores)
    tables_html = "".join(_table_html(name, rows) for name, rows in s.tables.items())

    summary = (
        f"<p>Aggregate score: <strong>{s.aggregate_score if s.aggregate_score is not None else '—'}/3</strong>"
        f" — gates passed: {s.gates_passed}/{s.gates_total}</p>"
        if s.scored else
        f"<p>Gates passed: {s.gates_passed}/{s.gates_total}</p>"
    )
    return (
        f"<div class='{cls}'>"
        f"{header}{summary}{metrics_html}{rubric_html}"
        f"<h4>Gates</h4>{gate_html or '<p class=detail>(no gates)</p>'}"
        f"{tables_html}"
        f"</div>"
    )


def _header_html(card) -> str:
    split_meta = card.meta.get("split", {})
    rows = [
        ("Model ID", card.model_id),
        ("Built at (UTC)", card.built_at),
        ("Phase", card.meta.get("phase", "")),
        ("Build duration (s)", card.meta.get("build_seconds", "")),
        ("Eval rows", split_meta.get("n_rows")),
        ("Positives", split_meta.get("n_positives")),
        ("Prevalence", f"{split_meta.get('prevalence', 0):.4f}"),
        ("Date range", f"{split_meta.get('date_min')} → {split_meta.get('date_max')}"),
        ("Feature version", split_meta.get("feature_version")),
        ("trend_ok filtered", split_meta.get("trend_ok_filtered")),
        ("Mode A pool rows", card.meta.get("mode_a_pool_rows")),
        ("Mode B pool rows", card.meta.get("mode_b_pool_rows")),
        ("Model path", str(card.model_path)),
    ]
    dl = "".join(
        f"<dt>{html.escape(str(k))}</dt><dd>{_esc(v)}</dd>" for k, v in rows
    )
    return f"<dl class='kv'>{dl}</dl>"


def _verdict_html(card) -> str:
    band = card.aggregate.get("band", "—")
    band_badge = _badge(band, BAND_COLOR.get(band, "#555"))
    reasons_map = getattr(card, "use_case_reasons", {}) or {}
    rows = []
    for use_case, verdict in card.use_case_verdicts.items():
        color = VERDICT_COLOR.get(verdict, "#555")
        sub = reasons_map.get(use_case, [])
        sub_html = " · ".join(
            (
                f"<span style='color:{VERDICT_COLOR.get(r['verdict'], '#555')}'>"
                f"{html.escape(r['section'])}={html.escape(r['verdict'])}"
                f"</span>"
            )
            for r in sub
        )
        rows.append(
            f"<div>{html.escape(use_case)}</div>"
            f"<div>{_badge(verdict, color)}</div>"
            f"<div class='detail'>{sub_html}</div>"
        )
    score_line = (
        f"Aggregate: <strong>{card.aggregate.get('total')}"
        f" / {card.aggregate.get('max')}</strong> {band_badge}"
    )
    per_section_rows = []
    per_section = card.aggregate.get("per_section", {})
    for sec, score in per_section.items():
        per_section_rows.append(
            f"<tr><td>{html.escape(sec)}</td>"
            f"<td>{score if score is not None else '—'}</td></tr>"
        )
    per_section_table = (
        "<h4>Per-section scores</h4>"
        f"<table class='grid'><thead><tr><th>section</th><th>score / 3</th></tr></thead>"
        f"<tbody>{''.join(per_section_rows)}</tbody></table>"
    )
    return (
        "<div class='section'>"
        "<h2>Verdict</h2>"
        f"<p>{score_line}</p>"
        f"<h4>Use-case verdicts</h4>"
        f"<div class='verdict-grid'>{''.join(rows)}</div>"
        f"{per_section_table}"
        "</div>"
    )


def _benchmarks_html(card) -> str:
    bm = getattr(card, "benchmarks", {}) or {}
    if not bm:
        return ""
    model = bm.get("model")
    sepa = bm.get("sepa_composite")
    delta = bm.get("delta_vs_sepa_composite")
    if not model:
        return ""

    rows = []
    columns = ["name", "n_rows", "auc", "pr_auc", "brier", "log_loss",
               "binary_ic_mean", "top5_lift", "prevalence"]

    def _row(d: dict) -> str:
        return "<tr>" + "".join(f"<td>{_esc(d.get(c))}</td>" for c in columns) + "</tr>"

    rows.append(_row(model))
    if sepa:
        rows.append(_row(sepa))
    head = "".join(f"<th>{html.escape(c)}</th>" for c in columns)
    table = (
        f"<table class='grid'><thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )

    delta_html = ""
    if delta:
        delta_rows = "".join(
            f"<tr><td>{html.escape(k)}</td><td>{_esc(v)}</td></tr>"
            for k, v in delta.items()
        )
        delta_html = (
            "<h4>Model − SEPA composite (positive = model wins)</h4>"
            f"<table class='grid'><thead><tr><th>metric</th><th>delta</th></tr></thead>"
            f"<tbody>{delta_rows}</tbody></table>"
        )
    elif "sepa_composite_skipped" in bm:
        delta_html = (
            f"<p class='detail'><em>SEPA composite baseline skipped: "
            f"{html.escape(str(bm['sepa_composite_skipped']))}</em></p>"
        )

    return (
        "<div class='section'>"
        "<h2>Benchmarks — model vs SEPA composite</h2>"
        "<p class='detail'>The SEPA composite is an equal-weight per-day rank "
        "of canonical SEPA strength features (no ML). Outperformance vs this "
        "baseline is the 'does ML add value over a domain-knowledge score?' "
        "test.</p>"
        f"{table}"
        f"{delta_html}"
        "</div>"
    )


def render(card, html_path: Path) -> None:
    void_banner = (
        "<div class='banner void'>CARD VOID — Section A blocking gate failed. "
        "Downstream metrics are not trustworthy.</div>"
        if card.card_void else
        "<div class='banner ok'>Section A passed; downstream metrics are reportable.</div>"
    )

    body = (
        f"<h1>Model Card — {html.escape(card.model_id)}</h1>"
        f"{_header_html(card)}"
        f"{void_banner}"
        f"{_verdict_html(card)}"
        f"{_benchmarks_html(card)}"
        + "".join(_section_html(s) for s in card.sections.values())
    )
    doc = f"<!doctype html><html><head><meta charset='utf-8'><title>Model Card — {html.escape(card.model_id)}</title>{STYLE}</head><body>{body}</body></html>"
    Path(html_path).parent.mkdir(parents=True, exist_ok=True)
    Path(html_path).write_text(doc, encoding="utf-8")
