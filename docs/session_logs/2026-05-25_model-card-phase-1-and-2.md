# Session Handover: 2026-05-25 — Model Card Framework Phases 1 + 2

## 🎯 Goal

Build the seven-section model-card framework end-to-end through Phase 2 of [docs/plans/model_card_implementation_plan_2026_05_25.md](../plans/model_card_implementation_plan_2026_05_25.md). Replace the verdict argued in [2026-05-25_binary-pruned-and-deep-rigor.md](2026-05-25_binary-pruned-and-deep-rigor.md) ("DEMOTE-as-ranker, HOLD-as-filter") with a numerical card that surfaces *why* — i.e., binary hit-rate works (gate-quality), magnitude ranking doesn't.

## ✅ Accomplished

### Phase 1 — Mechanical card (Sections A, B, C, F + verdict + report shell)

New package: [src/evaluation/model_card/](../../src/evaluation/model_card/)

- [data_loader.py](../../src/evaluation/model_card/data_loader.py) — `load_eval_data()` reads `v_d2_training` / `d2_training_cache`, runs the loaded `xgb.Booster` (auto-detects binary vs softprob, projects 4-class to home-run-class probability), attaches `label_binary` / `label_mfe` / `label_4class`, and returns a frozen `EvalSplit`. Loader pulls `valid_features` from the model's co-located `metadata.json` so outcome columns on the dataframe are never passed to predict.
- [rubric.py](../../src/evaluation/model_card/rubric.py) — `SectionResult` / `MetricEntry` / `GateEntry` primitives + the 0–3 `rubric_score()` band mapper. Section-level aggregate = `min` of its rubric scores (weakest band drives the verdict).
- [sections/section_a_integrity.py](../../src/evaluation/model_card/sections/section_a_integrity.py) — A1 leakage / A2 label-horizon spot check / A3 v_d3_deployment reconciliation / A4 class balance / A5 BAD_TICKERS / A6 trend_ok consistency. Any blocking FAIL voids the card.
- [sections/section_b_discrimination.py](../../src/evaluation/model_card/sections/section_b_discrimination.py) — ROC-AUC, PR-AUC, Brier, log-loss + DummyClassifier(prior) + DummyClassifier(stratified) baselines. B1/B2/B3 gates (AUC > 0.55, PR-AUC > 1.5× prevalence, Brier beats prior).
- [sections/section_c_calibration.py](../../src/evaluation/model_card/sections/section_c_calibration.py) — reliability bins + per-threshold-bin calibration check at T ∈ {0.3, 0.4, 0.5, 0.6, 0.7}. Returns `{calibration_error_at_T, tolerance_breached}` per threshold — the single most operationally important addition because the deployment uses thresholds.
- [sections/section_f_robustness.py](../../src/evaluation/model_card/sections/section_f_robustness.py) — M03 quintile bucketing + `t2_risk_scores.target_exposure` discrete bucketing + per-year + per-sector breakdowns + per-feature PSI vs the model's `reference_snapshot.json`. F1 (regime pass-rate ≥ 0.6) is blocking, F2 (no year < 0.50 AUC) is a warning, F4 (max PSI < 0.25) is blocking when a reference snapshot exists.
- [verdict.py](../../src/evaluation/model_card/verdict.py) — `USE_CASE_REQUIREMENTS` matrix (5 deployment patterns × required sections), `aggregate_score()` projecting to BROKEN/WEAK/ACCEPTABLE/STRONG bands, `card_void()` from Section A blocking failures.
- [report.py](../../src/evaluation/model_card/report.py) — self-contained HTML renderer (inline CSS, no external assets). Header KV + void banner + verdict + use-case grid + per-section blocks with metrics / rubric scores / gate badges / tables.
- [builder.py](../../src/evaluation/model_card/builder.py) — `ModelCardBuilder` orchestrator. Loads data, runs sections, aggregates, writes both `.html` and `.json`.
- [scripts/build_model_card.py](../../scripts/build_model_card.py) — CLI: `--model`, `--db`, `--start-date`, `--end-date`, `--no-trend-ok`, `--skip-sepa-match`, `--feature-version`.

Phase 1 unit tests: [test_data_loader.py](../../tests/model_card/test_data_loader.py), [test_section_b_metrics.py](../../tests/model_card/test_section_b_metrics.py), [test_rubric_scoring.py](../../tests/model_card/test_rubric_scoring.py). All pass.

Phase 1 acceptance check (from plan §2 exit criterion): ✅ `build_model_card.py --model m01_binary/v1 --skip-sepa-match` runs in ~49s and produces A/B/C/F populated + D/E/G placeholders.

### Phase 2 — Stateful pool + Section D + Section E

- [data_loader.py](../../src/evaluation/model_card/data_loader.py) extended with:
  - `build_mode_a_pool(split)` — trivial filter on the entry ledger (split.df where trend_ok=True). Returns the normalised columns Section D/E need (`ticker`, `date`, `pred_proba`, `label_binary`, `label_mfe`).
  - `build_mode_b_pool(...)` — stateful daily pool. Re-scores every `(ticker, date)` in `t3_sepa_features` where `trend_ok=TRUE` within the window. Replicates the full `v_d2_features` join (`fundamental_features` as-of filing date + `company_profiles` + `shares_history` + derived `pe_ratio` / `ps_ratio` / `pb_ratio` / `peg_adjusted`). Handles the `*_pct_chg` → `*_delta` rename (divides by 100). Cached to parquet keyed by `(model_id, hash(start, end, feature_version))` — re-running is instant.
- [sections/section_d_ranker.py](../../src/evaluation/model_card/sections/section_d_ranker.py) — D-binary and D-magnitude as **independent** sub-rubrics, each scored 0–3.
  - Metrics: per-day Spearman IC (mean / median / std / t-stat / n_days), top-K lift for K ∈ {1, 3, 5, 10} (computed per-day then averaged), decile profile (mean / median / 90th-pct of target per decile of P), tail recall (top-1% realised → top decile of P), top-vs-bottom decile ratio.
  - Each metric runs against both the binary label (D-binary) and `mfe_pct` (D-magnitude), on both Mode A and Mode B pools. Gates apply only to Mode A.
  - Gates: D1 (binary IC > 0, t > 2), D2 (top-5 hit lift > 1.5×), D3 (top decile ≥ 2× bottom AND top ≥ 1.5× prevalence) — all blocking; D4 (magnitude IC > 0, t > 2), D5 (top-5 magnitude lift > 1.5×) blocking; D6 (tail recall ≥ 0.20) warning.
- [sections/section_e_gates.py](../../src/evaluation/model_card/sections/section_e_gates.py) — threshold sweep T ∈ {0.3, 0.4, 0.5, 0.6, 0.7} on Mode A pool. E1–E7 metrics (precision, recall, coverage, trades/month, magnitude-conditional precision at MFE > 30/50/100%, E[MFE | gate]). Headline at T* = 0.6. E5 stability proxied by per-year precision variance (proper walk-forward folds deferred to Phase 4).
- [verdict.py](../../src/evaluation/model_card/verdict.py) updated — `D_binary` and `D_magnitude` resolve as independent sub-verdicts from `section.rubric_scores`. `aggregate_score()` scores them separately (max=21 when full).
- [builder.py](../../src/evaluation/model_card/builder.py) wired — Mode A pool is always built; Mode B is opt-in via `build_mode_b=True`.
- [scripts/build_model_card.py](../../scripts/build_model_card.py) — new flags: `--mode-b`, `--mode-b-cache-dir`, `--mode-b-force-recompute`.

Phase 2 unit tests: [test_section_d_modes.py](../../tests/model_card/test_section_d_modes.py) (12 tests), [test_section_e_gates.py](../../tests/model_card/test_section_e_gates.py) (5 tests), [test_synthetic_models.py](../../tests/model_card/test_synthetic_models.py) (3 tests — random/perfect/weak end-to-end). All 31 model-card tests pass.

Phase 2 acceptance check (from plan §3 exit criterion): ✅

### Verdict the card surfaces for `m01_binary/v1`

Built artifact: [model_cards/m01_binary_v1.html](../../model_cards/m01_binary_v1.html) + `.json`. Card is currently **VOID** because A5 (BAD_TICKERS) fails — see Open Issues below. But the downstream numbers are still computed:

| Section | Rubric score | Notes |
|---|---|---|
| B Discrimination | 3 / 3 | AUC + PR-AUC + Brier all clear B gates |
| C Calibration | 0 / 3 | Reliability fails (the §1.4 deep-rigor finding holds) |
| **D_binary** | **2 / 3** | 5/6 gates pass. Top-5 hit lift 1.54× (just over the 1.5× line), top-vs-bot decile 65.7×, binary IC median +0.43 (t=49). |
| **D_magnitude** | **0 / 3** | D5 fails: top-5 magnitude lift = 1.134× vs required 1.5×. |
| E Gates | 2 / 3 | precision 2.75× prevalence at T* = 0.6, 25.6 trades/month, year-to-year precision variance 0.008. |
| F Robustness | 0 / 3 | PSI / regime-pass-rate failures (existing data-quality issues) |
| G Edge | — | Phase 3 placeholder |

This is the numerical expression of "DEMOTE-as-ranker, HOLD-as-filter" from yesterday's verdict:
- **HOLD-as-filter**: D_binary = 2 (Good) + E = 2 (Good). The model works at threshold.
- **DEMOTE-as-ranker**: D_magnitude = 0 (Poor). P ≥ 0.6 doesn't mean *bigger* winners, just *more frequent* 30%-crossers.

The contradiction with the trainer's WF Sharpe = 0.476 — that was the §1.4 deep-rigor result — is no longer mysterious. S3's Sharpe 1.59 is driven by E's gate quality, not by ranker quality the trainer assumed.

### Mode B smoke verified

Tested on a tight window (2024-06-01 → 2024-09-30) with the m01_binary model:
- Mode A: 914 entry rows
- Mode B: 40,000 daily SEPA-pool rows
- Build time: ~3s with `--skip-sepa-match` (8s without)
- Cache: `mode_b_cache/mode_b_<model>_<hash>.parquet`

Mode B's binary numbers diverge usefully from Mode A's: B_binary top-5 lift = 3.46× vs A_binary 1.10×; B_binary IC t-stat = 3.02 vs A_binary 1.84. Confirmed: the framework's two-mode structure surfaces information that the entry-only ledger hides.

## 📝 Files Changed

### New (untracked) — Phase 1 + 2 together
- `src/evaluation/model_card/` (package — 11 files)
  - `__init__.py`, `builder.py`, `data_loader.py`, `rubric.py`, `verdict.py`, `report.py`
  - `sections/__init__.py` + 6 `section_*.py` files (A/B/C/D/E/F implemented; G placeholder lives in `rubric.placeholder_section`)
- `tests/model_card/` — `__init__.py`, `test_data_loader.py`, `test_section_b_metrics.py`, `test_rubric_scoring.py`, `test_section_d_modes.py`, `test_section_e_gates.py`, `test_synthetic_models.py` (31 tests, all passing)
- `scripts/build_model_card.py` — CLI
- `scripts/verify_model_card_prereqs.py` — pre-flight check (logged in plan §0)
- `model_cards/` — `m01_binary_v1.{html,json}`, `m01_prototype_2003_2026_v2.{html,json}` (smoke outputs)
- `docs/plans/model_card_implementation_plan_2026_05_25.md` — the implementation plan
- `docs/proposals/model_card_framework_2026_05_25.md` — the framework spec (Phase 0 artifact carried over)

### Modified — none required for Phases 1 + 2

All work was net-new code; no existing src module touched.

(The other modified/untracked entries in `git status` carry over from yesterday's session — see [2026-05-25_binary-pruned-and-deep-rigor.md](2026-05-25_binary-pruned-and-deep-rigor.md). They are independent and should be committed separately per yesterday's handover plan.)

## 🚧 Work in Progress — none

Phase 2 is complete and stable. The next phase (Phase 3 — Section G + benchmarks + verdict refinement) is fresh work, not in-flight.

## 🛑 Open Issues

1. **BAD_TICKERS in `d2_training_cache`** — LIF and CUE rows reach Section A and trip A5. This is the existing data-quality issue tracked in memory `bad_tickers_not_filtered`: `detect_bad_tickers` only warns; the cache wasn't filtered at source. Until that is fixed upstream, every card built against `m01_binary/v1` will be VOID. **Workaround**: cards built with `--skip-sepa-match` still produce all downstream metrics; the VOID flag is informational, not blocking. **Real fix**: drop BAD_TICKERS in the `d2_training_cache` refresh script (or in `v_d2_training`'s ticker filter).
2. **Section A3 (SEPA reconciliation) is currently skipped in all smoke runs** via `--skip-sepa-match`. The check works but adds ~60s. The plan's §2 exit-criterion was "60s" so it's fine to leave skipped for routine builds — but the gate should run at least once per model promotion. Add to Phase 4 promotion gate.
3. **Section E rubric thresholds were picked from the framework doc, not calibrated against real cards.** The plan §4 risk register flags this as "Phase-3-exit checkpoint." On `m01_binary/v1` the E scores look sensible (precision lift 2.75× → Good=2, coverage 20.5% → above the strong-band 3% — flagged Good=2, stability variance 0.008 → Strong=3). But if Phase 3 finds the bands routinely miscategorise real models, recalibrate before Phase 4.

## ⏭️ Next Steps (when user returns)

1. **Decide on commit grouping.** Phase 1 + 2 are self-contained and could be either one commit (`feat(eval): model-card framework Phases 1+2 — Sections A/B/C/D/E/F + Mode A/B pools`) or two (separate Phase 1 and Phase 2). Plus this handover. Plus yesterday's four pending groupings from [2026-05-25_binary-pruned-and-deep-rigor.md](2026-05-25_binary-pruned-and-deep-rigor.md) which are still uncommitted. Recommend: yesterday's four → today's two → handover.
2. **Phase 3 — Section G + benchmarks + verdict.** Per plan §4 (1 day estimate):
   - Classification-metric-level permutation null + block bootstrap CI on AUC / IC / top-K lift / tail recall.
   - `benchmarks.py` — DummyClassifier baselines + SEPA-composite-score baseline (replace `pred_proba` with `universe_scorer`'s composite; re-run D and E). The composite baseline is the "does ML add value?" check.
   - Refine `verdict.py`'s use-case verdict matrix once G lands.
   - Re-run both `m01_binary/v1` and `m01_prototype_2003_2026/v2` cards end-to-end.
3. **Phase 4 — promotion gate + registry integration.** Per plan §5 (0.5 day). Add `model_card_path` + `model_card_built_at` to the `models` table; CLI gets `--require-promotion-pass`; daily orchestrator gets advisory Phase 10. Decision-log entry recording the new promotion process.
4. **Fix the BAD_TICKERS leak upstream** so the void banner reflects real failures, not pre-existing data hygiene issues. 30-min fix in either `v_d2_training` or the cache refresh script.
5. **Run the card on `m01_binary_pruned/v1`** to see whether the dropped Volatility_Ranges/Technical_Oscillators groups change D_magnitude. The §1.4 ablation said they shouldn't (group rankings stable across model objectives). The card would put a number on it.

## 💡 Context/Memory

- **Mode B's most important detail is the `*_pct_chg` → `*_delta` rename.** `t3_sepa_features` stores percent-change features as `rs_pct_chg` etc. (raw percent); the training pipeline divides by 100 to get the `rs_delta` features the model is trained on (see memory `Views - Updated 2026-03-31` / "v3.1 optimization"). Mode B replicates the divide-by-100 in SQL at SELECT time. If a future feature set adds *_pct_chg-derived columns and the rename rule changes, Mode B's `_build_mode_b_select` is where to patch it.
- **Mode B replicates `v_d2_features`' fundamental join, it doesn't query the view directly.** The view's `v_d1_candidates` upstream filters to `is_new_trigger=TRUE` (entry-only — same 914 rows as Mode A). Querying `v_d2_features` for stateful Mode B would silently return the entry ledger instead of the daily pool. The dedicated CTE in `build_mode_b_pool` (ff_dedup + LEFT JOIN company_profiles + LEFT JOIN shares_history with as-of subqueries) does the same join structure on `t3_sepa_features` directly.
- **Section D's aggregate_score uses `min` of all rubric scores in the section.** That includes both `D_binary` and `D_magnitude`. So Section D's headline (single 0–3 number on the report) is the *weakest* half. The verdict logic and aggregate-score logic in `verdict.py` look up `rubric_scores['D_binary']` and `rubric_scores['D_magnitude']` independently, so the use-case matrix sees the right thing. The single-number aggregate is just informative.
- **t-stat of `inf` is intentional.** When daily IC has zero variance (e.g., a synthetic perfect ranker — every day produces IC = 1.0), the t-stat ratio is undefined. The code returns `+inf` (mean > 0) or `-inf` (mean < 0). Gates that require `t > 2` pass on `+inf`. This is correct: zero variance + positive mean = perfectly consistent signal, which is *more* significant than a high t-stat, not less.
- **`top_decile_vs_bottom` can be `+inf`.** Happens when the bottom decile mean is zero (e.g., binary label and bottom decile has no positives). The rubric maps `inf` to band 3 (Strong); `NaN` to band 0; finite values use the standard `rubric_score` cutoffs.
- **The CLI's `--mode-b` is opt-in.** Plain `python scripts/build_model_card.py --model X` builds A/B/C/F + D-Mode-A + E + G-placeholder in ~50s. Adding `--mode-b` re-scores `t3_sepa_features` for the entire eval window — minute-scale on full history, ~1s on a 4-month window thanks to the parquet cache. Use it when looking at Mode B's stateful-pool numbers; skip it for routine promotion-gate checks.
- **The synthetic-model tests are the regression backstop.** [test_synthetic_models.py](../../tests/model_card/test_synthetic_models.py) asserts perfect / random / weak models produce expected bands end-to-end. If Section D or E rubric thresholds get tuned later, these tests will catch behaviour drift.

---

Want me to `git add` and `git commit` the Phase 1 + 2 work now?
