# Sprint 11 Summary (Mid-Sprint)

**Goal:** Solidify the system's infrastructure, establish an irrefutable evaluation framework, and determine the path forward for the core modelling strategy.

## 🏆 Key Accomplishments So Far

### 1. Comprehensive System Documentation
* **`comprehensive_methodology.md` & `manual_for_me.md`**: Created definitive, authoritative guides detailing the system architecture, pipeline mapping, data engineering, and replication steps. The project is now fully document-driven and reproducible.
* **`model_development_methodology.md`**: Codified an **8-gate pipeline** for model development to prevent structural mistakes (like uncalibrated probabilities or overlapping forecast horizons) from reaching deployment.

### 2. Strategy Pivot: The "m01_rank" Verdict
* Evaluated the dual-model thesis (prototype selects, rank times). Discovered that `m01_rank`'s scores are horizon-invariant (1d and 20d are 0.92 correlated), meaning it captures general *setup quality* rather than precise timing.
* **Decision:** Treat timing as a price-action problem (using ATR stops and trend breaks) rather than an ML problem. Use the ML model as a robust **threshold filter** (e.g., `P(MFE > 30%) ≥ 0.30`) rather than a magnitude ranker.

### 3. "Deep Rigor" Evaluation Framework
* Upgraded the evaluation infrastructure from standard metrics to an academic-grade suite:
  * **Walk-Forward Cross-Validation**: Anchored walk-forward training and backtesting to prevent overlapping lookahead bias.
  * **Regime-Conditional Metrics**: Breaking down model performance by Strong Bull, Bull, Neutral, Bear, and Strong Bear markets.
  * **Calibration Audits**: Implementing Expected Calibration Error (ECE) and Isotonic calibration to ensure probability outputs reflect real-world hit rates.
  * **Robustness Tools**: Block Bootstrap CI on trades, Permutation null backtesting, Decile IC analysis, and automated Feature Ablation backtesting via `run_deep_rigor_suite.py`.

### 4. Model Card Framework (Phases 1 & 2)
* Built an automated, 7-section model card generator (`build_model_card.py`) that produces numerical (0-3) rubric scores.
* **Sections Shipped:** Integrity, Discrimination, Calibration, Ranker Quality, Threshold Gates, and Robustness.
* Supports **Mode A** (entry-only ledger) and **Mode B** (stateful daily SEPA pool), proving that binary classification works beautifully as a filter but poorly as a strict magnitude ranker.

### 5. Data Quality & Operational Fixes
* Identified and resolved a critical fan-out bug in `v_d2_features` (caused by correlated subqueries in `fundamental_features` and `shares_history`).
* Migrated a new `daily_predictions` table to log paper trades and decisions directly from the daily pipeline.

---

## 🚀 Remaining Work for Sprint 11 (1 Week to Go)

1. **Dashboard Polish:** Skip Page 2 (Ticker Deep Dive) for now. Instead, add an outbound link for each ticker to a 3rd party site (e.g., TradingView) for company research. Wire the `daily_predictions` Decision Log to the UI.
2. **Model Card Phase 4 (Integration):** Phase 3 (Section G: Edge vs. Baselines) is now complete. Next, wire the Model Card's verdict directly into the `ModelRegistry.set_prod()` promotion gate (and add card paths to the registry schema).
3. **Deploy the Production Model (`m01_prototype`):** Retrain the current production model (`m01_prototype`, which uses the refined feature set and longer horizon) on the newly cleaned, fan-out-free dataset. Decide on the final deployment pattern (e.g., Strategy S3: calibrated probability threshold + 5-position cap) and officially promote it to prod.
4. **Stateful Scoring Assessment (Mode B Analytics):** Assess the ability of the prototype to constantly update scores over time (which we are already using operationally). Evaluate the correlation of daily scores with forward returns across different horizons, and analyze how the score trajectories evolve for "super performers" vs. ordinary trades.
5. **Feature Drift Monitoring:** Finalize the quarterly trigger for the PSI (Population Stability Index) drift report.
