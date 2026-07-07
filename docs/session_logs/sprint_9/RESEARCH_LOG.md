# Sprint 9 — Research Log

This is the linear train-of-thought for the sprint, tracking questions and their resolution.

## Thread A: T3 Universe Architecture
1. **How do we efficiently limit the size of the T3 features table?** → Shifted to Option C: an event-log approach (`sepa_watchlist`) that tracks entry, exit, and cooldown of SEPA breakouts. Phase 4b now manages this lifecycle. [2026-05-08_02_wrapup.md](logs/2026-05-08_02_wrapup.md)

## Thread B: Backtest Realism
1. **Why does the vectorized backtester show 500% returns while reality underperforms?** → Vectorized execution assumes infinite capital and zero position limits, cherry-picking every trade. Built a sequential backtester that enforces `max_positions` and proved the strategy currently underperforms SPY. [2026-05-09_03_session3.md](logs/2026-05-09_03_session3.md)

---

## Open meta-questions
- **Strategy Viability**: The sequential backtest returned a 9.3% CAGR with a 35.7% max drawdown, significantly lagging SPY. How can we improve edge (e.g. 5-factor risk gate) to make this investable?
