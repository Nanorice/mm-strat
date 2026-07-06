# M02 signal-quality gate — report

> Generated 2026-07-04T23:43:57 by `scripts/analyze_m02_signal_quality.py`.
> All scores OUT-OF-SAMPLE (WF fold models on their test windows + final model on the
> post-train tail). Panel rows: 3,153,645. Gate criteria: prod-gap plan Phase 0.1.

## (a) Lead time vs M01 watchlist entry (lookback 60d, signal = daily top decile)

- Watchlist entries in span: **10,498**, with a prior M02 signal: **9,631**
  (coverage **91.7%**)
- Lead time days: median **42**, IQR [21, 57]
- Mean 21d fwd return from M02 signal date: **+4.16%**
  vs from M01 entry date: **+0.56%**

## (b) Score decile vs forward returns (the anti-circularity test)

|   decile |      n | fwd_5d   | fwd_10d   | fwd_21d   | ignition_rate   |
|---------:|-------:|:---------|:----------|:----------|:----------------|
|        1 | 315979 | +0.21%   | +0.42%    | +0.79%    | 2.2%            |
|        2 | 315834 | +0.18%   | +0.33%    | +0.57%    | 2.2%            |
|        3 | 315696 | +0.17%   | +0.32%    | +0.64%    | 2.3%            |
|        4 | 315569 | +0.17%   | +0.32%    | +0.58%    | 3.0%            |
|        5 | 315434 | +0.23%   | +0.45%    | +0.88%    | 5.6%            |
|        6 | 315290 | +0.26%   | +0.51%    | +1.02%    | 10.5%           |
|        7 | 315159 | +0.30%   | +0.56%    | +1.15%    | 16.2%           |
|        8 | 315024 | +0.28%   | +0.55%    | +1.13%    | 22.7%           |
|        9 | 314896 | +0.30%   | +0.57%    | +1.10%    | 30.5%           |
|       10 | 314764 | +0.25%   | +0.48%    | +0.97%    | 41.6%           |

- Top-minus-bottom decile 21d spread: **+0.18%**
- Monotone step fraction (21d): **44%** of decile steps increase

## (c) Top-50 stability

- Mean day-over-day top-50 overlap: **58.1%** over 1,371 days
- Unique names ever in top-50: **2,531**; precision at FIRST appearance:
  **49.6%** (vs daily-P@50 ≈ 50% from the WF run)

## (d) Top-50 forward returns vs universe, by year (follow-up query)

The deciles above are ~230 names/day; the actual product is the top-50. Sharper slice:

| yr | top50_5d | top50_21d | univ_5d | univ_21d | excess_21d |
|---|---|---|---|---|---|
| 2021 | +0.73% | +1.80% | +0.38% | +0.80% | **+1.01%** |
| 2022 | −0.37% | −0.61% | −0.31% | −0.56% | −0.05% |
| 2023 | +0.25% | +0.76% | +0.33% | +0.95% | −0.20% |
| 2024 | +0.14% | +1.19% | +0.33% | +1.40% | −0.21% |
| 2025 | +0.37% | +1.34% | +0.32% | +1.41% | −0.07% |
| 2026 | +0.58% | +2.26% | +0.49% | +1.74% | +0.52% |
| **all** | **+0.25%** | **+1.00%** | **+0.23%** | **+0.88%** | **+0.12%** |

## Gate read (Phase 0.1 go/no-go)

- **Go requires:** (a) coverage well above 0 with median lead > 0, AND (b) a real,
  roughly monotone top-vs-bottom forward-return spread.

### Verdict: **NO-GO** for the Job-1 trade build (E1 short-hold strategy)

- **(a) passes mechanically but is selection-biased as a return claim.** 91.7% coverage,
  median 42d lead — the head-start is real *for the event*. But the +4.16% vs +0.56% return
  comparison conditions on names that *did* subsequently enter the watchlist. The
  unconditional test is (d), and it erases the edge: the ~50% of top-50 names that never
  ignite drag the portfolio back to the universe mean.
- **(b) fails.** Ignition rate is beautifully monotone (2.2% → 41.6%, ~19× lift) — the model
  predicts the scanner event exactly as the WF metrics said. But forward returns peak at
  decile 7 and *decline* into decile 10, and the top-50 excess is **+12bps per 21d before
  costs** (negative in 4 of 6 years; the pooled positive is mostly 2021 + 2026 YTD).
- **The structural read:** M02 predicts *proximity to ignition*, and maximum proximity means
  the pre-breakout move is already spent — the score peaks exactly where the remaining
  short-horizon return is smallest. Predicting the watchlist event ≠ predicting returns;
  the circularity caveat was the right worry.
- **Exit-engineering hope (E2/E3 asymmetric exits on a ~0-mean edge) is overfit bait** —
  there is no mean to harvest; declined.

### What survives

- The model's *event*-prediction is genuine, broad (not persistent-name domination:
  unique-name precision 49.6% ≈ daily P@50), and out-of-sample stable.
- Possible residual value is **operational, not alpha**: an "about to trip the M01 scanner"
  attention list (its original §1 framing), or a candidate feature/prioritizer inside M01's
  own flow. Any such use must carry **no return claim**.
- Per the prod-gap plan gate: Phases 2–4 (prod plumbing) do **not** run on the strategy
  justification. If the ops-tool framing is wanted, that's a separate, smaller decision.
