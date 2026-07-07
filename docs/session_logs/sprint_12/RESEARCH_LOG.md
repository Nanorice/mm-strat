# Sprint 12 — Research Log

This is the linear train-of-thought for the sprint, tracking questions and their resolution.

## Thread A: Dashboard DB & Synchronization
1. **How much smaller can we make the database for the dashboard without losing functionality?** → Reduced from 67 GB to 783 MB (98.8% reduction) by extracting only the required view slice. [2026-06-11_02_slim_dashboard_db.md](logs/2026-06-11_02_slim_dashboard_db.md)
2. **How do we sync this database across devices?** ? Open. R2 + Cloudflare worker approach designed, S4 step pending. [dashboard_sync_deploy_plan.md](plans/dashboard_sync_deploy_plan.md)

## Thread B: Model Card Promotion Gate
3. **Should the model card threshold failures hard-block promotion?** ⟳ Originally planned as a block, revised to ADVISORY ONLY because thresholds are hand-set and unvalidated. [DONE_phase_4_promotion_gate.md](../sprint_11/DONE_phase_4_promotion_gate.md)

## Thread C: Training Infrastructure
4. **Does the end-to-end pipeline work on the clean dataset?** → Yes, but fixed a silent case-sensitivity bug in `get_model_features`. [DONE_t3_infra_verification.md](verdicts/DONE_t3_infra_verification.md)
5. **Is candidate `m01_prototype/v2` ready for promotion?** → No, it ranks well but fails calibration (raw 4-class booster, ECE 0.132 vs 0.05 gate). [DONE_t3_infra_verification.md](verdicts/DONE_t3_infra_verification.md)

---

## Open meta-questions
- **Cross-device sync**: How do we finalize the Task Scheduler runbook for the nightly pipeline to sync to R2?
