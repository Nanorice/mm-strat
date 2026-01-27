# SEPA-Style Equity Screening and ML Pipeline

## a Project summary: purpose, structure, and components

### Purpose
Build a **SEPA-style equity screening and ML pipeline** whose primary goal is to **identify "super performers"** (high upside potential) from a SEPA-filtered universe, using daily data and separating "pattern/potential detection" from "risk control" and later "exit optimization".

### Structure (end-to-end)

1. **Universe + data layer**
    * Daily OHLCV (plus corporate actions), benchmark/sector series, and liquidity measures.
    * Point-in-time feature generation (no future leakage).
2. **SEPA screener (candidate generator)**
    * Produces a **candidate list** based on SEPA-aligned pattern conditions (trend, contraction/tightness, breakout quality, relative strength). This is the "funnel" stage inspired by Minervini's SEPA framework [Minervini].
3. **Regime monitor (separate model/monitor)(to be implemented)**
    * Outputs a regime score/label (risk-on/off, volatility regime, breadth regime, etc.).
    * Fed as features into M01/M02, but must be trained point-in-time.
4. **M01: upside potential model (ranking)**
    * Learns **upside potential** using a target derived from **maximum favorable excursion (MFE)**, i.e., "max run-up within the event window" [Investopedia: MFE].
    * Candidate label variants:
        * (a) $y = MFE$
        * (b) $y = \log(1 + MFE)$ (tail smoothing)
        * (c) $y = MFE/ATR$ (volatility normalization; ATR definition [Investopedia: ATR])
        * (d) with vs without loser deletion (survivor filter)
5. **M02: downside/risk feasibility model**
    * Uses broader features to estimate downside risk (e.g., probability of hitting a stop/invalidating conditions).
    * Often naturally expressed as **probabilities**, which should be **calibrated** [scikit-learn calibration], [Platt 1999].
6. **Optional M03: "super performer" classifier**
    * If you want a calibrated probability like "chance this becomes top 1%/5% MFE", M03 converts the upside problem into a probability output (often easier to integrate/threshold than raw heavy-tail regression).
7. **(Later) execution/exit module**
    * TP/SL staging, trend break exits, sizing, and implementation costs. Not required to define now, but label definitions must remain non-leaky and interpretable.

---

### Pipeline integration

**Strengths**
* Modular design enables iteration (SEPA -> M01 -> M02 -> later exits).

**Weaknesses / risks**
* Misinterpreting M01 as "profit" instead of "run-up potential" can cause incorrect downstream decisions (you already aligned on naming/semantics).

---

## c) Development areas and what to do now

### 1) SEPA screener: add guardrails (monitoring, not "alpha proof")
Implement a lightweight "SEPA health dashboard":
* **Supply stability**
    * pass count distribution (median, 10th/90th percentile)
    * churn / turnover of candidates
* **Concentration**
    * sector/industry weights of passers
* **Liquidity**
    * ADV filter/monitor [Investopedia: ADTV]
    * spread proxy monitor if quotes unavailable [Corwin-Schultz]
* **Outcome sanity**
    * forward return distribution summaries for passers vs universe (multiple horizons)
    * regime splits (so you can see when SEPA is "out of season")

### 2) M01: implement the evaluation framework and compare label variants (a–d)

**Design**
* Use **walk-forward** OOS evaluation (not random splits). Basic reference: [TimeSeriesSplit].
* If event windows cross split boundaries, use **purged/embargo logic** [mlfinlab PurgedKFold].

**Scorecard metrics (optimize for ranking and tail capture)**
* **Rank quality:** Spearman IC between predicted and realized target.
* **Tail capture:** Lift of realized MFE among top 1%/5%/10% selected by M01.
* **Super-winner capture (percentile defined):** precision and recall for "top q% realized MFE".
* **Stability:** metrics by year and by regime bucket.

**Volatility detector checks (explicitly answer your concern)**
* Correlation of M01 predictions with entry ATR.
* Selection concentration: fraction of top picks coming from highest ATR decile.
* IC within ATR buckets.

> This is exactly where **ATR-normalized run-up** helps: using $MFE/ATR$ tends to reduce "volatility detector" behavior because the target becomes "run-up per unit risk" rather than "absolute run-up" [Investopedia: ATR].

**Statistical validation**
* Block bootstrap confidence intervals on fold metrics.
* Permutation tests for IC significance.
* Track selection bias if you trial many variants [Bailey et al.].

**Calibration for application**
* Treat M01 output as a **score**, then build a monotonic mapping from predicted score to realized run-up using isotonic regression on OOS predictions [IsotonicRegression].
* This produces a stable interpretation: "names scored in decile 10 historically reached X run-up".

### 3) M02: tighten labeling selection and probability calibration
* If using triple-barrier or stop/time rules, select parameters via **nested walk-forward** to avoid multiple-testing bias [Bailey et al.].
* Use purging/embargo if event windows overlap [mlfinlab PurgedKFold].
* Calibrate probabilities (reliability curves, Brier score, Platt/isotonic) [scikit-learn calibration], [Platt 1999].

### 4) Decide on M03 only after you see M01 score stability

**Decision rule:**
* If M01 variants produce **stable tail capture and stable calibration curves**, you may not need M03.
* If M01 remains unstable due to heavy tails [Cont 2001], add M03 to output a calibrated probability of "top q% run-up", which integrates cleanly with M02.