"""Top-level orchestrator: build sections, aggregate verdict, emit HTML+JSON."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from .benchmarks import (
    BaselineMetrics,
    baseline_delta,
    model_metrics_for_comparison,
    sepa_composite_baseline,
)
from .data_loader import (
    EvalSplit,
    build_mode_a_pool,
    build_mode_b_pool,
    load_eval_data,
)
from .rubric import SectionResult
from .sections import (
    run_section_a,
    run_section_b,
    run_section_c,
    run_section_d,
    run_section_e,
    run_section_f,
    run_section_g,
)
from .verdict import (
    aggregate_score,
    card_void,
    use_case_verdicts,
    use_case_verdicts_with_reasons,
)
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
    use_case_reasons: dict[str, list[dict[str, str]]]
    aggregate: dict[str, Any]
    card_void: bool
    benchmarks: dict[str, Any] = field(default_factory=dict)
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
            "use_case_reasons": dict(self.use_case_reasons),
            "aggregate": dict(self.aggregate),
            "benchmarks": dict(self.benchmarks),
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
        section_g_n_permutations: int = 500,
        section_g_n_bootstrap: int = 500,
        section_g_block_size_days: int = 60,
        skip_benchmarks: bool = False,
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
        self.section_g_n_permutations = section_g_n_permutations
        self.section_g_n_bootstrap = section_g_n_bootstrap
        self.section_g_block_size_days = section_g_block_size_days
        self.skip_benchmarks = skip_benchmarks

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
        logger.info(
            "Running Section G (perm=%d, bootstrap=%d, block=%dd) ...",
            self.section_g_n_permutations, self.section_g_n_bootstrap,
            self.section_g_block_size_days,
        )
        sections["G"] = run_section_g(
            mode_a_pool,
            n_permutations=self.section_g_n_permutations,
            n_bootstrap=self.section_g_n_bootstrap,
            block_size_days=self.section_g_block_size_days,
        )

        benchmarks_block: dict[str, Any] = {}
        if not self.skip_benchmarks:
            logger.info("Running model vs SEPA-composite baseline ...")
            try:
                model_metrics = model_metrics_for_comparison(split, mode_a_pool)
                sepa = sepa_composite_baseline(split, mode_a_pool)
                benchmarks_block["model"] = model_metrics.to_dict()
                if sepa is not None:
                    benchmarks_block["sepa_composite"] = sepa.to_dict()
                    benchmarks_block["delta_vs_sepa_composite"] = baseline_delta(
                        model_metrics, sepa,
                    )
                else:
                    benchmarks_block["sepa_composite_skipped"] = (
                        "no canonical SEPA components present in eval dataframe"
                    )
            except Exception as e:  # pragma: no cover
                logger.exception("Benchmarks failed: %s", e)
                benchmarks_block["error"] = str(e)

        verdicts_detail = use_case_verdicts_with_reasons(sections)
        verdicts = {k: v["verdict"] for k, v in verdicts_detail.items()}
        reasons = {k: v["reasons"] for k, v in verdicts_detail.items()}
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
            use_case_reasons=reasons,
            aggregate=agg,
            card_void=void,
            benchmarks=benchmarks_block,
            meta={
                "split": split.meta,
                "build_seconds": round(elapsed, 2),
                "phase": "3 (A/B/C/D/E/F/G + benchmarks)",
                "mode_a_pool_rows": int(len(mode_a_pool)),
                "mode_b_pool_rows": int(len(mode_b_pool)) if mode_b_pool is not None else None,
                "section_g_n_permutations": self.section_g_n_permutations,
                "section_g_n_bootstrap": self.section_g_n_bootstrap,
            },
        )
        logger.info("Built model card in %.2fs (void=%s, band=%s)", elapsed, void, agg.get("band"))
        return card

    def render(self, card: ModelCard, html_path: Optional[Path] = None,
               json_path: Optional[Path] = None,
               register_version_id: Optional[str] = None,
               registry_db_path: Optional[Path] = None) -> tuple[Path, Path]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        slug = self.model_id.replace("/", "_").replace(" ", "_")
        if html_path is None:
            html_path = self.output_dir / f"{slug}.html"
        if json_path is None:
            # Derive JSON path from the HTML path so a custom --output html
            # name does not collide with the default-slug JSON.
            json_path = Path(html_path).with_suffix(".json")
        json_path.write_text(json.dumps(card.to_dict(), indent=2, default=str))
        report_renderer.render(card, html_path)
        logger.info("Wrote %s and %s", html_path, json_path)

        # Advisory write-back: store the card path + build time on the models
        # row so set_prod() and the dashboard can find it. Lazy import keeps the
        # eval package decoupled from the registry's storage.
        if register_version_id:
            from src.model_registry import ModelRegistry

            registry = ModelRegistry(db_path=registry_db_path)
            registry.register_model_card(
                version_id=register_version_id,
                card_path=str(json_path),
                built_at=card.built_at,
            )

        return html_path, json_path
