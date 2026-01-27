# Survivor Model Implementation Plan

## Executive Summary

**Objective:** Decouple downside risk from M01 by training it only on "survivor" trades (those that don't hit structural stops).

**Key Innovation:** Instead of training M01 on mixed outcomes (crashes + gains), train it to predict **upside potential conditional on survival**.

---

## Conceptual Framework

### Current Problem
- M01 trained on `return_pct` learns to predict: "Will it crash?" + "How high will it go?"
- These are fundamentally different questions requiring different features
- Fundamental features (pe_ratio, operating_margin) predict "quality" (survival), not velocity (upside)

### Survivor Model Solution
**Two-stage prediction system:**

1. **M01_3BAR (Ignition Engine):** Predicts survival (TP vs SL outcome)
   - Features: Velocity, momentum, breakout patterns
   - Question: "Will it explode or crash in 30 days?"

2. **M01 (Survivor Model):** Predicts upside potential (conditional on survival)
   - Trained ONLY on survivors (trades that didn't hit -2×ATR stop)
   - Question: "How high will it go IF it doesn't crash?"

3. **Portfolio Integration:**
   - M01_3BAR filters (score > threshold) → Only high-ignition candidates
   - M01 ranks survivors → Top predicted returns get highest allocation

---

## Mathematical Definition

### y_max Calculation

```python
# For each trade in d2_features:
structural_stop = -2.0 * nATR  # Entry-day ATR-based stop

y_max = {
    MAE,  if MAE <= structural_stop  # Crashed: y_max = drawdown (negative)
    MFE,  otherwise                   # Survived: y_max = max upside (positive)
}

is_survivor = (MAE > structural_stop)  # Boolean flag
```

### Why This Works

1. **Structural Stop = -2×ATR**
   - Reasonable mechanical stop for volatility-adjusted risk
   - Aligns with Phase 1 optimized barriers (k_sl = 1.0 for 30-day horizon)
   - For 120-day horizon, -2×ATR gives trades room to breathe

2. **MAE = Max Adverse Excursion**
   - Worst intraday drawdown during the trade
   - Answers: "Would we have been stopped out?"

3. **MFE = Max Favorable Excursion**
   - Best intraday high during the trade
   - Answers: "What was the max potential?"

4. **Conditional Training**
   - Survivors: Train on upside (MFE)
   - Crashes: Excluded from M01 training (handled by M01_3BAR)

---

## Implementation Steps

### Step 1: Add y_max to D2 Feature Generation

**File:** `model_trainer.py` (or create new `src/feature_enrichment.py`)

**Location:** After D2 features are generated, before model training

```python
def enrich_d2_with_ymax(
    d2_features: pd.DataFrame,
    d2_rehydrated: pd.DataFrame,
    structural_stop_multiplier: float = 2.0
) -> pd.DataFrame:
    """
    Enrich d2_features with y_max column using structural stop logic.

    Args:
        d2_features: Snapshot dataset (one row per trade)
        d2_rehydrated: Trajectory dataset (multiple rows per trade)
        structural_stop_multiplier: Stop loss ATR multiplier (default: 2.0)

    Returns:
        d2_features with added columns:
        - y_max: Max potential (MFE) or crash depth (MAE)
        - MAE: Max adverse excursion
        - MFE: Max favorable excursion
        - is_survivor: Boolean flag (True if didn't hit stop)
    """
    # Calculate MAE/MFE for each trade
    mae_mfe_results = []

    for trade_id, group in d2_rehydrated.groupby('trade_id'):
        # Entry price (day 0)
        entry_rows = group[group['day_in_trade'] == 0]
        if len(entry_rows) == 0:
            continue

        entry_price = entry_rows['Close'].iloc[0]

        # MFE: Highest high during trade
        highest = group['High'].max()
        MFE = ((highest - entry_price) / entry_price) * 100

        # MAE: Lowest low during trade
        lowest = group['Low'].min()
        MAE = ((lowest - entry_price) / entry_price) * 100

        mae_mfe_results.append({
            'trade_id': trade_id,
            'MFE': MFE,
            'MAE': MAE
        })

    mae_mfe_df = pd.DataFrame(mae_mfe_results)

    # Merge with d2_features
    if 'trade_id' not in d2_features.columns:
        d2_features['trade_id'] = d2_features.index + 1

    df = d2_features.merge(mae_mfe_df, on='trade_id', how='left')

    # Calculate structural stop and y_max
    df['structural_stop'] = -structural_stop_multiplier * df['nATR']
    df['is_survivor'] = df['MAE'] > df['structural_stop']

    df['y_max'] = np.where(
        df['is_survivor'],
        df['MFE'],  # Survivor: max potential
        df['MAE']   # Crashed: drawdown (negative)
    )

    # Drop intermediate columns (optional, keep for debugging)
    # df = df.drop(columns=['MFE', 'MAE', 'structural_stop'])

    logger.info(f"Enriched d2_features with y_max column")
    logger.info(f"  Total trades: {len(df):,}")
    logger.info(f"  Survivors: {df['is_survivor'].sum():,} ({df['is_survivor'].mean():.1%})")
    logger.info(f"  Crashed: {(~df['is_survivor']).sum():,} ({(~df['is_survivor']).mean():.1%})")
    logger.info(f"  Mean y_max (all): {df['y_max'].mean():.2f}%")
    logger.info(f"  Mean y_max (survivors): {df[df['is_survivor']]['y_max'].mean():.2f}%")

    return df
```

**Integration Point:** Call after `generate_d2_features()` in the D2 pipeline:

```python
# In model_trainer.py, step D2
def generate_d2_features(...):
    # ... existing code ...
    d2_features = feature_snapshot_generator.generate_snapshots(d2_rehydrated)

    # NEW: Enrich with y_max
    d2_features = enrich_d2_with_ymax(d2_features, d2_rehydrated)

    return d2_features
```

---

### Step 2: Add --survivor-model Flag to model_trainer.py

**Location:** `model_trainer.py` CLI arguments and `train_fixed_horizon_model()` function

#### CLI Argument

```python
# In argparse setup (around line 2300-2400)
parser.add_argument(
    '--survivor-model',
    action='store_true',
    help='Train M01 as survivor model (exclude crashed trades with y_max < 0)'
)

parser.add_argument(
    '--survivor-stop-multiplier',
    type=float,
    default=2.0,
    help='Structural stop multiplier for survivor model (default: 2.0 = -2×ATR)'
)
```

#### Training Function Update

```python
def train_fixed_horizon_model(
    d2_path: str,
    model_name: str = 'M01',
    horizon_days: int = 120,
    n_jobs: int = -1,
    tune: bool = False,
    trials: int = 100,
    survivor_model: bool = False,  # NEW
    survivor_stop_multiplier: float = 2.0  # NEW
) -> Tuple[xgb.XGBRegressor, Dict]:
    """
    Train M01 fixed-horizon return regressor.

    Args:
        d2_path: Path to d2_features.parquet
        model_name: Model identifier (default: 'M01')
        horizon_days: Training horizon
        n_jobs: Parallel workers
        tune: Enable hyperparameter tuning
        trials: Number of tuning trials
        survivor_model: If True, train only on survivors (y_max > 0)
        survivor_stop_multiplier: ATR multiplier for structural stop (default: 2.0)

    Returns:
        Trained XGBoost model and metadata
    """
    logger.info(f"Training {model_name} model ({horizon_days}d horizon)")
    if survivor_model:
        logger.info(f"  🛡️ SURVIVOR MODEL: Training only on trades with y_max > 0")
        logger.info(f"  Structural stop: -{survivor_stop_multiplier:.1f}×ATR")

    # Load data
    d2 = pd.read_parquet(d2_path)

    # Verify y_max column exists
    if 'y_max' not in d2.columns:
        raise ValueError(
            "y_max column not found in d2_features. "
            "Run d2 generation with y_max enrichment first."
        )

    # Filter survivors if survivor model
    if survivor_model:
        original_len = len(d2)
        d2 = d2[d2['y_max'] > 0].copy()
        removed = original_len - len(d2)
        logger.info(f"  Removed {removed:,} crashed trades ({removed/original_len:.1%})")
        logger.info(f"  Training on {len(d2):,} survivors")

    # Feature columns (use M01_FEATURES from feature_config)
    feature_cols = get_model_features('M01')

    # Walk-forward validation setup
    splits = create_walk_forward_splits(d2, n_splits=3)

    fold_results = []
    oof_predictions = []

    for fold_idx, (train_idx, val_idx) in enumerate(splits):
        logger.info(f"Fold {fold_idx + 1}/{len(splits)}")

        train_data = d2.iloc[train_idx]
        val_data = d2.iloc[val_idx]

        # Filter survivors per-fold (if survivor model)
        if survivor_model:
            train_data = train_data[train_data['y_max'] > 0]
            val_data = val_data[val_data['y_max'] > 0]

        # Use y_max as label (instead of return_pct)
        X_train = train_data[feature_cols]
        y_train = train_data['y_max']  # NEW: Use y_max instead of return_pct

        X_val = val_data[feature_cols]
        y_val = val_data['y_max']

        # Train XGBoost
        model = xgb.XGBRegressor(
            objective='reg:squarederror',
            n_estimators=500,
            learning_rate=0.05,
            max_depth=6,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42 + fold_idx,
            n_jobs=n_jobs
        )

        model.fit(
            X_train, y_train,
            eval_set=[(X_val, y_val)],
            early_stopping_rounds=50,
            verbose=False
        )

        # Evaluate
        y_pred = model.predict(X_val)
        mae = mean_absolute_error(y_val, y_pred)
        rmse = np.sqrt(mean_squared_error(y_val, y_pred))
        r2 = r2_score(y_val, y_pred)

        logger.info(f"  MAE: {mae:.2f}%, RMSE: {rmse:.2f}%, R²: {r2:.3f}")

        fold_results.append({
            'fold': fold_idx,
            'mae': mae,
            'rmse': rmse,
            'r2': r2
        })

        oof_predictions.append(pd.DataFrame({
            'trade_id': val_data['trade_id'],
            'y_true': y_val,
            'y_pred': y_pred,
            'fold': fold_idx
        }))

    # Final model: Train on all data
    if survivor_model:
        d2 = d2[d2['y_max'] > 0]

    X_full = d2[feature_cols]
    y_full = d2['y_max']

    final_model = xgb.XGBRegressor(
        objective='reg:squarederror',
        n_estimators=500,
        learning_rate=0.05,
        max_depth=6,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        n_jobs=n_jobs
    )

    final_model.fit(X_full, y_full, verbose=False)

    # Save model and metadata
    model_suffix = '_survivor' if survivor_model else ''
    model_path = f'models/model_{model_name.lower()}{model_suffix}.json'
    final_model.save_model(model_path)

    metadata = {
        'model_name': model_name,
        'horizon_days': horizon_days,
        'survivor_model': survivor_model,
        'structural_stop_multiplier': survivor_stop_multiplier,
        'n_features': len(feature_cols),
        'n_train_samples': len(d2),
        'fold_results': fold_results,
        'mean_mae': np.mean([r['mae'] for r in fold_results]),
        'mean_rmse': np.mean([r['rmse'] for r in fold_results]),
        'mean_r2': np.mean([r['r2'] for r in fold_results])
    }

    logger.info(f"✅ Model saved: {model_path}")
    logger.info(f"   Mean MAE: {metadata['mean_mae']:.2f}%")
    logger.info(f"   Mean R²: {metadata['mean_r2']:.3f}")

    return final_model, metadata
```

---

### Step 3: Update CLI Command Flow

```python
# In main() function, handle survivor model flag
if args.survivor_model:
    logger.info("🛡️ SURVIVOR MODEL MODE ENABLED")
    logger.info(f"   Structural stop: -{args.survivor_stop_multiplier}×ATR")

# When training M01:
if 'd2train' in steps or 'train' in steps:
    train_fixed_horizon_model(
        d2_path=f'data/ml/d2_features.parquet',
        model_name='M01',
        horizon_days=args.horizon,
        n_jobs=args.n_jobs,
        tune=args.tune,
        trials=args.trials,
        survivor_model=args.survivor_model,  # NEW
        survivor_stop_multiplier=args.survivor_stop_multiplier  # NEW
    )
```

---

## Usage

### Step 1: Regenerate D2 with y_max

```bash
# Activate environment
C:/Users/Hang/PycharmProjects/quantamental/.venv/Scripts/Activate.ps1

# Regenerate D2 features with y_max column
python model_trainer.py --steps d2rh d2 --horizon 120
```

Expected output:
```
✅ Enriched d2_features with y_max column
   Total trades: 9,261
   Survivors: 7,845 (84.7%)
   Crashed: 1,416 (15.3%)
   Mean y_max (all): 12.3%
   Mean y_max (survivors): 16.7%
```

### Step 2: Validate in Notebook

Run [notebooks/Comprehensive_Model_EDA.ipynb](../notebooks/Comprehensive_Model_EDA.ipynb) Section 1.5:
- Verify crash rate (~15-20% expected)
- Check survivor y_max distribution (should be all positive)
- Validate -2×ATR threshold is reasonable

### Step 3: Train Baseline M01 (for comparison)

```bash
# Train normal M01 on return_pct
python model_trainer.py --steps d2train --horizon 120
```

### Step 4: Train Survivor M01

```bash
# Train survivor M01 on y_max (survivors only)
python model_trainer.py --steps d2train --horizon 120 --survivor-model
```

Expected output:
```
🛡️ SURVIVOR MODEL MODE ENABLED
   Structural stop: -2.0×ATR
   Removed 1,416 crashed trades (15.3%)
   Training on 7,845 survivors
✅ Model saved: models/model_m01_survivor.json
   Mean MAE: 8.2%
   Mean R²: 0.42
```

### Step 5: Compare Models

Create comparison report:
```python
# In model evaluation
baseline = load_model('models/model_m01.json')
survivor = load_model('models/model_m01_survivor.json')

# Compare predictions on same test set
# Expected: Survivor model has higher predicted returns (no crashes in training)
```

---

## Expected Results

### Baseline M01 (Trained on return_pct)
- Predicts mix of crashes and gains
- Mean prediction: ~8-10% (average of all trades)
- Lower variance (compressed by crashes)
- R² ~0.35-0.40

### Survivor M01 (Trained on y_max, survivors only)
- Predicts upside potential conditional on survival
- Mean prediction: ~15-20% (survivor average)
- Higher variance (no crash compression)
- R² ~0.40-0.45 (cleaner signal)

### Portfolio Impact
- **Filter:** M01_3BAR score > threshold (e.g., 0.7)
- **Rank:** Survivor M01 predictions (top decile)
- **Expected:** Higher returns due to:
  1. M01_3BAR removes crashes
  2. Survivor M01 ranks upside potential accurately

---

## Concerns & Mitigations

### Concern 1: Sample Selection Bias
**Problem:** Training only on survivors creates optimistic predictions.

**Mitigation:**
- This is **intentional** - M01_3BAR handles crash filtering
- Document clearly: "Predictions are conditional on survival"
- Use M01_3BAR + Survivor M01 together (two-stage system)

### Concern 2: -2×ATR May Be Wrong Threshold
**Risk:** Too tight = removes too many trades, too loose = doesn't remove crashes

**Mitigation:**
- Validate in EDA notebook (Section 1.5)
- Make it a parameter: `--survivor-stop-multiplier`
- Test sensitivity: 1.5×, 2.0×, 2.5× ATR

### Concern 3: Walk-Forward Validation Leakage
**Risk:** Using future MAE/MFE to determine survivors

**Mitigation:**
- MAE/MFE calculated from **same horizon** as return_pct (no leakage)
- Survivors determined per-fold independently
- Entry-day features only (no future information)

---

## Success Criteria

### Phase 1: Data Validation
- ✅ y_max column added to d2_features
- ✅ Crash rate 10-20% (reasonable threshold)
- ✅ Survivor y_max all positive
- ✅ No data leakage (MAE/MFE from same horizon as return_pct)

### Phase 2: Model Training
- ✅ Survivor M01 trains successfully
- ✅ Mean prediction > baseline (higher because no crashes)
- ✅ R² comparable or better than baseline

### Phase 3: Portfolio Integration
- ✅ M01_3BAR + Survivor M01 pipeline works
- ✅ Higher backtest returns vs baseline M01
- ✅ Lower drawdowns (M01_3BAR filters crashes)

---

## Next Actions

1. ✅ **Run EDA Notebook Section 1.5** - Validate crash rate and y_max distribution
2. ⬜ **Implement `enrich_d2_with_ymax()` function** in model_trainer.py
3. ⬜ **Add `--survivor-model` flag** to CLI
4. ⬜ **Regenerate D2 features** with y_max column
5. ⬜ **Train Survivor M01** and compare with baseline
6. ⬜ **Backtest** two-stage system (M01_3BAR + Survivor M01)

---

**Author:** Claude Code
**Date:** 2026-01-23
**Status:** Implementation Ready
**Recommended Approach:** YES - Cleaner than dual-label approach, aligns with portfolio reality
