# Module Passport: M03 Model (Market Regime)

## 1. Overview
*   **Responsibility:** Calculates a macro-econometric "Market Regime" risk score (0-100) to gauge the safety of the trading environment. It acts as a "Traffic Light" system for the algorithmic trading pipeline, determining when to be aggressive (Green/Bull), cautious (Yellow/Neutral), or defensive (Red/Bear).
*   **Key Dependencies:**
    *   `src.macro_engine.MacroEngine`: Fetches FRED/FMP macro data (Liquidity, VIX, Spreads).
    *   `src.data_engine.DataRepository`: Fetches SPY price data.
    *   `models/m03_config.json`: Configuration persistence for weights and thresholds.

## 2. File Structure

| File | Purpose |
| :--- | :--- |
| `src/pipeline/m03_regime.py` | **Core Calculator.** Contains `M03RegimeCalculator`. Implements the 3-pillar scoring logic (Trend, Liquidity, Risk). |
| `src/evaluation/m03_evaluator.py` | **Validation Engine.** Contains `M03Evaluator`. Tests model against historical Ground Truth using AUC, CCR, and Lag metrics. |
| `src/evaluation/m03_grid_search.py` | **Optimizer.** Contains `M03GridSearch`. Runs ablation studies on weights and VIX curves to maximize discrimination. |
| `src/evaluation/m03_ground_truth.py` | **Reference Data.** Hard-coded list of historical market regimes (e.g., "GFC", "COVID Crash") for validation. |
| `models/m03_config.json` | **Configuration.** JSON file storing current weights, thresholds, and calibration metadata. |

## 3. Data Schemas

### Regime Output (DataFrame)
Produced by `calculate_history_vectorized`.

| Column | Type | Description |
| :--- | :--- | :--- |
| `date` | Index | Trading date. |
| `score` | float | Composite regime score (0-100). |
| `category` | str | `strong_bull`, `bull`, `neutral`, `bear`, `strong_bear`. |
| `trend_score` | float | Component score for Trend pillar (0-100). |
| `liquidity_score` | float | Component score for Liquidity pillar (0-100). |
| `risk_appetite_score` | float | Component score for Risk Appetite pillar (0-100). |
| `spy_close` | float | Raw SPY close price. |
| `sma_200` | float | 200-day Simple Moving Average. |
| `net_liquidity` | float | Fed Assets - TGA - RRP (in Billions). |
| `liq_slope_20d` | float | 20-day linear regression slope of Net Liquidity. |
| `vix` | float | CBOE Volatility Index. |
| `hy_spread` | float | BofA US High Yield Index Option-Adjusted Spread. |

### M01 Feature Integration
Produced by `generate_m01_features` for consumption by the M01 Return Regressor.

| Column | Range | Description |
| :--- | :--- | :--- |
| `m03_score` | 0.0 - 1.0 | Normalized raw score. |
| `m03_regime_cat` | 0 - 4 | Ordinal category (0=Strong Bear, 4=Strong Bull). |
| `m03_delta_5d` | -1.0 - 1.0 | 5-day score velocity (Score diff / 100). |
| `m03_delta_20d` | -1.0 - 1.0 | 20-day score velocity. |
| `m03_regime_vol` | 0.0 - 1.0 | 10-day rolling standard deviation of score (clipped). |
| `m03_pillar_*` | 0.0 - 1.0 | Normalized individual pillar scores (Trend/Liq/Risk). |

## 4. Implementation Rules (The "Secret Sauce")

### Scoring Pillars
The model uses a weighted sum of three pillars. Weights are configurable in `m03_config.json`.

1.  **Trend Pillar (Default 40%)**
    *   **Logic:** `50 + 50 * tanh(pct_above_sma * 10)`
    *   **Inputs:** SPY vs 200-day SMA.
    *   **Behavior:** S-curve activation. Score > 50 when price > SMA.

2.  **Liquidity Pillar (Default 20-30%)**
    *   **Logic:** `50 + 50 * tanh(slope_pct * 50)`
    *   **Inputs:** Net Liquidity (Fed Assets - TGA - RRP). 10 or 20-day slope.
    *   **Behavior:** S-curve. Positive slope = bullish.
    *   **Lag Handling:** **CRITICAL.** Applies `T+1` shift to macro data to account for FRED publication delays (Wed data released Thu).

3.  **Risk Appetite Pillar (Default 30-40%)**
    *   **Logic:** Linear interpolation of VIX and HY Spread.
    *   **VIX Component (0-50):** Maps `[vix_bull_threshold, vix_extreme_threshold]` to `[50, 0]`.
    *   **Spread Component (0-50):** Maps `[spread_bull_threshold, spread_extreme_threshold]` to `[50, 0]`.
    *   **Optimization:** Uses "tight" VIX thresholds (e.g., 15-30) for faster crash detection.

### Gating Rules
Used to control the trading engine based on the score.
*   **Allow Longs:** Score >= `long_allow_min` (Default: 30).
*   **Reduced Sizing:** Score < `long_reduced_min` (Default: 50).

### Evaluation Targets
*   **Discrimination (Phase 1):**
    *   ROC-AUC >= 0.90
    *   Cohen's D >= 2.0
*   **Calibration (Phase 2):**
    *   Crash Capture Rate (CCR) >= 80% (Capture 80% of Strong Bear days).
    *   False Alarm Rate (FAR) <= 5% (Wrongly flag <= 5% of Strong Bull days).
    *   Reaction Lag <= 7 days (Average time to detect crash).

## 5. Public Interface

### `M03RegimeCalculator`
| Method | Arguments | Returns | Description |
| :--- | :--- | :--- | :--- |
| `calculate` | `as_of_date: str` | `Dict` | Returns full score breakdown (pillars, weights) for a single date. |
| `calculate_history_vectorized` | `start, end, freq` | `DataFrame` | Generates historical scores using vectorized operations (fast). |
| `generate_m01_features` | `start, end` | `DataFrame` | Generates normalized features specifically for M01 model training. |
| `should_gate_signal` | `score` | `Dict` | Returns boolean flags (`allow_longs`, `reduced_sizing`) based on score. |

### `M03Evaluator`
| Method | Arguments | Returns | Description |
| :--- | :--- | :--- | :--- |
| `evaluate` | `start, end` | `Dict` | Runs full backtest against Ground Truth. Returns discrimination and calibration metrics. |
| `calibrate_thresholds` | `ccr_target, far_target` | `Dict` | Calculates optimal category thresholds based on historical distributions. |
