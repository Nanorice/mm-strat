# Issue: prob_elite Gate Mismatch Between EDA and Backtest

**Date**: 2026-07-11 · **Discovered during**: rotation anatomy Q44 follow-up
**Status**: ⚠️ OPEN — investigated, NOT resolved (user has further checks). The proposed fix below
(raise 0.15→0.20/0.25) was RERUN and is **wrong-signed**: it lowers the champion's median-Sharpe
cone. See `verdicts/2026-07-11_prob_elite_gate_sensitivity.md` for the paired 90-cell result,
EDA reconciliation, and replication spec. Summary: the gate is a VARIANCE knob (buys floor/%neg,
costs median/tail), not an alpha knob — keep `min_prob_elite=0.15`. Topic stays open pending
further variants (different exit, gate×selection, non-Sharpe objective).

---

## The Problem

There are **two separate prob_elite scales** in the project — they share the same column name but are produced by different pipelines:

| Context | Scale | Median | Gate Applied |
|---|---|---|---|
| EDA panel parquets (`sprint_summary_eda.ipynb`) | **Raw** XGBoost P(Class 3) | ~0.55 | `PRIMARY_GATE = 0.6` |
| Backtest score cache (`universe_scorer`) | **Calibrated** (isotonic) | ~0.12 | `min_prob_elite = 0.15` |

The EDA's 0.6 raw gate was chosen deliberately — it sits above the raw-scale median and trims the "quality leak" left tail. The backtest's 0.15 calibrated gate was set as a "coin-flip floor" (just above calibrated median of ~0.12). **These two gates are not equivalent and were never reconciled.**

---

## The Invalidation Case

On **famine days** — days with sparse breakout supply where even the best available candidate has low model confidence — the backtest still enters the top-ranked name as long as its calibrated `prob_elite ≥ 0.15`. The EDA gate (0.6 raw ≈ approximately 0.20+ calibrated) would have stood aside.

This is the "best of a bad lot" problem: the strategy fills a slot with a low-quality signal simply because no slot-blocking mechanism (regime gate, cooldown) is active.

---

## Measured Exposure (Champion Book, 90 Rolling Cells, 2,072 Pooled Trades)

| Calibrated `prob_elite` | Trade Count | Share | Mean PnL | Win Rate |
|---|---:|---:|---:|---:|
| < 0.15 *(below current floor — should not exist)* | 46 | 2.2% | −32% | 28% |
| **0.15–0.20 ← the gap zone** | **369** | **17.8%** | **−42%** | **31%** |
| 0.20–0.25 | 122 | 5.9% | +24% | 25% |
| 0.25–0.30 | 1,043 | 50.3% | +22% | 29% |
| > 0.30 | 492 | 23.7% | +ve | 29–31% |

**~20% of all entered trades are in the gap zone (0.15–0.20 calibrated)** — the trades a tighter gate would block. This cohort is collectively P&L-negative.

> ⚠️ These are pooled across 90 overlapping cells — not deduplicated. Absolute PnL figures are unreliable due to double-counting. The **relative ordering** (low prob_elite → negative cohort) is valid.

---

## Root Cause

`_base_kwargs()` in [`strategy_registry.py`](file:///c:/Users/Hang/PycharmProjects/quantamental/src/backtest/strategy_registry.py#L141) sets:

```python
"min_prob_elite": 0.15,   # too soft — calibrated median is ~0.12
"min_score": 0,            # normalized_score gate off entirely
```

The 0.15 floor was never calibrated against the EDA's 0.6 raw threshold. No one mapped raw → calibrated when the gate was introduced.

---

## What Is NOT Invalidated

- The **regime gate** (SPY >200d) already blocks the worst famine-day conditions. The low-quality entries cluster in weaker regime periods, which is partially overlapping with periods the gate already shuts.
- The **structural SEPA gate** (`trend_ok + breakout_ok`) remains the primary alpha filter — the prob_elite gate is a secondary quality floor, not the main selector.
- The **relative findings** of the rotation anatomy (slot-constrained, queue quality, refill timing) are unaffected — they analyse what the backtest did, not what an ideal gated strategy would do.

---

## Proposed Fix

Raise `min_prob_elite` in `_base_kwargs()` from **0.15 → 0.20** (or test 0.25) and run one forward sweep:

```python
def _base_kwargs(n: int) -> Dict[str, Any]:
    return {
        ...
        "min_prob_elite": 0.20,   # was 0.15 — tighter quality floor
        ...
    }
```

**Expected effects:**
- Fewer entries on low-supply / famine days
- Higher mean P&L from surviving book (gap-zone drag removed)
- Possibly lower deployment days — check against regime gate overlap to ensure this isn't double-counting protection already in place

**Key question to answer**: How many of the 415 gap-zone trades occurred on days the SPY regime gate was already active? If >80%, the practical impact of fixing this is small. If <50%, fixing it would meaningfully change cone results.

---

## Priority

**Medium** — the results are directionally valid but overstated on famine days. Worth a one-parameter sweep before treating the champion book numbers as final for any live deployment decision.
