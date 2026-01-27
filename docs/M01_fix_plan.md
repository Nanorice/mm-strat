# Framework to evaluate M01 target variants (a–d)

You’re comparing **different target definitions**, so you want an evaluation that measures:
1.  **ranking quality** (can it surface the best run-ups?),
2.  **robustness/stability** (does it generalize across time/regimes?), and
3.  **whether it degenerates into a volatility detector** (your concern).

---

### Step 0 — Lock down what “truth” is for evaluation
For each SEPA event/trade ($i$), compute a consistent realized "potential" target on daily closes:

* **MFE definition (close-to-close run-up):** $MFE_i = \max_{t \in [0, \tau_i]} \left( \frac{P_{i,t}}{P_{i,0}} - 1 \right)$ (MFE definition reference [Investopedia].)
* **ATR at entry** (for normalization variants) [Investopedia ATR].

**Then generate target variants:**
* **(a)** $y = \mathrm{MFE}$
* **(b)** $y = \log(1 + \mathrm{MFE})$
* **(c)** $y = \mathrm{MFE} / \mathrm{ATR}_{\text{entry}}$
* **(d)** with/without deleting losers (I'd treat deletion as an ablation, but evaluate on the *full* universe of events either way)

---

### Step 1 — Use a walk-forward evaluation design (non-negotiable)
Use **time-ordered splits** (walk-forward). If your events have multi-week/month horizons, also ensure labels don’t leak across the split boundary (purging/embargo logic per López de Prado is commonly implemented; overview: [mlfinlab PurgedKFold]). For basic time splits, scikit's `TimeSeriesSplit` is a starting point [TimeSeriesSplit].

**Output of each fold:** out-of-sample predictions ($\hat{y}$) for that fold only. Concatenate folds to get a fully OOS prediction series.

---

### Step 2 — Evaluate what you actually do: ranking, not point accuracy
Because your downstream use is "pick best tickers", prioritize **rank and tail-capture** metrics over RMSE.

#### A) Primary metrics (ranking / tail capture)
Compute these per fold, then aggregate (mean/median across folds):

1.  **Information Coefficient (IC)**
    Spearman rank correlation between $\hat{y}$ and realized $y$:
    * $IC_{\text{Spearman}}$ is typically more relevant than $R^2$ for ranking.
2.  **Top-(k) / top-quantile enrichment** For $q \in \{1\%, 5\%, 10\%\}$:
    * **Mean realized target among selected:** $\mathbb{E}[y \mid \hat{y} \in \text{top } q]$
    * **Lift:** $Lift_q = \frac{\mathbb{E}[y \mid \hat{y} \in \text{top } q]}{\mathbb{E}[y]}$
3.  **Super-winner capture rate (threshold-free via percentiles)**
    Define "super winner" in each fold as top $q\%$ by realized MFE (or by realized $y$ for that variant). Then compute:
    * **Precision@q:** fraction of names you selected that are truly in top $q\%$
    * **Recall@q:** fraction of true top $q\%$ you captured
    * *This avoids hardcoding 50%/100% thresholds.*

#### B) Secondary metrics (only to diagnose)
* **MAE / RMSE on transformed scale** (especially for (b)): useful to detect gross misfit.
* If you later use quantile regression, track **pinball loss** (quantile loss).

---

### Step 3 — Explicitly test “volatility detector” risk
This is where (c) and (b) often help. Run these diagnostics out-of-sample:

1.  **Correlation of predictions with volatility**
    * Compute Spearman correlation: $\rho(\hat{y}, \mathrm{ATR}_{\text{entry}})$. If this is high, your M01 is strongly driven by volatility.
2.  **Within-volatility bucket IC**
    * Bucket events into ATR deciles.
    * Compute IC inside each decile. A good "upside potential" model should still rank within similar volatility.
3.  **Selection concentration**
    * What fraction of top-$q$ picks fall into the highest ATR decile? If your top picks cluster in high ATR, that's usually the "volatility detector" failure mode.

> **Answer to your question:** yes—**ATR-normalized run-up (c)** is *one* of the most direct ways to reduce "volatility detector" behavior, because it changes the target from absolute run-up to run-up per unit risk. It won't eliminate the risk entirely (features can still proxy volatility), but it usually reduces it measurably via the tests above.

---

### Step 4 — Statistical tests: “is variant A really better than B?”
Because everything is time-dependent and you're comparing many variants, rely on **resampling and out-of-sample fold distributions**, not single-number in-sample wins.

**Recommended toolkit:**
1.  **Block bootstrap confidence intervals** on fold metrics. Bootstrap folds (or time blocks) to get CIs for IC and $Lift_q$. This avoids naive i.i.d. assumptions.
2.  **Permutation test for IC:** Within each fold, shuffle targets across events (optionally within time buckets), recompute IC to build a null distribution. Your observed IC should sit far in the tail.
3.  **Diebold-Mariano test (optional):** If you frame each day (or period) as a forecast loss series, you can compare predictive accuracy via Diebold-Mariano [Diebold-Mariano 1995 PDF].
4.  **Multiple testing / selection penalty:** If you try many targets, features, and models, adjust expectations. The *Deflated Sharpe Ratio* paper is a standard reference on selection bias in backtests [Bailey et al. SSRN].

---

### Step 5 — Application integration: calibration and how to use the score

#### A) Calibrating M01 (regression-style calibration)
Even if M01 predicts "max run-up", you can still calibrate it so outputs correspond to empirical outcomes:
1.  Collect **fully OOS** predictions $\hat{y}$.
2.  Bin $\hat{y}$ into deciles.
3.  For each bin, compute realized mean/median of the true target.
4.  Fit a **monotonic mapping** $g(\hat{y})$ using isotonic regression [`scikit IsotonicRegression`].
5.  Use $g(\hat{y})$ in production as your "calibrated potential".

#### B) If you add M03, calibration becomes standard probability calibration
M03 outputs probabilities; you can validate with:
* **Brier score** [`scikit brier_score_loss`]
* **Calibration curves** and post-hoc calibration methods [`scikit calibration`]
* Platt scaling background [Platt 1999]



#### C) How M01 variants connect to M02 in practice
A robust "screening" integration (no exit assumptions) is:
* Rank by calibrated M01 potential $g(\hat{y})$
* Filter by M02 calibrated probability (or require $p$ above a threshold)
* Monitor whether the selected set’s realized outcomes match the calibration tables

---

## Practical “scorecard” to compare (a)–(d)
For each variant, fill this table (per fold, then aggregate):

| Category | Metric | What “good” looks like |
| :--- | :--- | :--- |
| **Ranking** | Spearman IC | Positive, stable across folds |
| **Tail capture** | $Lift\{5\%\}, Lift\{1\%\}$ | High and consistent |
| **Super winners** | $Precision@top(q\%)$ | High without collapsing recall |
| **Stability** | IC by year/regime | No single-regime dependency |
| **Vol detector check** | $\rho(\hat{y}, \mathrm{ATR})$ | Lower is better |
| **Vol robustness** | IC within ATR deciles | Still positive inside buckets |
| **Calibration** | Decile plot monotonicity | Increasing realized with predicted |

---

## Recommendation on your listed targets
* **(a) Raw MFE:** good as a "potential" label, but expect instability and volatility favoritism; only keep if it wins scorecard *and* doesn't correlate too strongly with ATR.
* **(b)** $\log(1 + \mathrm{MFE})$: often a strong default for heavy tails [Cont 2001]; tends to improve stability.
* **(c)** $\mathrm{MFE} / \mathrm{ATR}_{\text{entry}}$: yes, this is a direct way to push M01 toward "upside without being a volatility detector".
* **(d) Loser deletion:** evaluate as an ablation, but expect poorer real-world behavior; it usually inflates apparent upside and breaks calibration when deployed.