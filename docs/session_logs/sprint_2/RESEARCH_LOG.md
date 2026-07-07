# Sprint 2 — Research Log

This is the linear train-of-thought for the sprint, tracking questions and their resolution.

## Thread A: Modeling Strategy
1. **How do we reliably predict breakout success?** → It's easier to predict losers than winners. We built M02 (Loser Detector) using the Triple Barrier method, and restricted M01 ("Survivor Model") to only train on trades that survived the stop-loss, predicting their Log-Space MFE. [sprint_2_summary.md](verdicts/sprint_2_summary.md)
2. **How do we prevent entering during bad markets?** → Built M03, a 3-pillar Market Regime system (Trend, Liquidity, VIX), serving as a macro traffic light to gate trades.

## Thread B: Infrastructure & UX
1. **How do we visualize all these models?** → Overhauled the dashboard with Plotly, adding D1 Analysis, M01/M02 metrics, and interactive MAE/MFE scatters powered by pre-generated JSON reports.

---

## Open meta-questions
- **Data Bottlenecks**: The parquet-based pipeline is becoming cumbersome. Can we achieve better performance and alignment by moving feature engineering to SQL (DuckDB)?
