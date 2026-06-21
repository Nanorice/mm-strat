# m01_rank — Design Note (purpose, grain, substrate)

**Created:** 2026-05-22
**Owner:** Hang
**Status:** DRAFT for approval — no pipeline changes until signed off.
**Context:** Phase 1/2 audit revealed the backtest 28× was a measurement
artifact, then traced the root blocker to the training substrate. This note
fixes intent before the t3 rebuild.

---

## HIGH-LEVEL GOAL (anchor — do not deviate)

We are refining a two-model trading system. **m01_prototype** is the prod
**selection** model; **m01_rank** is the **timing/execution** model we are now
building to sit on top of it.

- **m01_prototype (prod, event-grain) answers:** *"Today this ticker — already in
  a SEPA uptrend — has a breakout and qualifies for SEPA. Given the information
  available on the breakout day, will this trade achieve good MFE before the
  trend breaks?"* It works well: a high home-run probability reliably precedes a
  good trade. It is a good SELECTION signal.
- **The gap m01_prototype leaves:** it is trained ONLY on breakout-day rows, so
  it cannot manage the trade once selected. After a breakout, a name typically
  **pulls back for a few days** before continuing — so even when we are confident
  the trade is good, we still need to know *when to enter, whether to hold,
  whether to rebalance, when to exit*.
- **m01_rank (dense-grain) answers those TIMING questions** by evaluating the
  setup **every day** through the life of the trade — conditional on
  m01_prototype already having flagged the name as a good trade.

**Key reframe (2026-05-22):** m01_rank is a **timing/execution layer on top of
m01_prototype's selection**, NOT a standalone return predictor. The Phase 2
verdict below tested it as its own top-K return strategy — which may have been
the wrong test for its actual mandate (see §0 caveat and §8).

**Open verification debt:** m01_prototype's own backtest "should be on dense data
and performance is OK" — but this has NOT been double-checked. Confirm
m01_prototype's dense-data backtest before leaning further on it as the selection
layer.

---

## 0. VERDICT (2026-05-22) — signal is NOT durable at its trained horizon

After removing every measurement artifact (gappy-panel `shift`, NULL `adj_close`,
split outliers, bad tickers), the walk-forward backtest (Cell E) gives the
honest answer:

| year | daily-rebal Sharpe | 20d-hold median | 20d win-rate |
|------|--------------------|-----------------|--------------|
| 2020 | 1.38 | −1.0% | 47% |
| 2021 | 0.62 | −1.5% | 47% |
| **2022** | **0.10** | +0.1% | 50% |
| 2023 | 2.15 | −0.2% | 49% |
| 2024 | 1.16 | −1.0% | 44% |

**Two engines, two conclusions, and the disagreement IS the finding:**
- **Daily rebalance** is positive on average (mean Sharpe 1.08) but **≈0 in the
  2022 drawdown** → this is long-only **momentum beta**, not alpha. The 2023
  Sharpe 2.15 that looked exciting was the best year, not a typical one.
- **20d non-overlapping hold** — the model's *native* trained horizon — has
  **negative median trade return and <50% win-rate in 4 of 5 years.** Holding
  the top-K for the 20 days the model predicts loses money.

**Conclusion:** the `y_homerun` (>20% in 20d) classifier does NOT produce a
tradeable forward edge at the horizon it was trained on. The only positive result
(daily rebalance) is regime-dependent momentum that dies in 2022, and it is
*not* harvesting the model's 20d prediction — it's harvesting short-horizon drift
that correlates with high `prob` in up-markets.

**This is leakage-clean and durability-tested — a trustworthy negative.** It does
NOT mean m01_rank is unbuildable; it means the current target/feature combination
does not yield 20d alpha. See §8 for what to revisit.

**CAVEAT — the test may not match the mandate (see HIGH-LEVEL GOAL).** This
backtest evaluated m01_rank as a *standalone selection* strategy (rank ALL names,
trade the top-K). But m01_rank's actual job is **timing/execution on names
m01_prototype already selected** — the universe should be m01_prototype's
home-run candidates, and the question is entry/exit *timing within those trades*,
not which names to pick. A standalone-rank negative does not refute the timing
mandate; it just says m01_rank is not itself a stock-picker. The right next test
conditions on m01_prototype's selection (§8).

---

## 1. What m01_rank is (and what it is NOT)

| | **m01_prototype** (prod) | **m01_rank** (this work) |
|---|---|---|
| Grain | **Event** — 1 row per breakout day | **Dense** — 1 row per (ticker, trading-day) |
| Row taken on | the breakout day (qualifies SEPA) | every day the trade is live |
| Question | "Given breakout-day info, will this trade reach good MFE before trend break?" | "Given this is a good trade, is TODAY a good day to enter / hold / rebalance / exit?" |
| Target | MFE before trend break | timing of entry/exit within the trade life |
| Role | **SELECTION** (which names) | **TIMING / EXECUTION** (when to act on a selected name) |
| Decision it informs | *is this a good trade?* | *when do I enter it, and when do I get out?* |
| Status | works well (high prob → good trade); dense backtest unverified | under construction; standalone-return test was negative (§0) |

m01_rank **complements** m01_prototype — it does NOT replace it and is NOT meant
to pick names on its own. m01_prototype says *which* door; m01_rank says *when to
walk through it and when to leave*. The breakout-day pullback is the canonical
case: m01_prototype flags the name, m01_rank's job is to wait out the pullback and
time the entry, then signal the exit before the trend breaks.

## 2. Substrate status — RESOLVED 2026-05-22: t3 is already correct

**Earlier drafts of this note claimed t3 was "gappy / a patchwork of stale
rows." That was a MEASUREMENT ERROR and is retracted.** The mistake: comparing
each ticker's t3 rows against *all* price_data days in its span. t3 is dense over
the **screener-active universe** (the T3 uplift, see
`docs/plans/completed/t3_table_uplift_plan.md`), NOT over all trading days. A
ticker correctly has no t3 row while it is screener-inactive (failed criteria
for ≥126 days, the grace period). Counting those legitimate exclusions as "gaps"
produced the false 192-gappy-tickers finding.

Verified state of t3 (2026-05-22):
- Uplift columns `trend_ok` / `breakout_ok` present. ✅
- Dense across full history: 655 rows/day (2001) → ~2,400/day (2025), tracking
  universe growth — never the old ~70/day sparse design. ✅
- Membership-aligned: e.g. 2024-03-08 has 2,267 t3 rows vs 2,433 screener-active
  (= `screener_active ∩ has_t2_row`, the uplift §1b Option A design). ✅
- t2 itself is 99.9% complete within active-membership spans (4,311 missing of
  4.5M) — the screener_membership gate is an event log with a 126-day grace
  period, NOT a per-day liquidity filter, so it does not create gaps. ✅

**No t2 recompute and no t3 rebuild are needed.** The substrate m01_rank requires
already exists.

## 3. The ONE real (and tiny) gap — handled on the P&L side, not the panel

t3 is dense *while a ticker is active*, but a ticker can legitimately fall out of
the active universe and return, leaving a real multi-week/month hole in its t3
row sequence. Magnitude within the m01_rank window (≥2018): of 4.5M consecutive
t3 row-pairs, **99.957% are trading-day-adjacent; only 0.043% (1,944 pairs) jump
>1 week.** Small, but non-zero.

**Consequence:** `df.groupby("ticker")["close"].shift(-1)` on t3 is unsafe — on
those 1,944 pairs it books a multi-month move as a single "1-day" return (the
mechanism behind the Phase 2 vertical NAV jumps). This is NOT a substrate defect
to rebuild away; it is correct data that the *consumer* must handle.

**Fix (already in the Phase 2 artifact):** source next-day returns from
`price_data.adj_close` with an adjacency guard (≤5 calendar days); a held name
spanning an active-universe hole earns 0 that day rather than a stale jump.
`price_data` is genuinely continuous (356 gaps >7d, max 219d = real halts).

## 4. Target construction for m01_rank (dense)

Recomputed per (ticker, day) from the continuous panel — NOT from `mfe_pct`:

```
y_homerun(t) = ( adj_close(t + H) / adj_close(t) - 1 ) > THRESH
```
with `H = 20` trading days, `THRESH = 0.20` (locked in the notebook G0
sensitivity sweep). Forward window uses **adj_close** sourced from `price_data`
(not t3 `shift()`) so splits/dividends don't masquerade as returns and the +H
lookup lands on a real trading day across any active-universe hole (§3).

Last `H` rows per ticker have no label (no future) → dropped, as today.

## 5. Substrate wiring (no rebuild — uses existing tables)

- **Train / score:** `load_pretrain_data(mode="dense")` → `t3_sepa_features`
  (already dense over the active universe). No view/table change needed.
- **Backtest daily P&L:** next-day return from **price_data.adj_close** with an
  adjacency guard (≤5 calendar days), per Phase 2 Cell A — handles the §3 holes.
- **Event-grain views unaffected:** `v_d1_candidates` Step-4 entry-row keep and
  `v_d2_training` stay event-grain — they serve M01_prototype, not m01_rank.

## 6. Status: no substrate work needed

All four "rebuild" open questions from the prior draft are MOOT — t3 is already
the correct dense panel (§2). The only real issue (§3 active-universe holes) is
handled by the price_data-sourced P&L already drafted in the Phase 2 artifact.

**Remaining work is purely on the m01_rank notebook backtest, not the data:**
1. Re-point Phase 2 Cell A at `price_data.adj_close` (done in artifact).
2. Re-run Phase 2 Cells B/C against the corrected return source.
3. Confirm the NAV curve is continuous and total return is plausible
   (single-digit-x), per the artifact's sanity bounds.

## 7. Out of scope (reaffirmed)

- Do NOT rebuild t3 or recompute t2 — both are correct as-is.
- Do NOT change `v_d1_candidates` / `v_d2_training` grain — they serve the
  event-grain prototype.
- Do NOT retrain M01_prototype.
- Notebook edits remain artifact-only (paste manually).

## 8. Next directions (reframed around the timing mandate)

The substrate and infra are sound. Per the HIGH-LEVEL GOAL, m01_rank is a TIMING
layer on m01_prototype's selection — so the FIRST test must match that mandate,
not the standalone-rank test that produced §0.

**0. (NEW — do first) Condition on m01_prototype's selection.** Restrict the
   universe to names m01_prototype flagged as home-run candidates, then ask:
   does m01_rank's daily score time the entry/exit *within those trades* better
   than naive "enter on breakout day, hold fixed"? Metric: MFE captured / drawdown
   avoided vs the naive baseline — NOT top-K portfolio Sharpe. This directly tests
   the breakout-pullback timing use case. If m01_rank improves entry timing here,
   it succeeds at its real job even though §0 (standalone picker) was negative.

Then, if a standalone signal is still wanted, the levers are target/horizon:

1. **Shorter target horizon (5–10d).** The daily engine that "worked" harvested
   ~1–5d drift; the 20d target may be too far out for a timing model. Cheap rerun.
2. **Target definition.** `>20% in 20d` is rare/fat-tailed (~5–8% base). A
   forward-return regression or cross-sectional-rank target may carry more signal.
3. **Long-short to strip beta.** Daily Sharpe dies in 2022 because it's long-only
   momentum. Long-top-K / short-bottom-K tests for *relative* rank alpha; if L/S
   survives 2022 there is cross-sectional signal even if outright-long lacks it.
4. **Daily momentum as a beta sleeve**, gated off in drawdowns by a regime filter
   (M03). Lower ambition; only if 0–3 don't yield alpha.

**Recommend (0) first** — it is the test that matches what m01_rank is FOR. (1)
and (3) follow if a standalone signal is still desired. Separately, **verify
m01_prototype's own dense-data backtest** (open debt noted in HIGH-LEVEL GOAL)
before relying on it as the selection layer for test (0).

---

## Sign-off checklist

- [x] §0 verdict: signal not durable at trained horizon (leakage-clean,
      walk-forward tested)
- [ ] §1 purpose/grain table is correct
- [ ] §2 substrate-is-already-correct finding accepted
- [ ] §8 next-direction chosen (recommend horizon retrain + long-short)
