"""Top-level orchestrator: build sections, aggregate verdict, emit HTML+JSON."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from .data_loader import (
    EvalSplit,
    build_mode_a_pool,
    build_mode_b_pool,
    load_eval_data,
)
from .rubric import SectionResult, placeholder_section
from .sections import (
    run_section_a,
    run_section_b,
    run_section_c,
    run_section_d,
    run_section_e,
    run_section_f,
)
from .verdict import aggregate_score, card_void, use_case_verdicts
from . import report as report_renderer

logger = logging.getLogger(__name__)


@dataclass
class ModelCard:
    model_id: str
    model_path: Path
    db_path: Path
    built_at: str
    sections: dict[str, SectionResult]
    use_case_verdicts: dict[str, str]
    aggregate: dict[str, Any]
    card_void: bool
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "model_path": str(self.model_path),
            "db_path": str(self.db_path),
            "built_at": self.built_at,
            "card_void": self.card_void,
            "sections": {k: v.to_dict() for k, v in self.sections.items()},
            "use_case_verdicts": dict(self.use_case_verdicts),
            "aggregate": dict(self.aggregate),
            "meta": dict(self.meta),
        }


class ModelCardBuilder:
    def __init__(
        self,
        model_id: str,
        model_path: Path,
        db_path: Path,
        output_dir: Path,
        *,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        apply_trend_ok_filter: bool = True,
        feature_version: str = "v3.1",
        skip_sepa_match: bool = False,
        build_mode_b: bool = False,
        mode_b_cache_dir: Optional[Path] = None,
        mode_b_force_recompute: bool = False,
    ):
        self.model_id = model_id
        self.model_path = Path(model_path)
        self.db_path = Path(db_path)
        self.output_dir = Path(output_dir)
        self.start_date = start_date
        self.end_date = end_date
        self.apply_trend_ok_filter = apply_trend_ok_filter
        self.feature_version = feature_version
        self.skip_sepa_match = skip_sepa_match
        self.build_mode_b = build_mode_b
        self.mode_b_cache_dir = Path(mode_b_cache_dir) if mode_b_cache_dir else None
        self.mode_b_force_recompute = mode_b_force_recompute

    def build(self) -> ModelCard:
        t0 = time.perf_counter()
        logger.info("Loading eval data for %s ...", self.model_id)
        split = load_eval_data(
            model_id=self.model_id,
            model_path=self.model_path,
            db_path=self.db_path,
            start_date=self.start_date,
            end_date=self.end_date,
            apply_trend_ok_filter=self.apply_trend_ok_filter,
            feature_version=self.feature_version,
        )
        logger.info(
            "Eval data: n=%d, prevalence=%.4f, dates %s..%s",
            split.n, split.prevalence, split.meta["date_min"], split.meta["date_max"],
        )

        # Build stateful pools for Section D + E
        logger.info("Building Mode A pool ...")
        mode_a_pool = build_mode_a_pool(split)
        logger.info("Mode A pool: %d rows", len(mode_a_pool))

        mode_b_pool = None
        if self.build_mode_b:
            mb_start = self.start_date or split.meta["date_min"]
            mb_end = self.end_date or split.meta["date_max"]
            logger.info(
                "Building Mode B pool from t3_sepa_features %s..%s ...",
                mb_start, mb_end,
            )
            mode_b_pool = build_mode_b_pool(
                db_path=self.db_path,
                model_id=self.model_id,
                model_path=self.model_path,
                feature_cols=split.feature_cols,
                start_date=mb_start,
                end_date=mb_end,
                feature_version=self.feature_version,
                cache_dir=self.mode_b_cache_dir,
                force_recompute=self.mode_b_force_recompute,
            )
            logger.info("Mode B pool: %d rows", len(mode_b_pool))

        sections: dict[str, SectionResult] = {}
        sections["A"] = run_section_a(split, self.db_path, skip_sepa_match=self.skip_sepa_match)
        sections["B"] = run_section_b(split)
        sections["C"] = run_section_c(split)
        sections["D"] = run_section_d(split, mode_a_pool, mode_b_pool)
        sections["E"] = run_section_e(split, mode_a_pool)
        sections["F"] = run_section_f(split, self.db_path)
        sections["G"] = placeholder_section("G", "Edge existence (Phase 3)")

        verdicts = use_case_verdicts(sections)
        agg = aggregate_score(sections)
        void = card_void(sections)
        elapsed = time.perf_counter() - t0

        card = ModelCard(
            model_id=self.model_id,
            model_path=self.model_path,
            db_path=self.db_path,
            built_at=datetime.utcnow().isoformat(timespec="seconds") + "Z",
            sections=sections,
            use_case_verdicts=verdicts,
            aggregate=agg,
            card_void=void,
            meta={
                "split": split.meta,
                "build_seconds": round(elapsed, 2),
                "phase": "2 (A/B/C/D/E/F; G placeholder)",
                "mode_a_pool_rows": int(len(mode_a_pool)),
                "mode_b_pool_rows": int(len(mode_b_pool)) if mode_b_pool is not None else None,
            },
        )
        logger.info("Built model card in %.2fs (void=%s, band=%s)", elapsed, void, agg.get("band"))
        return card

    def render(self, card: ModelCard, html_path: Optional[Path] = None,
               json_path: Optional[Path] = None) -> tuple[Path, Path]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        slug = self.model_id.replace("/", "_").replace(" ", "_")
        if html_path is None:
            html_path = self.output_dir / f"{slug}.html"
        if json_path is None:
            json_path = self.output_dir / f"{slug}.json"
        json_path.write_text(json.dumps(card.to_dict(), indent=2, default=str))
        report_renderer.render(card, html_path)
        logger.info("Wrote %s and %s", html_path, json_path)
        return html_path, json_path
