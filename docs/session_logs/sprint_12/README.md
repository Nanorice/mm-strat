# Sprint 12 — Infra uplift, slim dashboard DB, model card promotion gate

**Dates:** 2026-06-09 → 2026-06-16 · **Status:** ✅ Closed · **Next:** [sprint_13](../sprint_13/README.md)

> Infra that supports training/evaluation workflow, slim dashboard DB synced across devices, and model card promotion gate.

### Folder map
- **`RESEARCH_LOG.md`** — the linear question ledger (how the thinking evolved, by sequence).
- **`logs/`** — dated session handovers (`YYYY-MM-DD_NN_<slug>.md` + `_index.md` on multi-session days).
- **`plans/`** — forward-looking design/plan docs.
- **`verdicts/`** — findings, reports, issues, playbooks.
- **`cells/`** — notebook-cell artifacts.

### Headline outcomes
- **Slim Dashboard DB** — built `dashboard.duckdb` (783 MB from 67 GB, 98.8% reduction), parameterised app DB path, verified 18/18 loaders return valid current rows. Sync mechanism to be implemented.
- **Model Card Phase 4** — wired the card verdict into `ModelRegistry.set_prod()` as an ADVISORY WARNING (does not block).
- **Training/Eval Infra Verification** — flow works end-to-end; fixed a real case-sensitivity bug in `get_model_features`; candidate `m01_prototype/v2` card band=WEAK (ranks well, calibration fails). Not promoted.
- **Documentation** — updated `comprehensive_methodology.md` and `manual_for_me.md` with model dev lifecycle and runbooks.
- → full question ledger: [RESEARCH_LOG.md](RESEARCH_LOG.md)

## Roadmap & Goals
- [x] Slim Dashboard DB (build script, parameterise path, verify load)
- [~] Cross-Device Sync (S1-S3 done, S4 Task Scheduler runbook open)
- [x] Model Card Phase 4 (Promotion Gate)
- [x] Training/Eval Infrastructure Verification
- [x] Documentation update (Model Dev Lifecycle)

## Carried over from sprint 11
- [ ] Universe lifecycle automation (outflow side)
- [ ] Mode B analytics (score trajectory)
- [ ] Feature drift / PSI quarterly trigger
- [ ] Eval framework Phase 4 (scope TBD)
- [ ] Risk: 5-factor model improvements
- [ ] `earnings_calendar` at-scale rate-limit
- [ ] Audit script timeout 120s → 600s

## TODOs
<All active TODOs moved to Sprint 13>
