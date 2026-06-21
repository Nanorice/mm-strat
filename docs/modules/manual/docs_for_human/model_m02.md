# Module Passport: M02 Model (Ignition Classifier)

## 1. Overview
**Responsibility:**  
The **M02 Model** (also known as the "Ignition Classifier" or "Loser Detector") is a binary classification model designed to predict the probability of a trade "igniting" (hitting a profit target) versus "failing" (hitting a stop loss) immediately after entry. In production, it functions as a **Loser Detector**, identifying low-quality setups to filter out.

It uses a **Triple Barrier** labeling method (Profit Target / Stop Loss / Time Limit) to create ground truth labels from historical price trajectories.

**Key Dependencies:**
*   **Data Pipeline:** `src.pipeline.DataPipeline` (for hydrating and labeling data)
*   **Triple Barrier Labeler:** `src.triple_barrier_labeler` (for outcome calculation)
*   **Feature Config:** `src.feature_config` (defines `M02_FEATURES`)
*   **Base Trainer:** `src.pipeline.base_trainer.BaseTrainer` (parent class)

## 2. File Structure

| File | Purpose |
| :--- | :--- |
| `model_runner.py` | **CLI Entry Point**. Handles command-line arguments (`python model_runner.py m02`) and orchestrates the training pipeline steps (`scan`, `hydrate`, `label`, `train`). |
| `src/pipeline/m02_trainer.py` | **Core Logic**. Defines the `M02Trainer` class which handles model creation (XGBoost), training (with class weighting), validation, and reporting. Inverts labels to predict "Loser" probability. |
| `src/triple_barrier_labeler.py` | **Labeling Engine**. Applies path-dependent barriers (TP/SL/Time) to trade trajectories to determine outcomes (`TP`, `SL`, `Time`). |
| `src/feature_config.py` | **Configuration**. Defines `M02_FEATURES` (the "Velocity Squad"), a specific subset of features focused on relative strength, volume acceleration, and momentum. |
| `src/pipeline/data_pipeline.py` | **Orchestration**. Manages the flow from `scan` (D1) -> `features` (D2) -> `hydrate` (D2R) -> `label` (D3). |

## 3. Data Schemas

### D3 Dataset (Labeled Training Data)
The training input (`d3`) is a Pandas DataFrame containing features and labels.

| Category | Columns / Description |
| :--- | :--- |
| **Target (y_loser)** | `1` = **Stop Loss Hit** (Loser)<br>`0` = **Profit Target** or **Time Limit** (Success/Neutral) |
| **Outcomes (Raw)** | `outcome` (Enum: `TP`, `SL`, `Time`), `return_at_outcome` (float), `days_to_outcome` (int), `barrier_id` (int) |
| **Features (Velocity Focus)** | **53 Features** (defined in `feature_config.M02_FEATURES`), including:<br>- **Captains:** `RS` (Relative Strength), `Vol_Ratio`, `Alpha011` (VWAP Div), `VCP_Ratio` (Tightness)<br>- **Velocity Squad:** `volume_acceleration` (Surge), `rs_velocity` (Accel), `breakout_momentum`<br>- **Physics (Alphas):** `alpha046` (Slope Accel), `alpha051` (Slope Change), `alpha101` (Body Strength)<br>- **Context:** `Dist_From_52W_High`, `consolidation_duration` |

## 4. Implementation Rules ("The Secret Sauce")

### Triple Barrier Method
Unlike standard fixed-horizon returns, M02 uses path-dependent barriers.
*   **Stop Loss (SL):** `k_sl * ATR` (Default `k_sl=1.0`)
*   **Profit Target (TP):** `MAX(min_tp, k_tp * ATR)`
    *   **Default Constants:** `k_tp=4.0`, `min_tp=0.20` (20%)
    *   *Logic:* Target must be at least 20%, or 4x volatility, whichever is higher.
*   **Time Barrier:** Max holding period `max_time=30` days.

### Loser Detector Logic
*   **Inversion:** The model is trained to predict the **NEGATIVE** class (Losers).
*   **Imbalance Handling:** Uses `scale_pos_weight` in XGBoost to handle the rarity of specific outcomes if needed (though `M02Trainer` calculates class weights dynamically).
*   **Prediction:** Output is `P(Loss)`. A low score means high probability of success (Ignition).

### Magic Numbers & Defaults
*   **Time Limit:** 30 days (Default).
*   **Minimum Target:** 20% (`min_tp = 0.20`).
*   **Risk/Reward:** Target is typically 4x the Stop (`k_tp=4.0` vs `k_sl=1.0`).

## 5. Public Interface

### `src.pipeline.m02_trainer.M02Trainer`
The primary class for interacting with the M02 model.

**Methods:**

*   `__init__(feature_set=None, model_name=None, barrier_params=None)`
    *   Initializes trainer with optional custom config.
    
*   `train(data, tune=False, train_years=3, test_years=1)`
    *   **Input:** `data` (D3 DataFrame).
    *   **Process:** Splits data (TimeGroupKFold), handles class weights, trains XGBoost.
    *   **Returns:** `(model, metrics_df)`
    
*   `save(model, metrics_df)`
    *   Saves artifacts to `models/` directory:
        *   `{model_name}.json` (XGBoost model)
        *   `{model_name}_metrics.csv` (Performance metrics)
        *   `{model_name}_barriers.json` (Barrier params used)
        
*   `generate_report(model, metrics_df, start_date, end_date)`
    *   Creates a detailed Markdown report with confusion matrices and separation plots.

### `src.triple_barrier_labeler.TripleBarrierLabeler`

*   `label_dataset(d2_rehydrated, params, ...)`
    *   **Input:** Multi-day price trajectories (`d2r`).
    *   **Output:** Single-row-per-trade DataFrame (`d3`) with `outcome`, `return`, and `days` columns added.
