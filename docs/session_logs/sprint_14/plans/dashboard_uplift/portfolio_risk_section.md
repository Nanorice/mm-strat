# Portfolio — Risk Management section

> Sprint 14. Planned 2026-07-16, **SHIPPED 2026-07-17** (`_render_risk` in
> `scripts/pages/4_Portfolio.py` + `dashboard_utils.load_portfolio_risk`).
> Status: the four metric groups below are live; the "out of scope" list still binds.

## Two user decisions that shape this section (2026-07-17)

1. **Entries/exits are DISCRETIONARY.** The champion strategy is only there to set
   *expectation* — the user's words: *"it is a lottery"*. So this section does NOT
   measure divergence from the champion's rules; it monitors the user's own book.
   Corollary: **holdings routinely sit outside the SEPA screen**, so every metric
   must resolve from `price_data` (all tickers) rather than t2/t3 (~2.4k of ~4.0k).
2. **The section is to MEASURE AND MONITOR, position-specific.** Not to act.

## Why no VaR / expected shortfall

The user asked whether it's an infra gap. It isn't — a historical VaR off
`price_data` is ~10 lines. It's excluded because **it would mislead**:
- It needs a covariance matrix to mean anything at book level. With ~4 concentrated
  same-sector names the correlation term dominates; a naive VaR ignoring it
  understates risk exactly when it matters.
- Returns here are fat-tailed and regime-dependent (our own cone work) — a
  window-fitted VaR prints a calm number right up to the regime that breaks it.
- It's a single number that invites *acting*, and every acting overlay we cone-tested
  lost (below).

---

## The governing constraint (read this before proposing anything)

**Our own research has already falsified the obvious risk levers on the start-date
cone.** Any risk section must not resurrect them:

| Lever | Verdict | Evidence |
|---|---|---|
| **DD circuit breaker** (halt after book drawdown) | ❌ **REJECTED** | Sharpe median −0.04 vs champion 0.76; **lowers the floor it was built to lift** (−2.82 vs −1.93). Threshold sweep 6/10/15/20/30% proves it's **mechanism, not tuning** — floor worse at EVERY level. `[[project_overlay_brakes_rejected]]` |
| **Earnings blackout** (force-exit before prints) | ❌ **REJECTED** | Worse than the breaker. Force-exits 23.6% of the book, **77% of them winners**. Costs return AND drawdown. |
| **VIX-based de-risking** ("cut when VIX high") | ❌ **BACKWARDS** | corr +0.03; VIX>30 days are the **BEST** (+4.5%, crash-rebound). `[[project_capital_deployment]]` |
| **Raising the score gate** for safety | ⚠️ **variance knob** | Buys floor/%neg but **LOSES median-Sharpe**. Not free. `[[project_prob_elite_gate_variance_knob]]` |
| **Widening the basket** to diversify | ❌ **dilutes** | top-5 → top-10 same-day adds no winners (sharp cliff at 5). |
| **SPY > 200d deploy gate** | ✅ **THE ONE THAT WORKS** | BackTrader-confirmed: Sharpe 0.52→0.79, maxDD −61%→−37%. **The only distribution-shifting lever we have.** |

**The through-line: four separate attempts to buy consistency by clipping the tail
all LOST.** The tail is where the edge lives. So this section's job is **to inform,
not to automate** — surface the exposures, let the human decide. It must not become
a brake we already know loses money.

Second constraint: **the book is a real, hand-entered portfolio** — it is NOT the
backtest's 5-slot champion. Backtest verdicts about *the strategy* don't
automatically bind *this book*, but they're the best prior we have, and a panel
that contradicts them needs to say why.

---

## SHIPPED (2026-07-17) — `_render_risk`, one row per position + book totals

| Metric | Source | Coverage |
|---|---|---|
| **ATR(14), ATR %** | `price_data` (Wilder TR, computed in the loader) | **every holding** |
| **Realized vol 20d / 60d** (annualised) | `price_data` | **every holding** |
| **20d/50d support & resistance** | `price_data` | **every holding** |
| **Distance to S/R in ATR UNITS** | derived | **every holding** |
| **1-ATR move as % of NAV** (`qty × ATR / NAV`) | derived | **every holding** |
| **True 52w high/low** | `t3_sepa_features` (**read**, precomputed) | ~68% — "—" off-screen |
| **Beta** (book beta = mv-weighted) | `company_profiles.beta` (4,085 non-null) | most |
| **Top-3 / sector share** | positions ⋈ profiles | all |

Design notes worth keeping:
- **ATR is computed in the loader, not read from t3's `atr_20d`** — so the window is
  identical for every holding, including off-screen names t3 has never seen.
- **A true 52w level CANNOT be recomputed on the remote**: the slim DB windows
  `price_data` to ~172 bars (~8 months). t3's `high_52w` is a *stored* value, so it
  survives the window — read it, never recompute it. Off-screen names show "—".
- **Distances are quoted in ATR units** because dollars aren't comparable across
  names. "1.2 ATR to support" means something; "$4.20" doesn't.
- **`1-ATR / NAV` is the payoff metric**: it converts per-name noise into book impact.
  Live example — PSNL (7.9% ATR) contributes MORE book risk than NVDA despite a much
  smaller dollar position. That's invisible on a positions table.
- ATR uses `GREATEST/LEAST(close)` to bound the known `price_data` OHLC dirt.
- 🧪 The ATR test was **mutation-checked and the first version was worthless**: a
  constant true range makes EVERY window average the same, so it passed with a
  5-bar window. Now the TR varies per bar (ATR(14)=7.5 vs 5-bar=3.0) and the
  mutation fails it. Same lesson as the session-04 bot-block test.

## Original proposal (kept for the reasoning)

### 1 · Concentration — the risk our research says is real
Thread J's conclusion: *"the residual constraint is REGIME CONCENTRATION"* — extra
names are **regime-correlated exposure, not diversification** (n=10 slots: median
Sharpe ≈ flat, but p25 −0.29). So concentration is the thing worth staring at.

- Top-3 / top-5 share of NLV *(already shipped)*.
- **Sector share** — a 69%-one-sector book is the real risk, not name count.
- ⚠️ **Do NOT ship an HHI "style score" like the mock's 5.8/10 "Balanced".** That's
  an invented composite; we'd be manufacturing a number we can't defend.

### 2 · Model-opinion drift on holdings — uniquely ours, nobody else has it
The score/cohort columns are shipped. The *risk* read on top:

- **Count of holdings whose cohort has gone `removed`** — the model's universe
  dropped them. This is a genuine, ex-ante, non-falsified signal.
- **Score decay**: today's score vs the score at entry, per holding.
- ⚠️ Honest framing: label-lift ≠ trade-edge. A falling score is **a prompt to
  look**, not an exit rule. We have **no evidence** that exiting on score decay
  makes money — and four rejected overlays say tail-clipping usually loses.
  `[[project_standing_epistemics]]`

### 3 · Deploy-regime banner — reuse, don't rebuild
SPY>200d is the **only** lever that survived BackTrader. It already exists as
`weather_gauge` (Phase 7.45) + `macro_sizer.spy_above_200d()`.

- One line: *"SPY above/below 200d — deploy / stand aside"*, read from the
  existing table. **Reuse, don't recompute.**
- Chop-days run **−2.0 annualized Sharpe vs +1.15 on bull-days**; all the loss
  lives below the 200d. That's the one macro fact worth a permanent banner.

### 4 · Position-level exposure facts (no verdict attached)
- % NLV per name *(shipped)*, cash %, largest position.
- **Beta** — `company_profiles.beta` is populated (4,085 non-null). Book beta =
  Σ(w × beta). Cheap, real, and only a description of exposure.
- ⚠️ **Not a "risk score".** Beta is a number, not a recommendation.

---

## Explicitly OUT of scope (and why)

- **Stop-loss suggestions / auto-exits** — the champion's exit is a native tranche
  trail, validated on BackTrader. A dashboard second-guessing it with a different
  rule is a strictly worse, unvalidated overlay. `[[project_overlay_brakes_rejected]]`
- **A DD circuit breaker in any form** — see the sweep. Don't re-propose.
- **VaR / vol-target / Kelly sizing** — needs a covariance estimate we don't have,
  and vol-targeting is a tail-clipper by construction (the thing that lost 4×).
- **Margin / leverage / options greeks** — no data, no tables, and the book is cash
  long-only.
- **A composite "risk score"** — the mock's 5.8/10. We'd be inventing it.

---

## Open questions — RESOLVED 2026-07-17

1. ~~Track the champion or discretionary?~~ → **Discretionary.** The champion is for
   expectation only ("it is a lottery"). No divergence-from-champion panel.
2. ~~Alert or observe?~~ → **Observe.** Description only; the section never says SELL.
3. **Benchmark (SPY-relative)?** — still open. TWR is truthful now so it's *possible*.
   Not built.

## Still NOT built (deliberate)

- **`removed`-cohort count + score-decay column** — the cohort IS shown per position;
  the *decay* read (today's score vs score-at-entry) is not. Needs a score-at-entry
  snapshot, and the framing must stay "a prompt to look", never an exit rule.
- **SPY-200d banner** — reuse `weather_gauge` (Phase 7.45), don't recompute. The one
  macro fact that survived BackTrader; chop-days run −2.0 annualized Sharpe vs
  bull-days +1.15.
- **Benchmark-relative return** (Q3 above).
