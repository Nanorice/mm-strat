# Glossary — terms, and which names lie

> **Why this exists.** 2026-07-17: a design session conflated two different objects both
> called "cone" and built a plan on the confusion. The root cause is not carelessness —
> it's that we have **no fixed terminology and nowhere to look one up**. Several live
> names are ambiguous (`cone`), uninformative (`sepa_watchlist`), or actively false
> (`prob_elite`, `trend_c8`).
>
> **Precedent this follows:** `src/evaluation/label_registry.py` already does exactly this
> for labels — a `LabelDefinition` with description / `target_col` / `horizon_days` /
> `exit_rule` / `bins` / `git_sha` + a `fingerprint()`, so *"which label was this model
> trained against?"* is **verifiable forever**. That pattern works. This extends it from
> labels to the vocabulary.
>
> **Rule: a term here is the definition. If code and this doc disagree, one of them is a
> bug — say which.**

---

## 1 · The names that lie (audit, 2026-07-17)

Verdict key: **RENAME** (the name is false/misleading) · **DOCUMENT** (name is poor but
entrenched; pin the meaning here) · **SPLIT** (one name, two objects → needs two names).

| Name | Verdict | What's wrong | Proposed |
|---|---|---|---|
| **`cone`** | **SPLIT** | Two unrelated objects. **Label cone** = `basket_paths` buy-and-hold-to-exit fan (no rotation) — asks *is the label worth anything?* **Strategy cone** = `cone_gate` real equity across 89 start dates (slots/rotation/exits) — asks *did it earn promotion?* Rendering them as one thing is the C1/C3 confusion the banners exist to prevent | `label_cone` / `strategy_cone`. Never bare "cone" in code or a chart title |
| **`prob_elite`** | **RENAME + SPLIT** | ⚠️ **Three things under one name, chosen by a silent branch** (`universe_scorer.py:353-365`): 4-class → `proba[:,3]`; binary **without** calibrator → raw `p_pos`; binary **with** calibrator → `iso.transform(p_pos)`. **Raw XGB output is NOT a probability** — it's a score that ranks. Isotonic output approximately is. Same column, two scales (**raw median ~0.55 vs calibrated ~0.12**) → a gate of "0.15" means opposite things. **"Elite" appears in no label definition** — the labels say `mfe_homerun` / "Home Run" (MFE >30%) | `score_raw` (uncalibrated rank) vs `prob_homerun_cal` (calibrated). The dashboard already refuses to call it P(...) — see §3 |
| **`sepa_watchlist`** | **RENAME** | It is **not a watchlist**. Columns: `ticker, entry_date, exit_date, session_id, trend_ok, breakout_ok, status` — ~38.7k rows of **trade sessions**. Since 2026-07-18 it is the SINGLE session store: the 14-day cool-down gate was removed (re-triggers are kept; derive `is_retrigger` at read time via LAG when episode-dedup matters), and `screener_watchlist` became a display **VIEW** over it (company info + realized returns; delisted tickers kept). The name doesn't scope what's in it | `sepa_sessions` / `sepa_trade_sessions` |
| **`trend_c8`** | **RENAME** | Computes **C1+C2+C6** (the exit criteria), not C1–C8. Known misnomer, still live (`view_manager.py:270,281`) | `trend_exit` |
| **`score`** | **DOCUMENT** | Overloaded: `calibrated_score` (expected MFE, 3–70 scale), `m03_score` (0–100 regime), `prob_elite`, `normalized_score` (= `prob_elite*100`), `leader_score`. "The score" alone is meaningless | Always qualify. Never bare `score` in a new column |
| **`cell`** | **DOCUMENT** | A cone cell = one (start-date × horizon) backtest run. Identified today by **path** (`<arm>/<grid>/r_200301_h12`) → renaming an arm dangles references | `cell_id` = content fingerprint (below) |

---

## 2 · Core terms

### The three currencies — *what a result licenses you to claim*
| | Means | Lives |
|---|---|---|
| **C1 · label** | label-level lift (AUC, class separation). **Says nothing about money.** | model card, Model Lab |
| **C2 · OOS** | out-of-sample generalization of the model | OOS gate |
| **C3 · exit-P&L** | trade-level realized P&L through a real exit | Backtest Studio, cone gate |

**Master rule: `label lift ≠ trade edge`.** A C1 win is a **hypothesis** until it clears a
C3 cone. See `[[project_standing_epistemics]]`.

### The pipeline stages — *where a thing sits*
> **`data → model/label → strategy`**

Pages split by **stage**; the currency is a claim-strength **banner within** a page:
**Dataset EDA** = data · **Model Lab** = model/label (C1) · **Backtest Studio** = strategy (C3).

⚠️ **Stage ≠ currency.** EDA is *input inspection*, upstream of every currency — tagging it
C1/C2/C3 would imply a claim it isn't making.

### Cone (never use bare)
| Term | Engine | Exit | Asks |
|---|---|---|---|
| **`label_cone`** | `basket_paths` | fixed horizon (150d) + stop (15%), **no rotation, no TP** | is the label worth anything on the population? |
| **`strategy_cone`** | `VectorizedSEPABacktest` / BackTrader | real exits, slots, rotation | did this strategy earn promotion? |

Both are **start-DATE sweeps**, because the edge is a regime ride — a single P&L is one
draw, not the verdict (`[[project_champion_starttime_dependent]]`).

### The gate — `trend_ok ∧ breakout_ok`
```sql
trend_ok  = C1-C9 Minervini trend template (src/feature_pipeline.py:397-406):
            close > SMA150 AND close > SMA200 AND SMA150 > SMA200
            AND SMA200 > SMA200_lag20              -- 200d rising
            AND SMA50 > SMA150 AND close > SMA50
            AND close > low_52w * 1.3              -- 30% off the low
            AND close > high_52w * 0.85            -- within 15% of the high
            AND price_vs_spy > price_vs_spy_ma63   -- RS line uptrending
breakout_ok = breakout = 1 AND volume / vol_avg_50_prev > 1.3   -- volume confirmation
```
= **a genuine breakout day on a stock already in a Stage-2 uptrend.**

🛑 **The gate is a BUG FIX, not an optimization.** The score cache scores *every*
trend-active row, so an ungated `nlargest(prob_elite)` draws from an inflated pool of
**off-setup days** — the **population-inflation bug**: it picks names on days the strategy
would never have traded. Measured: **8,934,524 → 122,359 rows (1.37%)**. So a study's
population is part of its identity — **the same scores under a different gate are a
different study.**

### Labels — the registry is the source of truth
`label_registry/*.json` + a copy in each model's artifact dir. **No label defines "elite".**

| label_id | target | Definition |
|---|---|---|
| `mfe_binary_homerun_v1` | `mfe_homerun` | 1 if MFE >30% over the **SEPA holding period** (entry → C1∨C2∨C6 exit; open trades capped at entry+120d). Base rate ~14.5% |
| `mfe_4class_v1` | `mfe_class` | Noise (0-2] / Moderate (2-10] / Strong (10-30] / **Home Run (>30)** |
| `m01a_tail_v1` | `tail_mag_63` | `max(MFE_63 − 30%, 0)`, **fixed** 63-bar horizon (a different clock from the SEPA exit) |

⚠️ **Two clocks**: the fixed horizon **RANKS**; the SEPA event-terminated exit **HOLDS**.
Don't mix them.

### `cell_id` — content fingerprint, not a path
`sha256` of a cell's canonical config (params + start + horizon + `score_scale` + input
hash), following `label_registry.fingerprint()`. Identical configs → identical id, so **a
re-run is provably a reproduction**; survives engine edits that don't change the config,
and an arm rename doesn't orphan history.

---

## 3 · Display rules (already enforced — don't regress)

- **Never label a raw score "P(...)"**. `scripts/pages/3_Screening.py` and `4_Portfolio.py`
  render **"Score (raw)"**: 0.79 is *a strong RANK*, not "a 79% chance". The **display is
  honest; the column name is the liar** — which is why `prob_elite` is a RENAME above.
- A held name outside the scored universe renders **"—"**, never a stale score or a zero
  (a zero reads as "the model hates it"). Model scores ~751 of ~3,980 active tickers.
- **Median is the misleading lens; the tail is the signal** — a median-first chart
  contradicts the sprint's own conclusion.

## 4 · How to add a term

One row in §2, and if the name is bad, a verdict row in §1. Keep it terse. **State what a
term is NOT** — every entry above exists because something was silently two things.
