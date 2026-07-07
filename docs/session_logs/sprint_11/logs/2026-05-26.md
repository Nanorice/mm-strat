# Session Handover: 2026-05-26 — Model Card Framework Phase 3

## 🎯 Goal

Complete Phase 3 of [docs/plans/model_card_implementation_plan_2026_05_25.md](../../plans/model_card_implementation_plan_2026_05_25.md): wire Section G (edge existence — statistical), benchmarks (SEPA-composite baseline), and the per-use-case verdict reasons into the seven-section model card. Phases 1+2 landed in [2026-05-25_model-card-phase-1-and-2.md](2026-05-25_model-card-phase-1-and-2.md); Phase 4 (promotion-gate integration) deferred to next session.

## ✅ Accomplished

### Phase 3 — Section G + benchmarks + verdict reasons

New code:

- [src/evaluation/model_card/sections/section_g_edge.py](../../../src/evaluation/model_card/sections/section_g_edge.py) — classification-metric-level permutation null + block-bootstrap CI.
  - **Permutation null** on AUC (global label shuffle), binary IC (per-day shuffle preserving per-day prevalence), top-5 hit lift (per-day shuffle). Returns observed metric, null median, percentile, one-sided p-value per metric.
  - **Block bootstrap** (default 60d blocks, matching `bootstrap.py` convention) on the same three metrics. Returns 5/95 CI.
  - **G3 sample adequacy**: 4-band score from `n_positives` count (< 50 noisy, < 100 marginal, ≥ 500 strong).
  - **Gates**: G1 (≥ 2 of 3 metrics above 95th percentile of null) blocking; G2 (≥ 1 of 3 CIs excludes random baseline) blocking; G3 (n_positives ≥ 100) warning.
  - **Rubric**: `permutation_min` + `bootstrap_min` + `sample_adequacy` each scored 0–3.
  - Defaults: 500 permutations × 500 bootstrap iters × 60d blocks. CLI override via `--section-g-permutations / --section-g-bootstrap / --section-g-block-days`.

- [src/evaluation/model_card/benchmarks.py](../../../src/evaluation/model_card/benchmarks.py) — model vs SEPA-composite baseline comparison.
  - `BaselineMetrics` dataclass: `auc`, `pr_auc`, `brier`, `log_loss`, `binary_ic_mean`, `top5_lift`, `prevalence`, `n_rows`.
  - `sepa_composite_baseline()` — equal-weight per-day rank composite of canonical SEPA strength features (`rs_rating`, `rs`, `rs_ma`, `rs_line_log`, `return_20d`, `price_vs_spy`, `vol_ratio` higher-better; `pct_from_high_52w`, `dist_from_52w_high` lower-better). Case-insensitive column resolution (handles DuckDB lowercase + view-manager TitleCase rename). Returns `None` if no canonical components found.
  - `model_metrics_for_comparison()` — same metric block computed on the model's `pred_proba`.
  - `baseline_delta()` — per-metric model − baseline (with sign flipped for Brier so positive = model wins).

- [src/evaluation/model_card/verdict.py](../../../src/evaluation/model_card/verdict.py) — added `use_case_verdicts_with_reasons()`. Each use case now reports the per-section sub-verdicts that drove its aggregate, so the report explains *why* a use case rejects.
  - **Note:** post-session edit dropped Section C from `threshold_gate` requirements (`["A", "E", "G"]` instead of `["A", "C", "E", "G"]`). Carried forward as an open question in the Phase 4 pending doc.

- [src/evaluation/model_card/builder.py](../../../src/evaluation/model_card/builder.py) — wired G + benchmarks.
  - New `ModelCard` fields: `use_case_reasons`, `benchmarks`.
  - New `ModelCardBuilder.__init__` args: `section_g_n_permutations`, `section_g_n_bootstrap`, `section_g_block_size_days`, `skip_benchmarks`.
  - `meta.phase` now reads `"3 (A/B/C/D/E/F/G + benchmarks)"`.
  - `render()` derives `json_path` from `html_path` stem so a custom `--output xxx_phase3.html` doesn't collide with the default-slug JSON.

- [src/evaluation/model_card/report.py](../../../src/evaluation/model_card/report.py) — added benchmarks block + per-use-case reason details in the verdict grid (each use case shows `A=PASS · D_binary=REJECT · ...` as a coloured detail line).

- [scripts/build_model_card.py](../../../scripts/build_model_card.py) — new flags: `--section-g-permutations`, `--section-g-bootstrap`, `--section-g-block-days`, `--skip-benchmarks`.

### Tests

- [tests/model_card/test_section_g_edge.py](../../../tests/model_card/test_section_g_edge.py) — 8 tests: perfect/random/degenerate/empty pools, sample-adequacy thresholds, shuffle helpers preserve per-day prevalence + total positives, date-block coverage.
- [tests/model_card/test_rubric_scoring.py](../../../tests/model_card/test_rubric_scoring.py) — extended with 4 verdict-aggregation tests covering use-case REJECT propagation, PENDING-when-section-not-implemented, consistency between short/long verdict APIs, and full-strong aggregate band.
- **Full suite: 43 passed in ~25s.**

### End-to-end verification

`scripts/build_model_card.py --model m01_binary/v1 --output model_cards/m01_binary_v1_phase3.html --skip-sepa-match --section-g-permutations 30 --section-g-bootstrap 30 --start-date 2025-09-12 --end-date 2026-05-22`

- **Build time: 14.13s** (target was < 90s)
- `meta.phase = "3 (A/B/C/D/E/F/G + benchmarks)"`
- Section G all 3 gates PASS on this narrow window
- Use-case verdicts all REJECT (driven by D-binary / D-magnitude / F gate failures — matches the framework doc's expected readout for the Sharpe-1.59-but-IC-negative model)
- Benchmarks block populated: model + sepa_composite + delta_vs_sepa_composite

Artifact: [model_cards/m01_binary_v1_phase3.html](../../../model_cards/m01_binary_v1_phase3.html) + `.json`

## ⏸️ Pending — Phase 4 (deferred)

See [phase_4_promotion_gate_pending.md](phase_4_promotion_gate_pending.md). Scope:

1. `models` table — add `model_card_path` + `model_card_built_at` columns.
2. `--require-promotion-pass <use_case>` flag on CLI; non-zero exit on REJECT.
3. Decision-log entry codifying the "no `is_production=true` without a card built ≤ 7 days ago, verdict ≠ REJECT, human sign-off" rule.
4. `DailyPipelineOrchestrator` Phase 10 — nightly card refresh when model version or eval window changes (advisory, non-blocking).
5. Open question: `verdict.py` edit dropped C from `threshold_gate` — confirm intent or revert.

Estimated effort: 0.5 day per the original plan.

## 🧠 Key design choices

- **Permutation strategy is metric-aware**: AUC uses global label shuffle (preserves total prevalence); per-day metrics (IC, top-K lift) use within-day shuffle (preserves per-day prevalence + universe size). Mirrors the existing `permutation_null.py` per-date approach but at classification-metric level.
- **Bootstrap blocks are calendar-day blocks** (60d default), not trade-count blocks. Same convention as `bootstrap.py` for trade Sharpe.
- **Section G defaults (500 perms × 500 bootstrap)** were chosen as percentile-resolution / runtime tradeoff. At 500 each, Section G runs in ~12s on a 1976-row eval pool. For full ~38K-row windows expect ~30–60s — still under the 90s build budget. CLI can lower for smoke tests.
- **SEPA-composite is a per-day cross-sectional rank**, not a raw blended score. This way, components on wildly different scales (RS rating 1–99 vs. pct_from_high_52w negative percentage) combine cleanly. Component weights are equal — no tuning, by design.
- **Verdict aggregation rule**: PASS > MARGINAL > PENDING > REJECT precedence — any single REJECT in the required-section list rejects the whole use case. PENDING wins over MARGINAL because a missing section is more uncertain than a known-weak section.

## 📁 Artifacts created

- `src/evaluation/model_card/sections/section_g_edge.py` (372 lines)
- `src/evaluation/model_card/benchmarks.py` (304 lines)
- `tests/model_card/test_section_g_edge.py` (130 lines)
- `model_cards/m01_binary_v1_phase3.html` + `.json` (sample output)
- `docs/session_logs/sprint_11/phase_4_promotion_gate_pending.md` (Phase 4 carry-over plan)

## 📁 Artifacts modified

- `src/evaluation/model_card/builder.py` — Section G + benchmarks wiring
- `src/evaluation/model_card/report.py` — benchmarks block + verdict reason rendering
- `src/evaluation/model_card/verdict.py` — `use_case_verdicts_with_reasons()` (later edited externally to drop C from threshold_gate)
- `src/evaluation/model_card/sections/__init__.py` — export `run_section_g`
- `src/evaluation/model_card/__init__.py` — comment updated
- `scripts/build_model_card.py` — Section G + benchmarks CLI flags
- `tests/model_card/test_rubric_scoring.py` — verdict-aggregation tests

## 🚀 Next session pickup

1. Read [phase_4_promotion_gate_pending.md](phase_4_promotion_gate_pending.md) first.
2. Resolve the open question about Section C being dropped from `threshold_gate` requirements.
3. Decide whether to do all four Phase 4 items or just the promotion-gate flag (the highest-leverage one).
4. If proceeding with full Phase 4, the `models` table schema edit and CLI flag are independent — do them in parallel.
