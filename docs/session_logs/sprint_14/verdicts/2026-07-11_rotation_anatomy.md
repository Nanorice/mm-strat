# Rotation anatomy of the champion book — slot-constrained, not signal-constrained

**Date**: 2026-07-11 · **Thread**: J (portfolio layer) · **Q**: 44
**Data**: the 90 persisted `champion_trail_spygate/rolling` cone cells
(`data/selection_sweep/starttime/champion_trail_spygate/rolling/*/{trades,rejections,equity}.parquet`)
— pure artifact analysis, no re-runs. 2,072 pooled trades (1,476 deduped by ticker+entry),
~118k rejection rows.

## Question

The equity fan is a per-draw view (no re-entry). The BackTrader champion is a rotating book.
What does the rotation actually look like — and is capital or signal the binding constraint?

## Findings

### 1. The book runs near-full and refills instantly
Per 12-month cell (median across 90 cells): **23 trades**, median hold **29d**, mean open
positions **3.8 / 5**, **55% of days at full 5/5**, only 10% of days empty (gate-shut periods).
Median exit→refill latency is **0 trading days** — the moment a slot frees, the queue fills it.
Exit mix (deduped): **52% stop / 45% trend-exit / 3% regime liquidation**.

### 2. The rejected queue is nearly as good as the book ← the headline
`no_slots` rejections fire on ~162 of ~252 days/year (median 1,312 rejected signals per cell-year).
Label-level fwd100 (gated-panel join, apples-to-apples):

| cohort | n | mean fwd100 | median | loss | HR>30% |
|---|--:|--:|--:|--:|--:|
| ENTERED names | 1,468 | **+6.4%** | +1.9% | 48% | **21.0%** |
| no_slots QUEUE | 49,870 | **+5.7%** | +2.2% | 47% | **17.5%** |

The book skims a slightly better slice (score median 28.9 vs queue 19.1 raw), but the marginal
queued name earns ~90% of the booked edge. **The strategy is slot-constrained, not
signal-constrained** — additional capital deployed as additional slots would dilute only mildly
(HR 21→17.5% at the margin). This is the quantitative licence for breadth/aggregation.

### 3. Rotation timing is quality-neutral (no adverse selection)
First pass showed refill trades underperforming (mean +0.09% vs initial +2.58% / drip +1.98%),
but it decomposes away: freed-by-stop refills (+0.25%) ≈ freed-by-trend refills (−0.61%), and
within regime 4 refill ≈ drip (+2.8 vs +3.0%). The gap is regime composition (refills cluster
where exits cluster), not a timing defect. Regime 1 entries are the only structurally bad cohort
(−3.8% mean, 24% win) — consistent with the deploy-gate arc.

## Verdict

Rotation already does what the fan can't show: recycles capital ~4.6× per slot-year at neutral
timing quality, drawing from a deep queue of near-book-quality signals. The open portfolio
question is therefore **entry cadence and slot count** (how to spread the near-flat queue across
time/capital), not signal supply. → feeds the max-1-position-per-day temporal-breadth test (Q45).

## Caveats
- Rolling 12m cells overlap (quarterly starts) — per-cell stats are draw-level; pooled trade stats deduped.
- Role classification (initial/drip/refill) is a 7-day-window heuristic.
- Queue-vs-book comparison is label-level fwd100, not exit-realized P&L (the queue was never traded).
