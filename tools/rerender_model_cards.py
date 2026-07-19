"""Re-render model-card HTML from the cached JSON — no recompute.

A card build recomputes every section (Section G multiprocessing hangs on the dev
box, project_model_card_section_g_hang). When only the *renderer* changes — CSS,
chart config — the numbers are already correct in `model_cards/*.json`, so the
HTML can be regenerated straight from it.

Usage:
    python tools/rerender_model_cards.py            # all cards
    python tools/rerender_model_cards.py m01_binary_v1
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.evaluation.model_card.builder import ModelCard  # noqa: E402
from src.evaluation.model_card.report import render  # noqa: E402
from src.evaluation.model_card.rubric import (  # noqa: E402
    GateEntry,
    MetricEntry,
    SectionResult,
)

CARDS_DIR = ROOT / "model_cards"


def _section(d: dict) -> SectionResult:
    return SectionResult(
        name=d["name"],
        title=d.get("title", ""),
        scored=d.get("scored", False),
        metrics=[MetricEntry(**m) for m in d.get("metrics", [])],
        rubric_scores=d.get("rubric_scores", {}),
        gates=[GateEntry(**g) for g in d.get("gates", [])],
        tables=d.get("tables", {}),
        detail=d.get("detail", ""),
        not_implemented=d.get("not_implemented", False),
    )


def _card(d: dict) -> ModelCard:
    return ModelCard(
        model_id=d["model_id"],
        model_path=Path(d.get("model_path", "")),
        db_path=Path(d.get("db_path", "")),
        built_at=d.get("built_at", ""),
        sections={k: _section(v) for k, v in d.get("sections", {}).items()},
        use_case_verdicts=d.get("use_case_verdicts", {}),
        use_case_reasons=d.get("use_case_reasons", {}),
        aggregate=d.get("aggregate", {}),
        card_void=d.get("card_void", False),
        benchmarks=d.get("benchmarks", {}),
        meta=d.get("meta", {}),
    )


def main() -> int:
    wanted = sys.argv[1:]
    jsons = sorted(CARDS_DIR.glob("*.json"))
    if wanted:
        jsons = [p for p in jsons if p.stem in wanted]
    if not jsons:
        print("No matching card JSON found.")
        return 1

    for jp in jsons:
        try:
            card = _card(json.loads(jp.read_text(encoding="utf-8")))
        except (ValueError, KeyError, TypeError) as e:
            print(f"[SKIP] {jp.name}: {e}")
            continue
        out = jp.with_suffix(".html")
        render(card, out)
        print(f"[OK] {out.relative_to(ROOT)} ({out.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
