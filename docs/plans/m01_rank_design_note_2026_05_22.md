# m01_rank — Design Note (purpose, grain, substrate)

**Created:** 2026-05-22
**Owner:** Hang
**Status:** DRAFT for approval — no pipeline changes until signed off.
**Context:** Phase 1/2 audit revealed the backtest 28× was a measurement
artifact, then traced the root blocker to the training substrate. This note
fixes intent before the t3 rebuild.

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

---

## 1. What m01_rank is (and what it is NOT)

| | **M01_prototype** (exists) | **m01_rank** (this work) |
|---|---|---|
| Grain | **Event** — 1 row per trade | **Dense** — 1 row per (ticker, trading-day) |
| Row taken on | the day the name qualifies SEPA | every day the name is in the panel |
| Question | "On qualify day, how good is this setup?" | "Right now, what's this name's conviction, and is it decaying?" |
| Target | MFE over a (random) holding period | forward continuation, recomputed each day |
| Role | **screening / entry** | **monitoring / hold-duration** |
| Decision it informs | *should I enter?* | *should I keep holding, and for how long?* |

m01_rank **complements** M01_prototype; it does not replace it. The prototype
picks the door; m01_rank watches the room. They are intentionally different
grains because they answer different questions.

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

## 8. Given the negative verdict — what to revisit (not yet decided)

The substrate and infra are sound, so the lever is the **target / horizon /
feature** combination, not the plumbing. Candidate directions, roughly ordered:

1. **Target horizon vs hold horizon mismatch.** The model predicts 20d but the
   *daily* engine (which works) harvests ~1–5d drift. Test training the target
   at a SHORTER horizon (5–10d) — maybe the real, tradeable signal is
   short-horizon continuation, and 20d is too far out.
2. **Target definition.** `>20% in 20d` is a rare, fat-tailed event (~5–8% base
   rate). A regression on forward return, or a relative (cross-sectional rank)
   target, may carry more usable signal than the binary home-run.
3. **Long-short to strip beta.** Daily Sharpe dies in 2022 because it's long-only
   momentum. A long-top-K / short-bottom-K book would test whether there is
   *relative* rank alpha once market beta is removed. If L/S survives 2022,
   m01_rank has real cross-sectional signal even if outright long does not.
4. **Accept the daily momentum result as a beta sleeve**, not alpha — only if a
   regime filter (e.g. M03) gates it off in drawdowns. Lower ambition.

Recommend testing (1) and (3) first — both are cheap notebook reruns and they
disambiguate "wrong horizon" from "no alpha, only beta."

---

## Sign-off checklist

- [x] §0 verdict: signal not durable at trained horizon (leakage-clean,
      walk-forward tested)
- [ ] §1 purpose/grain table is correct
- [ ] §2 substrate-is-already-correct finding accepted
- [ ] §8 next-direction chosen (recommend horizon retrain + long-short)
