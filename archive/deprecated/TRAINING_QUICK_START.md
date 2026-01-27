# SEPA Model Training - Quick Start

## TL;DR

```bash
# 1. Install dependencies
pip install -r requirements_ml.txt

# 2. Verify setup
python test_training_setup.py

# 3. Train model (quick)
python train_sepa_model.py --dataset data/ml/training_dataset_final.parquet

# 4. Train model (optimized)
python train_sepa_model.py \
    --dataset data/ml/training_dataset_final.parquet \
    --optimize \
    --n-trials 50
```

## Implementation Summary

### Your Decisions

| Question | Your Answer | Implementation |
|----------|-------------|----------------|
| **Fold Structure** | Option C: Expanding Window | 2 folds: 2y→1y, 3y→1.9y |
| **Purge Gap** | 60 days | `max(14, avg_trade * 1.25)` |
| **Split On** | Entry Date | Simulates real decisions |
| **Correlation Threshold** | 0.95 | Conservative |
| **Feature Selection** | SHAP | TreeExplainer |
| **Evaluation Metric** | Precision@Top-20% | Ranking optimization |
| **Class Imbalance** | scale_pos_weight | 9:1 ratio |
| **Algorithm** | XGBoost | Industry standard |
| **Hyperparameter Tuning** | Moderate (Optuna) | 50 trials, max_depth ≤ 4 |
| **Output** | Probability Scores | 0.0 - 1.0 ranking |

### Key Features

**Temporal Integrity**:
- ✅ Walk-forward validation (no look-ahead bias)
- ✅ 60-day purge gap (prevents trade overlap)
- ✅ Expanding window (learns from all history)

**Feature Engineering**:
- ✅ Drop 100% missing features (4 features)
- ✅ Correlation filter at 0.95 (removes ~45 pairs)
- ✅ SHAP importance (optional top-N selection)

**Model Training**:
- ✅ XGBoost with scale_pos_weight=9
- ✅ Max depth constrained to 3-4 (prevents overfitting)
- ✅ Precision@Top-20% optimization
- ✅ Early stopping on validation set

**Evaluation**:
- ✅ Precision@k (Top 10%, 20%, 30%)
- ✅ ROC-AUC and PR-AUC
- ✅ Trading simulation (what if we bought top-k?)
- ✅ Baseline comparison (vs unfiltered SEPA)
- ✅ SHAP feature importance

## File Structure

```
quantamental/
├── src/
│   ├── model_preparation.py      # Temporal splitting + feature selection
│   ├── train_model.py             # XGBoost training + Optuna
│   └── evaluate_model.py          # Evaluation + visualization
│
├── train_sepa_model.py            # Master training script
├── test_training_setup.py         # Pre-flight checks
├── requirements_ml.txt            # ML dependencies
│
├── models/                        # Trained models (output)
│   ├── model_fold_1.json
│   ├── model_metadata_fold_1.json
│   ├── model_fold_2.json
│   └── model_metadata_fold_2.json
│
├── evaluation/                    # Evaluation reports (output)
│   ├── evaluation_report.json
│   ├── roc_curve_fold_*.png
│   ├── pr_curve_fold_*.png
│   └── feature_importance_fold_*.png
│
└── training.log                   # Training log (output)
```

## Expected Performance

Based on your dataset (1,694 trades, 9.7% win rate):

| Metric | Baseline (SEPA) | Model (Top 20%) | Improvement |
|--------|-----------------|-----------------|-------------|
| Win Rate | 9.7% | ~20-25% | **+117%** |
| Avg Return | 1.97% | ~3-4% | **+62%** |
| Precision@Top-20% | 9.7% | ~20-25% | **2.2x** |

**Note**: Actual performance depends on data quality and market regime.

## Next Steps After Training

### 1. Review Results

```bash
# View evaluation report
cat evaluation/evaluation_report.json

# Check summary
grep -A 10 "EVALUATION SUMMARY" training.log
```

### 2. Deploy Model

```python
# Load trained model
import xgboost as xgb
model = xgb.Booster()
model.load_model('models/model_fold_2.json')

# Predict on new candidates
probabilities = model.predict(new_data)

# Rank and select top 5
top_5 = new_data.nlargest(5, 'probability')
```

### 3. Integrate with Scanner

```python
# Add to scanner_v0.py
from src.train_model import SEPAModelTrainer

# After SEPA screening
qualified_stocks = strategy.batch_scan_universe(...)

# Score with ML model
trainer = SEPAModelTrainer()
trainer.load_model('models/model_fold_2.json')
scores = trainer.predict_proba(qualified_stocks)

# Filter: Only buy if score > 0.6
buy_list = qualified_stocks[scores > 0.6]
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| ModuleNotFoundError: xgboost | `pip install xgboost optuna shap` |
| No positive samples | Adjust fold dates or check data quality |
| Training too slow | Reduce `--n-trials` or skip `--optimize` |
| Model overfitting | Check `max_depth` and `--top-n` features |

## Documentation

- **Full Guide**: [docs/MODEL_TRAINING_GUIDE.md](docs/MODEL_TRAINING_GUIDE.md)
- **Architecture**: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- **Dataset A**: [docs/DATASET_A_GUIDE.md](docs/DATASET_A_GUIDE.md)
- **Dataset B**: [docs/DATASET_B_GUIDE.md](docs/DATASET_B_GUIDE.md)

## Contact

For questions or issues, review:
1. `training.log` - Detailed training logs
2. `evaluation/evaluation_report.json` - Performance metrics
3. [docs/MODEL_TRAINING_GUIDE.md](docs/MODEL_TRAINING_GUIDE.md) - Comprehensive guide
