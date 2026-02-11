# Implementation Plan: D1/D2/D2R Updates & M01 Ranker

This plan outlines the changes required to update the SEPA screening criteria, refine the target variable (`log_hybrid`) logic, upgrade the M01 model to a Learning-to-Rank (LTR) architecture, and enhance reporting.

## Status: PARTIALLY COMPLETE

### Completed Changes

| Item | Status | Details |
|------|--------|---------|
| Target Variable (Option E) | DONE | Default changed to `log_hybrid` in M01Trainer |
| Save D2 with Scores | DONE | `save_d2_with_scores()` method added |
| Detailed Decile Stats | DONE | Added to `generate_report()` |
| File Management | DONE | Model-specific folders: `models/{model_name}/` |
| Report Filename | DONE | Format: `model_report_{name}_{YYMMDD}.md` |

### Pending Changes

| Item | Status | Details |
|------|--------|---------|
| RS Threshold (D1) | PENDING | Change from 70th to 50th percentile |
| Pairwise Ranking | PENDING | Switch to `rank:pairwise` objective |
| Dashboard Updates | PENDING | Point to new model folder structure |

---

## Next Session: Action Items

### 1. Retrain Models with New File Structure

```bash
# Activate environment
C:/Users/Hang/PycharmProjects/quantamental/.venv/Scripts/Activate.ps1

# Train M01 with log_hybrid target (new default)
python model_runner.py train --model m01 --report

# This will create:
# models/m01/
#   ├── model.json
#   ├── config.json
#   ├── model_report_m01_YYMMDD.md
#   ├── feature_importance.csv
#   ├── preprocessing_config.json
#   ├── d1_analysis.json
#   ├── d2_scored.parquet
#   └── calibrator.pkl (if calibrate() called)
```

### 2. Update Dashboard to Use New Paths

Files to update:
- `dashboard.py` - Update paths to read from `models/{model_name}/`
- Look for hardcoded paths like:
  - `models/m01.json` → `models/m01/model.json`
  - `models/m01_config.json` → `models/m01/config.json`
  - `models/d1_analysis.json` → `models/m01/d1_analysis.json`

### 3. Verify log_hybrid Target

After training, verify in the report:
- Check "Decile Performance Analysis" section
- Confirm losers have negative targets (not MFE)
- Look for "Survivor Rate by Decile" table

---

## Proposed Changes (Original Plan)

### 1. SEPA Criteria Update (D1)

Relax the RS Rating criteria from top 30% to top 50%.

#### [MODIFY] [src/vectorized_screening.py](src/vectorized_screening.py)
*   **Location**: `batch_screen_universe` method (Phase 1).
*   **Change**: Update percentile calculation from `70` to `50`.

```python
# Current
rs_threshold = np.percentile(rs_values, 70)

# New
rs_threshold = np.percentile(rs_values, 50) # Top 50%
```

### 2. Target Variable (`log_hybrid`) - COMPLETE

**Default changed to Option E (Log-Hybrid)** "The Golden Target".

**Implementation:**
- [src/pipeline/m01_trainer.py](src/pipeline/m01_trainer.py):
  - `get_target_col()` returns `'log_hybrid'`
  - `train()` default parameter: `target='log_hybrid'`
  - Added `_compute_log_hybrid_target()` method

**Logic (from `src/evaluation/targets.py`):**
*   **Survivors**: `y = sign(MFE) * log(1 + |MFE|)`
*   **Losers**: `y = sign(Loss) * log(1 + |Loss|)`
    *   Loss is defined by the *first* trigger hit:
        1.  **Structural Stop**: Close < Entry * (1 - 10%)
        2.  **Technical Stop**: Close < (SMA_50 - 1.0*ATR)

### 3. Model Training Enhancements (M01) - PENDING

Transition M01 from Regression to Pairwise Ranking with focus on super-performers.

#### [MODIFY] [src/pipeline/m01_trainer.py](src/pipeline/m01_trainer.py)
*   **Change A: Pairwise Ranking**:
    *   Switch XGBoost objective to `rank:pairwise`.
    *   Sort data by `date`.
    *   Calculate and pass `group` parameter (counts per date) to XGBoost.
    *   Metric: `ndcg`.
*   **Change B: Sample Weights**:
    *   Apply `sample_weight` to emphasize "Super Performers" (e.g., `y_max > 20%`).

### 4. Save Model Predictions - COMPLETE

**New method:** `save_d2_with_scores(model, data, suffix=None)`

**Output:** `models/{model_name}/d2_scored.parquet`

**Columns added:**
- `m01_score`: Raw model predictions
- `m01_score_calibrated`: Calibrated predictions (if calibrator available)
- `m01_decile`: Decile assignment (1-10)

### 5. Enhanced Model Report - COMPLETE

**New sections in report:**
1. **Detailed Decile Statistics**: Mean, Std, Min, P1, P5, P25, P50, P75, P95, P99, Max
2. **Survivor Rate by Decile**: Survivor Rate, Crash Rate, Avg MFE, Avg MAE

### 6. File Management - COMPLETE

**New folder structure:**
```
models/
├── m01/
│   ├── model.json
│   ├── config.json
│   ├── model_report_m01_260209.md
│   ├── feature_importance.csv
│   ├── preprocessing_config.json
│   ├── d1_analysis.json
│   ├── d2_scored.parquet
│   └── calibrator.pkl
├── m01_v2/
│   └── ...
```

---

## Verification Plan

### After Retraining

1. **Check folder structure**: `ls models/m01/`
2. **Verify target type in logs**: Look for "Using log_hybrid target"
3. **Inspect report**: Open `models/m01/model_report_m01_*.md`
   - Check "Detailed Decile Statistics" table
   - Verify losers show negative mean returns in bottom deciles
4. **Load scored data**:
   ```python
   import pandas as pd
   d2 = pd.read_parquet('models/m01/d2_scored.parquet')
   print(d2[['ticker', 'date', 'm01_score', 'm01_decile']].head())
   ```

### Dashboard Verification

1. Run dashboard: `python dashboard.py`
2. Verify EDA tab loads D1 analysis from correct path
3. Verify M01 evaluation metrics display correctly

---

**Dependencies**:
- `src/vectorized_screening.py`
- `src/pipeline/m01_trainer.py`
- `src/pipeline/base_trainer.py`
- `src/evaluation/targets.py`
- `dashboard.py`
