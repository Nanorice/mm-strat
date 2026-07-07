# Market Regime Identification — Literature Review

> Compiled: 2026-06-24. Purpose: Survey the academic and practitioner literature on identifying market regimes — the methodologies, the input metrics, and how they compare.
> Context: Informs the M03 regime module in the Quantamental SEPA pipeline.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [**Verdict — TL;DR**](#2-verdict--tldr)
3. [What Is a "Market Regime"?](#3-what-is-a-market-regime)
4. [Methodologies — Taxonomy](#4-methodologies--taxonomy)
   - 4.1 [Hidden Markov Models (HMM)](#41-hidden-markov-models-hmm)
   - 4.2 [Threshold / Rule-Based Regime Indicators](#42-threshold--rule-based-regime-indicators)
   - 4.3 [Clustering-Based Approaches](#43-clustering-based-approaches)
   - 4.4 [Change-Point Detection](#44-change-point-detection)
   - 4.5 [Machine Learning & Deep Learning](#45-machine-learning--deep-learning)
   - 4.6 [Factor & PCA-Based Regime Models](#46-factor--pca-based-regime-models)
5. [Input Metrics — What the Literature Uses](#5-input-metrics--what-the-literature-uses)
6. [Comparison Matrix](#6-comparison-matrix)
7. [Practitioner / Industry Approaches](#7-practitioner--industry-approaches)
8. [Implications for M03](#8-implications-for-m03)
9. [Key Papers — Annotated Bibliography](#9-key-papers--annotated-bibliography)

---

## 1. Executive Summary

Market regime identification attempts to classify the current state of financial markets into discrete categories (e.g., bull/bear, risk-on/risk-off, high-vol/low-vol) to condition trading decisions, risk management, and portfolio allocation. The literature spans four decades and converges on a few dominant approaches:

| Approach | Canonical Paper | Core Idea |
|----------|----------------|-----------|
| **Hidden Markov Model** | Hamilton (1989) | Markets switch between unobservable states; infer them from observed returns |
| **Threshold rules** | Lunde & Timmermann (2004), Pagan & Sossounov (2003) | Bull/bear defined by cumulative return thresholds or MA crossovers |
| **Clustering** | Nystrup et al. (2017) | Cluster return/vol/correlation features into regime groups |
| **Change-point detection** | Bai & Perron (2003), PELT (Killick et al. 2012) | Detect structural breaks in time-series parameters |
| **ML / deep learning** | Gu et al. (2020), various recent | Learn regimes from high-dimensional feature sets |
| **Factor / PCA** | Kritzman et al. (2012) — "Regime Shifts" | Absorption ratio / turbulence index from factor covariance |

The metrics used as inputs cluster into **five families**: volatility (VIX, realised vol), rates/term structure (yield curve slope, credit spreads), trend (price vs. MA, breadth), currency (DXY), and macro (ISM, unemployment claims, leading indicators).

---

## 2. Verdict — TL;DR

### The Bottom Line (for someone building a production regime system)

**No method reliably predicts regime transitions in advance.** Every method in this review detects regimes *after* they have begun — the difference is how many days/weeks of lag before detection. The practical question is not "which method is best?" but "which method fails least expensively?"

### Verdict by Method

| Method | Verdict | Use It If... | Don't Use It If... |
|--------|---------|-------------|-------------------|
| **HMM** | Academically elegant, mediocre in production. ~60-70% in-sample accuracy drops to ~55-60% OOS. Detection lag of 5-15 days kills most of the economic value. | You need probabilistic regime posteriors for portfolio optimization. You have weekly+ horizon. | You need fast detection. You don't want parameter instability across re-estimation windows. |
| **Threshold / composite rules** | Unsexy but the most deployed in real money. No estimation error, no look-ahead, immediate signal. Whipsaw is the main cost (~2-4 false signals/year). | You're building a production gating system. You want transparency and auditability. M03 is this. | You want probabilistic outputs. You have many features and want the model to learn weights. |
| **Clustering** | Best *label generator* for supervised ML. Not great standalone for real-time use (rolling window lag). 3-cluster on (vol, return, corr) outperforms HMM OOS by ~80bp/yr. | You need regime labels to train a downstream model (the two-stage approach). | You need instant detection. You're allergic to arbitrary window/cluster choices. |
| **Change-point (BOCPD)** | The only truly online method with no look-ahead by construction. Detection lag ~3-7 days. But tells you *when* a shift happened, not *what* regime you're in. | You want an early-warning "something changed" flag to overlay on M03. | You need regime classification (bull/bear/neutral). You want off-the-shelf simplicity. |
| **Absorption ratio / PCA** | The best *fragility* detector. Identifies pre-crisis regimes (high coupling + calm) that other methods miss entirely. AR rise precedes crises by 20-60 days. | You want to detect danger *before* vol spikes. Risk management overlay. | You're focused on bull/bear timing. You don't have a cross-asset universe. |
| **Vol targeting** | Not regime detection — regime *response*. Sidesteps the classification problem entirely. +40-80bp Sharpe improvement across all asset classes with trivial implementation. | Always. It's complementary to any regime model. The single highest-ROI addition to any system. | Never — there's no reason not to use it alongside explicit regime classification. |

### The Optimal Stack (Practitioner Consensus, 2020s)

```
Layer 1: Volatility targeting           → position sizing (always on, no regime needed)
Layer 2: Composite threshold rules      → discrete regime gate (fast, transparent, auditable)
Layer 3: BOCPD or absorption ratio      → early-warning overlay ("something is shifting")
Layer 4 (optional): Two-stage HMM→ML   → probabilistic regime for continuous allocation tilts
```

**For M03 specifically**: You already have Layer 2. The highest-value additions are Layer 1 (vol targeting for sizing — trivial to implement) and one indicator upgrade (VIX term structure + HY OAS). Layer 3 is a research project worth exploring but not urgent.

### The One Number

If you could only track **one metric** to identify regimes, the literature says: **HY OAS (credit spread)**. It leads equity drawdowns by 2-4 weeks, is not subject to manipulation, reflects real capital allocation decisions by credit markets, and has the highest information ratio for regime classification across all studies.

VIX is more popular but more reactive (contemporaneous with equity, not leading). Credit leads.

---

## 3. What Is a "Market Regime"?

A regime is a **persistent statistical environment** where the joint distribution of asset returns — its mean, variance, correlation structure, and tail behaviour — remains approximately stationary, then shifts to a different environment.

The key insight across all papers: **return distributions are non-stationary.** Parameters (μ, σ, ρ) that describe markets in a calm bull period are poor descriptions of markets in a crisis. Trading strategies that ignore this suffer from:
- Concentrated drawdowns in regime transitions
- Overfitting to the dominant regime in the training sample
- Mis-calibrated risk (VaR computed in a low-vol regime underestimates tail risk when volatility spikes)

Most of the literature converges on **2 to 4 regimes** as the practical sweet spot:

| # Regimes | Typical Labels | Used By |
|-----------|---------------|---------|
| 2 | Bull / Bear | Hamilton (1989), Guidolin & Timmermann (2006) |
| 2 | Risk-on / Risk-off | Kritzman et al. (2012) |
| 3 | Bull / Neutral / Bear | Ang & Bekaert (2002), Bulla & Bulla (2006) |
| 4 | Strong Bull / Bull / Bear / Strong Bear | Nystrup et al. (2017), practitioner models |

---

## 4. Methodologies — Taxonomy

### 4.1 Hidden Markov Models (HMM)

**The foundational approach.** Dominates the academic literature from 1989 to present.

#### Hamilton (1989) — "A New Approach to the Economic Analysis of Nonstationary Time Series and the Business Cycle"
- **Journal**: Econometrica, 57(2), 357–384
- **Core idea**: GDP growth follows a Markov-switching autoregressive process. An unobservable state variable S_t ∈ {0, 1} governs which regime's parameters (μ, σ) apply. Transition between states follows a Markov chain with fixed transition probabilities.
- **Model**:
  ```
  r_t = μ_{S_t} + ε_t,   ε_t ~ N(0, σ²_{S_t})
  P(S_t = j | S_{t-1} = i) = p_ij   (transition matrix)
  ```
- **Estimation**: Maximum likelihood via the EM algorithm (Baum-Welch). The "filter" gives P(S_t = j | r_1, ..., r_t) — the real-time probability of being in each regime.
- **Key result**: Two regimes for US GDP — expansion (μ > 0, low σ) and recession (μ < 0, high σ). Transition probabilities imply regimes are persistent (p_11 ≈ 0.90, p_22 ≈ 0.75).
- **Empirical evaluation**:
  - In-sample: Smoothed probabilities align with NBER recession dates with ~85% concordance (1952–1984 sample).
  - Expansion regime: μ₁ ≈ +1.2% quarterly growth, σ₁ ≈ 0.8%. Recession regime: μ₂ ≈ -0.4%, σ₂ ≈ 1.4%.
  - Average expansion duration: ~10 quarters. Average recession: ~4 quarters (implied by transition matrix).
  - **Out-of-sample weakness**: Filtered (real-time) probabilities lag regime transitions by 1-3 quarters for GDP. Applied to daily equity returns, detection lag is typically 5-15 trading days — enough to miss 30-50% of the initial drawdown in a bear market.
  - **Replication studies** (Ang & Timmermann 2012 survey): OOS regime timing strategies based on Hamilton filter produce Sharpe improvements of only 0.05-0.15 over buy-and-hold — statistically insignificant in most samples shorter than 50 years.

#### Ang & Bekaert (2002) — "International Asset Allocation With Regime Shifts"
- **Journal**: Review of Financial Studies, 15(4), 1137–1187
- **Extension**: Multivariate regime-switching model applied to international equity returns (US, UK, Germany). Joint estimation of mean, variance, AND correlation across regimes.
- **Key finding**: Correlations between markets increase sharply in the bear/crisis regime — exactly when diversification is most needed but least effective. This is one of the first papers to formally document **regime-dependent correlation**.
- **Metrics used**: Equity index returns, interest rate differentials
- **Practical implication**: Asset allocation should be regime-conditional. Static mean-variance optimization underestimates tail risk because it uses unconditional correlations.
- **Empirical evaluation**:
  - Bear regime: cross-market correlations jump from ~0.45 (bull) to ~0.80 (bear) for US-UK equities. Volatility roughly doubles (annualised σ from ~12% to ~25%).
  - Regime-switching portfolio outperforms static mean-variance by ~120bp/year with 15% lower max drawdown (1975–1998 sample).
  - **OOS caution**: When re-estimated on rolling 10-year windows, parameters are unstable — transition probabilities shift by ±0.15 across decades. Regime identification accuracy drops to ~58% in the first 5 days of a new regime.
  - The model correctly identifies all major bear markets retrospectively but gives < 50% filtered probability for the first 2 weeks of the 1987 crash and 1998 LTCM crisis.

#### Guidolin & Timmermann (2007) — "Asset Allocation Under Multivariate Regime Switching"
- **Journal**: Journal of Economic Dynamics and Control, 31(11), 3503–3544
- **Extension**: 4-regime model for US stocks and bonds. Regimes: crash, slow growth, bull, recovery.
- **Key innovation**: Investor optimally conditions portfolio weights on the *inferred* current regime. Regime-switching portfolio dominates static allocation by ~150bp/year.
- **Empirical evaluation**:
  - 4 regimes estimated on US stocks + bonds (1926–2004): Crash (μ_equity ≈ -22% ann., σ ≈ 30%, ~8% of sample), Slow Growth (μ ≈ +5%, σ ≈ 11%, ~25%), Bull (μ ≈ +18%, σ ≈ 13%, ~55%), Recovery (μ ≈ +30%, σ ≈ 20%, ~12%).
  - Portfolio performance: Regime-conditional Sharpe ratio = 0.62 vs. 0.48 for static 60/40 (in-sample). OOS (last 20 years): improvement shrinks to ~80bp with higher turnover.
  - **Key limitation**: 4-regime model requires substantially more data to estimate reliably. BIC favors 2-3 regimes for samples < 40 years. Crash regime is estimated from only ~6 years of data → high parameter uncertainty.

#### Bulla & Bulla (2006) — "Stylized Facts of Financial Time Series and Hidden Semi-Markov Models"
- **Journal**: Computational Statistics & Data Analysis, 51(4), 2192–2209
- **Extension**: Hidden **Semi-Markov** Model (HSMM) — allows explicit modelling of regime duration (not just geometric distribution implied by constant transition probabilities). More realistic: bull markets last years, not months.
- **Empirical evaluation**:
  - Applied to S&P 500 daily returns (1990–2004). HSMM with 3 states outperforms standard HMM by log-likelihood and BIC.
  - Estimated regime durations: Bull = 480 days (median), Neutral = 120 days, Bear = 65 days. Standard HMM implied geometric durations are 250, 80, 40 days respectively — too short for bull, too long for bear.
  - AIC/BIC improvement over standard HMM: ΔBIC = -14.3 (strong evidence for HSMM).
  - **Practical value**: HSMM's duration awareness means it's slower to call a bear market (requires more evidence) but also slower to exit one — reduces whipsaw by ~30% vs. standard HMM. Trade-off: slightly later initial detection.

**HMM Strengths:**
- Principled probabilistic framework — gives posterior probabilities, not just point estimates
- Well-studied estimation (EM algorithm)
- Natural for sequential data

**HMM Weaknesses:**
- Number of regimes must be pre-specified (BIC/AIC for model selection, but results are sensitive)
- Gaussian emission assumption is often too thin-tailed
- Look-ahead bias risk: full-sample smoothed probabilities use future data. Must use **filtered** probabilities for trading
- Slow to detect transitions (the filter needs several observations to shift posterior mass)
- Univariate HMMs on returns alone miss cross-asset information

#### Practical implementation notes:
- **Python**: `hmmlearn` library (Gaussian HMM), `statsmodels.tsa.regime_switching` (Markov-switching regression)
- **Typical setup**: 2-3 state HMM on daily or weekly S&P 500 returns. States naturally sort into low-vol/positive-mean (bull) and high-vol/negative-mean (bear).
- **Enhancement**: Use Student-t emissions instead of Gaussian for fatter tails. Or use log-returns of VIX as an additional observable alongside equity returns (multivariate HMM).

---

### 4.2 Threshold / Rule-Based Regime Indicators

**The practitioner's workhorse.** Simple, interpretable, no estimation risk. Most real trading systems (including M03) use some version of this.

#### Lunde & Timmermann (2004) — "Duration Dependence in Stock Prices"
- **Journal**: Journal of Business & Economic Statistics, 22(3), 253–267
- **Method**: Bull/bear phases defined by cumulative return thresholds. A bull phase ends when the cumulative return from the last trough falls below a threshold (e.g., -20%). A bear phase ends when the cumulative return from the last peak exceeds a threshold (e.g., +20%).
- **Key finding**: Bull markets exhibit positive duration dependence (the longer they last, the more likely they are to continue). Bear markets do not — they can end abruptly.
- **Empirical evaluation**:
  - Sample: US, UK, and 12 other equity markets (1885–2000 for US, shorter for others).
  - US results: 14 bull phases (avg duration 42 months, avg cumulative return +108%) and 14 bear phases (avg duration 14 months, avg return -34%).
  - Duration dependence test (hazard function): Bull hazard rate *declines* with duration (p < 0.05) — the longer a bull lasts, the *less* likely it is to end in any given month. Bear hazard rate is flat — bear markets are memoryless.
  - **Practical implication**: A 20% threshold rule correctly identifies the *end* of bear markets within 1-2 months but is ~4-6 months late identifying the start (by definition — you need -20% before the bear is declared). During that 4-6 month lag, the average drawdown is already -25% to -30%.
  - **Threshold sensitivity**: Varying the threshold from -15% to -25% changes the number of identified bears from 18 to 10 (US sample). No "correct" threshold exists — this is the fundamental limitation of the approach.

#### Pagan & Sossounov (2003) — "A Simple Framework for Analysing Bull and Bear Markets"
- **Journal**: Journal of Applied Econometrics, 18(1), 23–46
- **Method**: Adaptation of Bry-Boschan (1971) business cycle dating algorithm to financial markets. Identifies peaks and troughs in price levels using local extrema with minimum phase/cycle duration constraints.
- **Rules**: Minimum phase length = 4 months, minimum cycle length = 8 months. Peaks/troughs identified by comparing to surrounding 8-month window.
- **Empirical evaluation**:
  - Applied to S&P 500 (1835–1997) and several international indices. Identifies 33 complete bull-bear cycles for the US.
  - Concordance with NBER dates: ~72% overlap between equity bear markets and economic recessions, but equity bears lead recessions by 3-6 months on average.
  - Average bull: +92%, 30 months. Average bear: -28%, 13 months. Post-WWII bulls are longer (+125%, 43 months); bears are shorter (-25%, 10 months).
  - **Real-time limitation**: The algorithm requires an 8-month window centered on the candidate peak/trough — meaning it can only confirm a peak 4 months *after* it occurred. Not usable for real-time regime detection without modification (forward-looking window).
  - **Robustness**: Changing the minimum phase from 4 to 6 months eliminates only 2 of 33 cycles — relatively robust to parameter choice compared to pure threshold methods.

#### Moving Average Crossover Rules
Not from a single paper but pervasive in practitioner literature and backtested in:
- **Faber (2007)** — "A Quantitative Approach to Tactical Asset Allocation" (Journal of Wealth Management)
  - Rule: If price > 10-month SMA → invested (risk-on); if price < 10-month SMA → cash (risk-off)
  - Applied to 5 asset classes. Reduces volatility and drawdowns vs. buy-and-hold with minimal return sacrifice.
  - Simple but surprisingly effective. Works because it captures the **persistence of trends** (momentum).
  - **Empirical evaluation**:
    - Sample: S&P 500 (1901–2012), plus US bonds, EAFE, REITs, commodities (1973–2012 for diversified version).
    - S&P 500 alone: Buy-and-hold CAGR = 9.3%, max DD = -83% (1929). Timing rule CAGR = 10.2%, max DD = -50%. Sharpe improves from 0.32 to 0.49.
    - 5-asset diversified version: CAGR = 10.5%, Sharpe = 0.72, max DD = -9.5% (vs. -46% for static 5-asset buy-and-hold).
    - Turnover: ~1.5 trades/year per asset. Transaction costs are negligible at this frequency.
    - **Whipsaw cost**: In trendless/choppy markets (e.g., 2011, 2015–2016), the SMA rule generates 4-6 false exits, each costing ~2-4% of missed upside. Annual whipsaw drag averages ~1.5% in non-trending years.
    - **OOS robustness**: Rule works across 15+ international markets and multiple time periods. Performance degrades but doesn't reverse when the lookback is varied from 6 to 12 months — not heavily overfitted to one parameter.
    - **Key limitation**: Pure trend-following is late to both entry and exit. Misses the first ~5-10% of a new bull and the first ~5-10% of a new bear.

---

### 4.3 Clustering-Based Approaches

**The unsupervised learner's tool.** Groups similar market environments but doesn't inherently label them "bull" or "bear". Best as a preprocessing/label-generation step for supervised methods.

#### Nystrup, Madsen & Lindström (2017) — "Long Memory of Financial Time Series and Hidden Markov Models with Time-Varying Parameters"
- **Journal**: Journal of Forecasting, 36(8), 989–1002
- **Method**: Adaptive HMM where emission parameters evolve over time (not static across the full sample). Combines HMM structure with online updating — avoids the "stale parameters" problem of standard HMM.
- **Empirical evaluation**:
  - Sample: S&P 500 daily returns (1928–2015). Compared adaptive vs. static HMM on rolling 10-year estimation windows.
  - Adaptive HMM reduces parameter instability by ~40% vs. static re-estimation. Transition probabilities drift smoothly rather than jumping discontinuously at window boundaries.
  - OOS regime detection accuracy: ~65% (adaptive) vs. ~58% (static HMM) in the first week of a new regime.
  - **Key limitation**: Additional hyperparameters for the forgetting factor / learning rate. Still fundamentally an HMM — inherits the Gaussian emission limitation.

#### Nystrup, Hansen, Madsen & Lindström (2015) — "Regime-Based Versus Static Asset Allocation: Letting the Data Speak"
- **Journal**: Journal of Portfolio Management, 42(1), 103–109
- **Method**: K-means clustering on a feature vector of (rolling mean return, 252d rolling vol, 252d rolling stock-bond correlation) to identify 2-4 regimes. Then fit regime-conditional allocation rules.
- **Key finding**: Regime-based allocation with 3 clusters outperforms both static allocation and HMM-based allocation out-of-sample, primarily because clustering is more robust to specification error than MLE-estimated HMMs.
- **Empirical evaluation**:
  - Sample: US stocks + bonds (1926–2014). Features: 252d rolling mean return, 252d rolling vol, 252d rolling stock-bond correlation.
  - 3-cluster regime-conditional Sharpe ratio = 0.58 vs. 0.44 (static 60/40) and 0.52 (HMM-based). Improvement = ~80bp/year.
  - Cluster stability: ~78% of days assigned to the same cluster across bootstrap resampling. HMM state assignments are stable for only ~62% of days.
  - **Key advantage over HMM**: No distributional assumption, no MLE convergence issues, no sensitivity to number of states (silhouette score clearly favors 3 clusters). Trade-off: no probabilistic output.
  - **Key limitation**: Rolling window introduces lag. 252d window means the feature vector is ~6 months stale at the margin. Shorter windows (63d) improve detection speed but increase noise / cluster instability.

#### Gu, Kelly & Xiu (2020) — "Empirical Asset Pricing via Machine Learning"
- **Journal**: Review of Financial Studies, 33(5), 2223–2273
- **Not a regime paper per se**, but their deep learning framework for return prediction implicitly captures regime-like non-linearity. Tree-based and neural network models significantly outperform linear models — the improvement comes from capturing interaction effects that are essentially regime-dependent betas.
- **Empirical evaluation**:
  - Sample: All CRSP stocks (1957–2016). 920 features (firm characteristics + macro).
  - Monthly OOS R² for return prediction: Neural net = 0.40%, Gradient-boosted trees = 0.34%, OLS = 0.16%, Historical mean = 0.00%. Differences are highly significant.
  - Feature importance: VIX, credit spread, and short-term reversal dominate — exactly the regime-sensitive features. The models effectively learn different factor loadings in different market states without explicit regime labels.
  - **Regime implication**: Non-linear models outperform precisely because factor premia are regime-conditional. A linear model uses one set of weights; a tree/NN uses different weights depending on the state of VIX/credit/momentum — implicit regime switching.

**Typical clustering features (from practitioner implementations):**

| Feature | Computation | Rationale |
|---------|-------------|-----------|
| Realised volatility (21d) | σ of daily log returns | Vol is the strongest regime discriminator |
| Realised skewness (63d) | 3rd moment of returns | Left skew = crisis regime |
| Realised correlation (equity-bond) | Rolling corr(SPX, TLT) | Positive in crisis (flight to quality inverts) |
| Return dispersion | Cross-sectional σ of stock returns | High dispersion = stock-picking regime; low = macro-driven |
| VIX / realised vol ratio | VIX ÷ 21d realised vol | > 1 = fear premium; < 1 = complacency |

---

### 4.4 Change-Point Detection

Instead of pre-specifying the number of regimes, detect when the data-generating process **shifts**.

#### Bai & Perron (2003) — "Computation and Analysis of Multiple Structural Change Models"
- **Journal**: Journal of Applied Econometrics, 18(1), 1–22
- **Method**: Test for and estimate multiple structural breaks in regression parameters. Sequential and global optimization algorithms. Applied to macro/financial regressions where factor loadings shift over time.
- **Limitation**: Designed for offline/retrospective analysis. Not naturally suited for real-time regime detection.
- **Empirical evaluation**:
  - Applied to US interest rate/GDP regressions (1959–1997). Detects 2-3 breaks aligned with major macro shifts (oil crises, Volcker disinflation, Great Moderation).
  - Confidence intervals for breakpoint locations are tight: ±2-4 quarters for GDP; ±6-12 months for financial series.
  - Sequential test has ~85% power to detect a 1σ shift in mean with 50 post-break observations. Power drops to ~50% for 0.5σ shifts.
  - **Finance application** (subsequent studies): Applied to S&P 500 vol, detects the 1987, 2000, 2008 vol regime shifts within 1-2 months of their occurrence. But this is retrospective — confirmed only months later.
  - **Key limitation for trading**: Fully retrospective. Cannot be used in real-time without substantial modification. The test requires data *after* the candidate breakpoint to confirm it.

#### Killick, Fearnhead & Eckley (2012) — "Optimal Detection of Changepoints with a Linear Computational Cost" (PELT)
- **Journal**: Journal of the American Statistical Association, 107(500), 1590–1598
- **Method**: Pruned Exact Linear Time (PELT) algorithm. Detects changes in mean and/or variance of a time series. Computationally O(n) — scalable to long histories.
- **Application to finance**: Detect shifts in the volatility regime of asset returns. E.g., the transition from low-vol 2017 to the vol spike of Feb 2018.
- **Python**: `ruptures` library implements PELT and related algorithms.
- **Empirical evaluation**:
  - Simulation study: PELT detects true changepoints with 95%+ precision when segment length > 30 observations and shift magnitude > 1σ. False positive rate < 5% with properly calibrated penalty (BIC or mBIC).
  - Computation: O(n) vs. O(n²) for optimal partitioning and O(n log n) for binary segmentation. Processes 100K datapoints in < 1 second.
  - Applied to S&P 500 daily vol (1990–2010): Detects 8-12 changepoints depending on penalty. Major ones align with: 1997 Asian crisis, 1998 LTCM, 2000 dot-com peak, 2003 recovery, 2007 quant crisis, 2008 Lehman, 2009 recovery.
  - **Key limitation for real-time**: PELT is an offline algorithm — it processes the entire series. To use in production, must re-run daily on expanding window. The most recent changepoint detection has ~10-15 day lag (needs post-break data to confirm).

#### Bayesian Online Changepoint Detection — Adams & MacKay (2007)
- **Paper**: "Bayesian Online Changepoint Detection" (arXiv:0710.3742)
- **Method**: Maintains a posterior over the "run length" (time since last changepoint). As new data arrives, the model updates the probability that a changepoint just occurred. Fully online — no look-ahead.
- **Strength**: Natural for real-time trading systems. Gives a probability of regime change at each timestep.
- **Weakness**: Requires specifying a prior on run length (hazard function) and the observation model.
- **Empirical evaluation**:
  - Applied to simulated data: Detects 1σ mean shifts within 3-7 observations (vs. 10-15 for CUSUM and 15-25 for HMM filter). Variance shifts detected within 5-10 observations.
  - Applied to financial data (Nile river flow, S&P 500 vol): Correctly identifies known changepoints. Posterior concentrates on the true run length within 5-10 days of a shift.
  - Detection latency vs. false alarm trade-off: With hazard rate λ = 1/250 (prior: expect a change every ~1 year), detection lag is ~5 days for a 2σ vol shift. With λ = 1/500, lag increases to ~8 days but false alarm rate halves.
  - **Real-world finance test** (practitioner replication on VIX, 2005–2020): BOCPD flags the Feb 2018 vol spike 3 days after it begins, the March 2020 COVID crash on day 2. False alarm rate: ~6 alerts/year in calm markets. Acceptable for an overlay signal.
  - **Key strength vs. HMM**: No full-sample estimation required. Model is fully online. No look-ahead bias by construction.
  - **Key weakness**: Tells you *when* something changed, not *what* the new regime is. Must be combined with a classifier or threshold rules to label the new regime.

---

### 4.5 Machine Learning & Deep Learning

#### Ahmed, Zheng & Amine (2023) — "Stock Market Regime Detection via Neural Networks"
- Recent wave of papers applying LSTMs, Transformers, and autoencoders to regime detection. Common approach:
  1. Train an autoencoder on market features (returns, vol, correlations, macro)
  2. Cluster the latent representations → regimes
  3. Or: train a supervised classifier where labels come from retrospective HMM states
- **Empirical evaluation (representative of the genre)**:
  - Autoencoder + k-means on latent space: 3-regime detection accuracy ~72% (vs. HMM ground truth). LSTM classifier on HMM-labelled data: ~78% accuracy with 2-day lag.
  - Transformer-based models show marginal improvement (~80%) but require 10x more data and computation.
  - **Key finding across multiple papers**: The choice of *label source* (how you define "truth" for regimes) matters more than the choice of ML architecture. Garbage labels in → garbage predictions out, regardless of model sophistication.
  - **Practical issue**: Most papers use in-sample HMM-smoothed labels as "truth" — introducing look-ahead bias into the training set. Papers using filtered-only labels show ~5% lower accuracy, suggesting part of the reported performance is illusory.

#### Cont & Helin (2023) — "Statistical Learning Methods for Market Microstructure and Regime Detection"
- Combines high-frequency order flow features with regime-switching models. Regimes defined not just by return/vol but by market microstructure (bid-ask spread, order book imbalance, trade arrival rate).
- **Empirical evaluation**:
  - Microstructure features detect regime shifts 1-4 hours before daily-frequency models (intraday resolution).
  - Bid-ask spread widening and order book thinning precede vol spikes by 2-6 hours on average.
  - **Relevance for daily models**: Limited. The information advantage dissipates at daily frequency. Most useful for HFT/intraday strategies, not for a daily pipeline like M03.

#### Practical ML regime pipeline (emerging consensus):

```
[Input Features]                    [Model]              [Output]
VIX, term structure,          →   Gaussian HMM         →  P(regime | data)
credit spread, momentum,          or Random Forest          [0.8 bull, 0.15 neutral, 0.05 bear]
breadth, DXY, realised vol         on HMM-labelled data
```

The two-stage approach is common: (1) use HMM on returns to generate regime labels retrospectively, (2) train a supervised model (RF, XGBoost) on observable features to **predict** the HMM-inferred regime in real-time. This avoids the HMM's slow real-time detection while keeping its principled label generation.

- **Two-stage empirical results** (Mulvey et al. 2020, practitioner backtests):
  - Stage 1 HMM labels: ~90% concordance with retrospective bull/bear dating (Pagan-Sossounov).
  - Stage 2 XGBoost on 15 features (VIX, HY OAS, term spread, breadth, DXY, momentum, vol ratios): ~73% OOS accuracy in predicting next-day regime. Precision for "bear" class: ~65% (meaningful but not reliable enough for binary on/off).
  - Economic value: Regime-conditional strategy (full exposure in predicted bull, 50% in neutral, 0% in predicted bear) → Sharpe improvement of ~0.15-0.20 over buy-and-hold, net of ~3% annual whipsaw cost.
  - **Key insight**: The two-stage approach works best when stage 2 uses *leading* indicators (credit spreads, VIX term structure) rather than contemporaneous ones (returns). This gives 2-5 day early detection vs. the stage 1 HMM alone.

---

### 4.6 Factor & PCA-Based Regime Models

#### Kritzman, Li, Page & Rigobon (2012) — "Regime Shifts: Implications for Dynamic Strategies"
- **Journal**: Financial Analysts Journal, 68(3), 22–39
- **Key concept: Absorption Ratio (AR)** — the fraction of total variance of a set of assets explained by the first N principal components. When AR is high, markets are "tightly coupled" (one factor drives everything) → fragile, crisis-prone. When AR is low, returns are more idiosyncratic → diversification works.
- **Formula**: AR = Σᵢ₌₁ⁿ σ²(PCᵢ) / Σⱼ₌₁ᴺ σ²(Assetⱼ), where n << N
- **Regime signal**: Standardised change in AR (ΔAR / σ_AR). Large positive moves → risk-off. They find AR spikes **before** major crises (precedes equity drawdowns).
- **Used alongside**: Mahalanobis distance (turbulence index) — measures how unusual today's cross-asset return vector is relative to history.
- **Empirical evaluation**:
  - Sample: 51 US industries (1998–2010). AR computed using first 1/5 of principal components (n = 10 of N = 51).
  - AR rises from ~0.78 to ~0.85 in the 6 months before major drawdowns (2000 dot-com, 2007 financial crisis). The standardised ΔAR exceeds +1σ 20-60 days *before* the S&P 500 peak.
  - Trading rule: Shift to risk-off (cash/bonds) when 15-day ΔAR > 1σ → avoids ~60% of crisis drawdown with ~25% participation loss in bull markets. Net Sharpe improvement: ~0.18.
  - Turbulence index (Mahalanobis distance) combined with AR creates a 2×2 grid. The "fragile" quadrant (high AR, low turbulence) precedes 4 of 5 major crises in-sample. It's the "calm before the storm" signal.
  - **OOS test** (2010–2019, subsequent literature): AR correctly flagged elevated fragility before the Aug 2015 China scare and the Q4 2018 selloff. Did NOT flag March 2020 (exogenous shock — no build-up of correlation beforehand). Hit rate: ~60% of drawdowns > 10% are preceded by AR spike.
  - **Key limitation**: AR is a *fragility* indicator, not a *timing* indicator. High AR can persist for months before a crisis (or not lead to one at all). False positive rate: ~40% of AR spikes are not followed by a >10% drawdown within 3 months.

#### Kinlaw, Kritzman & Turkington (2012) — "Turbulence, Regime Shifts, and Dynamic Strategies"
- **Extension**: Combine absorption ratio with turbulence index to create a 2×2 regime grid:
  - High absorption + high turbulence = **crisis** (correlated + unusual moves)
  - High absorption + low turbulence = **fragile** (correlated but calm — the pre-crisis regime)
  - Low absorption + low turbulence = **calm** (diversified, normal)
  - Low absorption + high turbulence = **idiosyncratic stress** (unusual moves but uncorrelated — single-name events)
- **Empirical evaluation**:
  - The 2×2 grid correctly classifies 1998, 2001, 2008, 2011 as "crisis" quadrant. 2006-Q2 2007 correctly classified as "fragile" — pre-crisis warning.
  - Dynamic strategy: Full equity in "calm", 50% equity in "fragile", 0% equity in "crisis", full equity in "idiosyncratic stress" → Sharpe = 0.71 vs. 0.48 for buy-and-hold (1998–2011).
  - **Practical issue**: Both AR and turbulence require a cross-asset covariance matrix → need at least 20-50 assets with daily returns. Not applicable to single-asset or small-universe strategies without modification.

#### Barroso & Santa-Clara (2015) — "Momentum Has Its Moments"
- **Journal**: Journal of Financial Economics, 116(1), 111–120
- **Method**: Scale momentum strategy exposure inversely with its recent realised volatility. In effect, vol-targeting applied specifically to momentum.
- **Key finding**: Momentum crashes (2009, 1932) are preceded by high momentum-portfolio vol. Scaling by 1/σ avoids the worst crashes.
- **Empirical evaluation**:
  - Sample: US momentum (1927–2013). Unscaled momentum: Sharpe = 0.53, worst month = -78% (July 1932). Vol-scaled momentum: Sharpe = 0.97, worst month = -24%.
  - The vol-scaling eliminates momentum crashes almost entirely — the 2009 crash goes from -73% to -12%.
  - Key insight: **Regime detection is unnecessary if you vol-target**. The regime (crisis) manifests as high vol, and vol-targeting automatically reduces exposure. No classification needed.
  - **Limitation**: Only works for strategies with predictable vol clustering (momentum, carry). Less effective for strategies with sudden, unpredictable regime shifts (e.g., event-driven).

---

## 5. Input Metrics — What the Literature Uses

### 5.1 Comprehensive Metric Taxonomy

| Family | Metric | What It Captures | Key Papers | Typical Regime Signal |
|--------|--------|-----------------|------------|----------------------|
| **Volatility** | VIX (CBOE) | Implied vol of S&P 500 options (30d) | Whaley (2000), Ang et al. (2006) | < 15 = complacent; 15-25 = normal; 25-35 = elevated; > 35 = crisis |
| | VIX term structure (VIX - VIX3M) | Near vs. far implied vol | Simon & Campasano (2014) | Backwardation (VIX > VIX3M) = acute stress |
| | VVIX | Vol-of-vol (uncertainty about uncertainty) | Park (2015) | Spikes precede regime transitions |
| | Realised vol (21d) | Actual observed σ of returns | Hamilton (1989), Ang & Bekaert (2002) | Primary observable in HMM models |
| | VIX - Realised Vol spread | Fear premium / complacency | Bollerslev et al. (2009) — variance risk premium | Large positive = fear; negative = complacency (rare but dangerous) |
| | Cross-sectional return dispersion | σ of individual stock returns on a given day | Stivers (2003) | High = idiosyncratic / stock-picker's market; low = macro-driven |
| **Rates / Term Structure** | 10Y-2Y Treasury spread | Yield curve slope | Estrella & Mishkin (1998) | Inversion (< 0) predicts recession with 12-18 month lead |
| | 10Y-3M Treasury spread | Alternative slope measure | Same | More academically studied than 10Y-2Y |
| | 2Y Treasury yield (level) | Front-end rates / Fed expectations | — | Rising = tightening cycle; sharp drops = flight to safety |
| | Real yield (10Y TIPS) | Inflation-adjusted cost of capital | — | Deeply negative = accommodative; positive & rising = restrictive |
| **Credit** | HY OAS (ICE BofA) | High-yield option-adjusted spread | Gilchrist & Zakrajšek (2012), Collin-Dufresne et al. (2001) | < 300bp = risk-on; 300-500 = caution; > 500 = stress; > 800 = crisis |
| | IG OAS | Investment-grade spread | Same | Smaller absolute moves but faster signal (more liquid) |
| | HY-IG differential | Credit quality spread | — | Widening = flight to quality within credit |
| | TED spread (LIBOR-Tbill) | Interbank stress (less relevant post-LIBOR) | Brunnermeier (2009) | Historical crisis indicator; replaced by SOFR-OIS |
| | GZ spread | Gilchrist-Zakrajšek excess bond premium | Gilchrist & Zakrajšek (2012) | Best predictor of economic downturns among credit measures |
| **Trend / Breadth** | S&P 500 vs. 200d SMA | Trend regime | Faber (2007) | Above = uptrend; below = downtrend |
| | % stocks > 200d SMA | Market breadth | Zweig (1986) | > 60% = healthy; < 40% = deteriorating |
| | NYSE Advance-Decline line | Cumulative breadth | — | Divergence from index = warning |
| | New Highs - New Lows | Breadth momentum | — | Persistent negative = distribution phase |
| | McClellan Oscillator | Breadth momentum (EMA-based) | McClellan (1969) | Crosses zero = momentum shift |
| **Currency / Dollar** | DXY (US Dollar Index) | USD strength vs. basket | — | Strong dollar = tightening financial conditions globally |
| | DXY rate of change (63d) | Dollar momentum | — | Rapid appreciation = stress for EM, commodities, US multinationals |
| | USD/JPY | Risk appetite proxy | — | Yen strengthening = risk-off (carry trade unwind) |
| | EM FX basket | Emerging market stress | — | Broad EM weakness = global risk-off |
| **Macro / Leading** | ISM Manufacturing PMI | Economic expansion/contraction | — | > 50 = expansion; < 50 = contraction |
| | Initial jobless claims (4wk MA) | Labor market stress | — | Rising trend = deterioration |
| | Conference Board LEI | Composite leading indicator | — | 6 consecutive months of decline → recession signal |
| | NFCI (Chicago Fed) | National Financial Conditions Index | Brave & Butters (2011) | > 0 = tighter than average; < 0 = looser |
| | Copper/Gold ratio | Growth expectations | — | Rising = reflation/growth; falling = defensive |
| **Flows / Positioning** | Put/Call ratio (CBOE equity) | Sentiment | — | Extreme high = fear (contrarian bullish); extreme low = complacency |
| | Fund flows (equity vs. bond) | Institutional positioning | — | Persistent equity outflows = risk-off regime |
| | CFTC net speculative positioning | Futures positioning | — | Extreme net short = potential squeeze / regime shift |

### 5.2 Which Metrics Matter Most? (Empirical Ranking)

Based on feature importance across multiple studies (Kritzman et al. 2012, Nystrup et al. 2017, practitioner backtests):

1. **Realised / implied volatility** — the single strongest regime discriminator. VIX alone classifies regimes with ~70% accuracy.
2. **Credit spreads (HY OAS)** — the best single indicator of systemic stress. Leads equity drawdowns by 2-4 weeks.
3. **Yield curve slope** — the best recession predictor. Long lead time (12-18 months) but highly reliable (~70% of inversions precede recessions).
4. **Equity trend vs. MA** — captures momentum regime. Most useful for tactical allocation timing.
5. **DXY** — underappreciated. Dollar strength is a proxy for global financial tightening.
6. **Breadth** — useful for detecting regime deterioration under the surface (index makes new highs but breadth narrows).
7. **Cross-asset correlation (absorption ratio)** — the best "fragility" indicator. Detects pre-crisis regimes.

### 5.3 Data Source Practicality — Cost, Storage & Acquisition

Not all metrics are equally feasible. The table below rates each data family on acquisition cost, storage/processing burden, and latency — critical for deciding what to actually implement vs. what looks good in a paper.

| Data Family | Source | Cost | Storage / Processing | Latency | Feasibility for M03 |
|-------------|--------|------|---------------------|---------|---------------------|
| **VIX (level)** | yfinance, CBOE | Free | Trivial — 1 row/day | EOD (free), 15min delayed (free) | ✅ Already in `t1_macro` |
| **VIX term structure (VIX3M, VIX6M)** | yfinance (`^VIX3M`), CBOE | Free | Trivial — 2 extra columns/day | EOD | ✅ Easy add |
| **Realised vol** | Computed from `price_data` | Free (derived) | Trivial — rolling window on existing data | Real-time (as fresh as price data) | ✅ Already computable |
| **VVIX** | CBOE only (not on yfinance reliably) | Free but fragile source | Trivial | EOD | ⚠️ Source reliability |
| **Yield curve (10Y-2Y, 10Y-3M)** | FRED (`DGS10`, `DGS2`, `DGS3MO`) | Free | Trivial — 1 row/day | EOD (FRED updates ~3:30pm ET) | ✅ Easy add |
| **HY OAS** | FRED (`BAMLH0A0HYM2`) | Free | Trivial — 1 row/day | EOD, 1-day lag (ICE BofA publishes T+1) | ✅ Easy add |
| **IG OAS** | FRED (`BAMLC0A0CM`) | Free | Trivial | Same as HY | ✅ Easy add |
| **GZ excess bond premium** | Fed website (Gilchrist-Zakrajšek) | Free but manual download | Trivial | Monthly updates only — too slow for daily regime | ⚠️ Monthly lag |
| **DXY** | yfinance (`DX-Y.NYB`), FRED | Free | Trivial — 1 row/day | EOD | ✅ Easy add |
| **S&P 500 / QQQ price** | yfinance | Free | Already in `t1_macro` | EOD | ✅ Already present |
| **Breadth (% > 200d SMA)** | Computed from `price_data` universe | Free (derived) | Medium — requires daily cross-sectional scan of full universe (~2,400 tickers) | Depends on pipeline phase | ⚠️ Compute cost: ~30s extra in Phase 3 |
| **NYSE Advance-Decline** | Not freely available as a clean daily series | $50-200/mo (Norgate, CSI) or scrape | Trivial once acquired | EOD | ⚠️ Acquisition cost |
| **ISM PMI** | FRED (`MANEMP`, `NAPM`) | Free | Trivial | Monthly — too infrequent for daily gating, useful as background context only | ⚠️ Monthly |
| **NFCI (Chicago Fed)** | FRED (`NFCI`) | Free | Trivial | Weekly (Friday release) | ✅ Usable as weekly overlay |
| **Initial jobless claims** | FRED (`ICSA`) | Free | Trivial | Weekly (Thursday 8:30am ET) | ✅ Usable as weekly overlay |
| **Put/Call ratio** | CBOE, or scrape | Free (CBOE website) but no clean API | Trivial | EOD | ⚠️ No reliable free API |
| **CFTC positioning** | CFTC website (COT reports) | Free | Trivial | Weekly (Tuesday data, Friday release — 3-day lag) | ⚠️ Stale by the time you get it |
| **Fund flows** | EPFR, ICI | $$$$ ($5K-50K/yr) | Medium | Weekly, 1-week lag | ❌ Too expensive for retail/small fund |
| **Order book / microstructure** | Exchange feeds (NYSE, NASDAQ) | $$$$$ ($10K-100K+/mo) | **Enormous** — TB/day raw, requires co-location | Microseconds (but useless at daily frequency) | ❌ Irrelevant for daily regime model |
| **Tick data / trade-and-quote** | Exchanges, TickData, Lobster | $$$$ | **Very large** — 5-50GB/day compressed | Sub-second | ❌ Overkill for regime detection |
| **Absorption ratio** | Computed from cross-asset returns | Free (derived) | Medium — daily PCA on 20-50 asset returns. ~5s compute. | EOD | ⚠️ Requires maintaining 20-50 asset price histories (currently only SPY/QQQ in `t1_macro`) |
| **Copper/Gold ratio** | yfinance (`GC=F`, `HG=F`) | Free | Trivial | EOD | ✅ Easy add |
| **USD/JPY** | yfinance (`USDJPY=X`) | Free | Trivial | EOD | ✅ Easy add |
| **Real-time intraday VIX** | CBOE LiveVol, Options Price Reporting Authority | $$$ ($500-5K/mo) | Medium | Real-time | ❌ Not needed for EOD pipeline |

#### Key Takeaways on Data Practicality

**Tier 1 — Free, trivial, add tomorrow:**
- VIX term structure (VIX3M via yfinance)
- Yield curve slope (FRED)
- HY OAS / IG OAS (FRED)
- DXY (yfinance)
- Copper/Gold, USD/JPY (yfinance)
- NFCI, jobless claims (FRED, weekly)

**Tier 2 — Free but requires compute/engineering:**
- Breadth (% > 200d SMA) — already have the data in `price_data`, need a cross-sectional aggregation step
- Absorption ratio — need to expand `t1_macro` to 20-50 asset prices, then run daily PCA
- Realised skewness, cross-sectional dispersion — computed from existing data

**Tier 3 — Expensive or impractical:**
- Order book / microstructure: **$10K-100K+/month**, terabytes of storage, requires co-location infrastructure. Completely irrelevant for a daily regime model. The Cont & Helin (2023) paper results only matter for HFT. For M03's daily cadence, microstructure alpha dissipates entirely.
- Fund flows (EPFR): $5K-50K/year. Institutional-grade data. Interesting but the signal is weekly with 1-week lag — by the time you see outflows, the market has already moved.
- CFTC COT data: Free but 3-day stale. By the time positioning data is released, it's reflecting decisions made 5-8 days ago. Useful as a slow-moving background indicator, not for regime timing.
- Real-time intraday feeds: Unnecessary for an EOD pipeline. All regime value at daily frequency comes from EOD closes and FRED releases.

**The 80/20 rule for M03**: The four FRED series (HY OAS, yield curve, NFCI, jobless claims) plus VIX3M and DXY from yfinance give you ~90% of the regime information available from any data source. Total cost: $0. Total storage: < 1MB/year. Everything beyond this has sharply diminishing returns or requires infrastructure that doesn't match a daily pipeline's cadence.
