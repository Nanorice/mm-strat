# Sprint 11 — Research Log

This is the linear train-of-thought for the sprint, tracking questions and their resolution.

## Thread A: Model Evaluation Rigor
1. **How do we standardise model promotion?** → Built a 7-section automated model card (`build_model_card.py`) assessing Integrity, Discrimination, Calibration, Ranker Quality, Gates, Robustness, and Edge. Imposed blocking gates (e.g. AUC > 0.55). [2026-05-25_02_model-card-phase-1-and-2.md](logs/2026-05-25_02_model-card-phase-1-and-2.md)
2. **How do we evaluate entry-timing vs holding-ranking?** → Implemented dual-mode pools. Mode A evaluates purely on the entry ledger (home-run probability). Mode B builds a stateful daily pool to evaluate the daily ranking stability (Spearman IC). [2026-05-26.md](logs/2026-05-26.md)

---

## Open meta-questions
- **Data Quality upstream**: The Section A integrity checks revealed that `BAD_TICKERS` (like LIF and CUE) are still present in the `d2_training_cache`. We need to filter these upstream to prevent model cards from being marked VOID.
