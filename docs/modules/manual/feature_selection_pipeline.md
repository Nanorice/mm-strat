# Feature Selection & M01 Training Pipeline

**Last Updated:** 2026-01-30

---

## Overview

This document describes the complete pipeline for:
1. **Feature Selection** - Multi-pillar evaluation using the Quant-Standard framework
2. **Target Engineering** - Choosing the optimal training target (log_space winner)
3. **Model Training** - Training M01 with selected features and target
4. **Production Deployment** - Safe workflow to avoid overwriting models

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    QUANT-STANDARD FEATURE EVALUATOR                         │
└─────────────────────────────────────────────────────────────────────────────┘

  All Numeric Columns                           Final Feature Set
  (d2_features)                                 (M01_FEATURES)
           │                                              ▲
           ▼                                              │
  ┌─────────────────────────────────────────────────────────────────────┐
  │  PILLAR 1: DISTRIBUTIONAL HEALTH                                    │
  │  ├─ ADF Stationarity Test (reject non-stationary)                   │
  │  ├─ Kurtosis Check (flag extreme fat tails)                         │
  │  └─ Missingness Analysis (systematic vs random)                     │
  └─────────────────────────────────────────────────────────────────────┘
           │
           ▼
  ┌─────────────────────────────────────────────────────────────────────┐
  │  PILLAR 2: PREDICTIVE POWER                                         │
  │  ├─ Information Coefficient (Spearman rank correlation)             │
  │  ├─ KS Discrimination (existing, Q1 vs Q4)                          │
  │  ├─ Mutual Information (non-linear capture)                         │
  │  └─ Decile Monotonicity (strict increase/decrease check)            │
  └─────────────────────────────────────────────────────────────────────┘
           │
           ▼
  ┌─────────────────────────────────────────────────────────────────────┐
  │  PILLAR 3: TEMPORAL STABILITY                                       │
  │  ├─ IC Stability (IC_mean / IC_std across years)                    │
  │  ├─ PSI (Population Stability Index, drift detection)               │
  │  └─ Per-Year IC Breakdown (identify regime-dependent features)      │
  └─────────────────────────────────────────────────────────────────────┘
           │
           ▼
  ┌─────────────────────────────────────────────────────────────────────┐
  │  PILLAR 4: INTERACTION (enhanced correlation handling)              │
  │  ├─ Correlation Clusters (hierarchical grouping)                    │
  │  └─ Intelligent Pruning (keep highest IC_Stability in cluster)      │
  └─────────────────────────────────────────────────────────────────────┘
           │
           ▼
  ┌─────────────────────────────────────────────────────────────────────┐
  │  COMPOSITE SCORING & REPORT                                         │
  │  ├─ Leaderboard (weighted: 40% IC + 30% Stability + 30% KS)         │
  │  ├─ Deep Dive: Monotonicity plots per feature                       │
  │  ├─ Stability Analysis: Per-year breakdown                          │
  │  └─ Cluster Recommendations: "Keep X, drop Y"                       │
  └─────────────────────────────────────────────────────────────────────┘


┌─────────────────────────────────────────────────────────────────────────────┐
│                         M01 TRAINING PIPELINE                               │
└─────────────────────────────────────────────────────────────────────────────┘

  M01_FEATURES              D2 Features Dataset        D2R Rehydrated Data
  (feature_config.py)       (data/ml/d2_features)      (data/ml/d2r_sepa)
           │                       │                          │
           └───────────────────────┼──────────────────────────┘
                                   │
                                   ▼
                    ┌─────────────────────────────┐
                    │     TargetEngineer          │
                    │     (src/evaluation/        │
                    │      targets.py)            │
                    │                             │
                    │  Options:                   │
                    │  A. return_pct (baseline)   │
                    │  B. hybrid_floor            │
                    │  C. risk_adjusted           │
                    │  D. log_space  ◄── WINNER   │
                    │  E. log_hybrid              │
                    └─────────────────────────────┘
                                   │
                                   ▼
                    ┌─────────────────────────────┐
                    │     M01Trainer              │
                    │     (src/pipeline/          │
                    │      m01_trainer.py)        │
                    │                             │
                    │  Walk-Forward Validation    │
                    │  3yr train / 1yr test       │
                    └─────────────────────────────┘
                                   │
                                   ▼
                    ┌─────────────────────────────┐
                    │     Output Files            │
                    │                             │
                    │  models/m01.json            │
                    │  models/m01_config.json     │
                    │  models/m01_calibration.json│
                    │  models/feature_importance  │
                    │        _m01.csv             │
                    └─────────────────────────────┘
```

---

## CLI Commands

### 1. Feature Selection (Full 4-Pillar Analysis - Default)

```bash
# Run full quant-standard evaluation
python model_runner.py workflow --steps load eda select

# With custom thresholds
python model_runner.py workflow --steps load eda select --ks-threshold 0.10 --correlation-threshold 0.7
```

**Output:** `models/eda_report.md` with:
- Feature leaderboard with composite scores
- Monotonicity deep dive with ASCII bar charts
- Per-year IC stability analysis
- Correlation cluster recommendations
- Distributional warnings

### 2. Feature Selection (Fast KS-Only Mode)

```bash
# Skip 4-pillar analysis for quick iterations
python model_runner.py workflow --steps load eda select --fast-eda
```

**Output:** `models/eda_report.md` (legacy KS-only format)

### 3. M01 Training (Production)

```bash
# Train with log_space target (default, recommended)
python model_runner.py m01 --start 2018-01-01 --end 2023-12-31 --report

# Explicit target specification
python model_runner.py m01 --target log_space --report

# With hyperparameter tuning (slower)
python model_runner.py m01 --tune --report
```

**Output:** `models/m01.json`, `models/m01_config.json`, `models/model_report_M01_*.md`

### 4. Ablation Study (Compare Targets)

```bash
# Run full ablation study comparing all 5 target types
python scripts/run_m01_ablation_study.py --start 2018-01-01 --end 2023-12-31
```

**Output:** Comparison table showing IC, Edge, Edge Sharpe for each target type

---

## Key Files

| File | Purpose |
|------|---------|
| `model_runner.py` | CLI entry point for all ML commands |
| `src/pipeline/m01_workflow.py` | Automated workflow orchestrator |
| `src/pipeline/m01_trainer.py` | M01 training logic with walk-forward validation |
| `src/evaluation/feature_screener.py` | Feature selection pipeline (KS + Quant-Standard) |
| `src/evaluation/feature_analyzer.py` | 4-pillar analysis engine |
| `src/evaluation/targets.py` | Target engineering (log_space, hybrid_floor, etc.) |
| `src/feature_config.py` | Feature lists (M01_FEATURES, M01_CANDIDATE_FEATURES) |
| `scripts/run_m01_ablation_study.py` | Ablation study comparing target types |

---

## Feature Screening Pipeline

### Pipeline Modes

**Quant-Standard (Default):** Full 4-pillar analysis with composite scoring
**Fast KS-Only:** Legacy 3-stage pipeline for quick iterations (`--fast-eda`)

### Quant-Standard 4-Pillar Analysis

#### Pillar 1: Distributional Health
| Test | Method | Pass Criteria |
|------|--------|---------------|
| Stationarity | ADF test | p-value < 0.05 (warning only) |
| Kurtosis | Excess kurtosis | Flag if > 10 (extreme fat tails) |
| Missingness | Pattern analysis | Flag if > 10% and systematic |

#### Pillar 2: Predictive Power
| Test | Method | Interpretation |
|------|--------|----------------|
| IC | Spearman rank correlation | Higher = better linear prediction |
| KS | Q1 vs Q4 discrimination | Higher = better separation |
| Mutual Info | sklearn MI regression | Captures non-linear relationships |
| Monotonicity | Decile mean returns | Identifies linear_pos, linear_neg, kinked signals |

#### Pillar 3: Temporal Stability
| Test | Method | Interpretation |
|------|--------|----------------|
| IC Stability | IC_mean / IC_std across years | Higher = more consistent |
| PSI | Population Stability Index | < 0.1 stable, > 0.25 drift |
| Regime Flag | IC variance check | Flags features with inconsistent IC |

#### Pillar 4: Interaction
| Step | Method | Result |
|------|--------|--------|
| Clustering | Hierarchical (|r| >= 0.7) | Groups correlated features |
| Pruning | IC Stability tie-breaker | Keep highest stability in cluster |

### Composite Scoring

**Formula:** `Composite = 0.4 × IC + 0.3 × Stability + 0.3 × KS`

All components normalized to 0-1 scale before weighting.

### Legacy KS-Only Pipeline (--fast-eda)

3-stage pipeline for quick iterations:

1. **Pre-Filter:** Remove raw columns (prices, volumes, lag features)
2. **KS Test:** Q1 vs Q4 discrimination (KS >= threshold, p < 0.05)
3. **Correlation:** Remove |r| >= 0.9 (keep higher KS)

---

## Target Engineering

**Winner from Ablation Study:** `log_space` (Option D)

| Target | Formula | IC | Edge Sharpe | Notes |
|--------|---------|----|----|-------|
| return_pct | Raw SEPA return % | 0.28 | 2.1 | Baseline |
| hybrid_floor | MFE for winners, capped loss for losers | 0.31 | 3.2 | Reduces outlier impact |
| risk_adjusted | MFE / ATR | 0.25 | 1.8 | Normalizes by volatility |
| **log_space** | sign(MFE) x log(1 + \|MFE\|) | **0.34** | **5.5** | **Recommended** |
| log_hybrid | log transform with realized stop losses | 0.32 | 4.8 | Most realistic |

**Why log_space wins:**
- Compresses outlier returns (reduces tail dominance)
- No filtering (keeps all trades)
- Best IC and Edge Sharpe in ablation study

**Class:** `TargetEngineer` in `src/evaluation/targets.py`

---

## Production Workflow (Safe Deployment)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  STEP 1: EDA Screening                                                      │
│  python model_runner.py workflow --steps load eda select                    │
│                                                                             │
│  Output: models/eda_report.md                                               │
│  [NO MODEL SAVED]                                                           │
└─────────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  STEP 2: User Review                                                        │
│                                                                             │
│  1. Open models/eda_report.md                                               │
│  2. Review passed/failed features                                           │
│  3. Copy approved features to src/feature_config.py → M01_FEATURES          │
└─────────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  STEP 3: Train Production Model                                             │
│  python model_runner.py m01 --target log_space --report                     │
│                                                                             │
│  Output: models/m01.json (overwrites production model)                      │
└─────────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  STEP 4: Verify                                                             │
│  python daily_scanner.py --ml                                               │
│                                                                             │
│  Confirm scanner runs without errors                                        │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Why this matters:** The workflow `save_model=False` by default prevents accidental overwrites during experimentation.

---

## Feature Preprocessing (Fit/Transform Pattern)

**New in 2026-01-30:** The preprocessing step ensures consistent feature transformation between training and inference.

### Architecture

```
Training:  D2 → clean → fit(preprocessor) → transform → save config → train
Inference: candidates → load config → transform → score
```

### FeaturePreprocessor Class

**File:** `src/feature_preprocessor.py`

```python
from src.feature_preprocessor import FeaturePreprocessor

# Training: fit and save
preprocessor = FeaturePreprocessor()
preprocessor.fit(df, feature_cols, target='return_pct')
df = preprocessor.transform(df)
preprocessor.save('models/preprocessing_config.json')

# Inference: load and transform
preprocessor = FeaturePreprocessor.load('models/preprocessing_config.json')
df = preprocessor.transform(df)
```

### Transform Decision Tree

| Category | Features | Transform | New Name |
|----------|----------|-----------|----------|
| BOUNDED | `RSI_14`, `operating_margin` | Winsorize | Same |
| EXPLOSIVE | `volume_acceleration`, `Vol_Ratio` | Log | `log_volume_acceleration` |
| STANDARD | `Price_vs_SMA_50`, `Slope_*` | Winsorize | Same |
| UNKNOWN | Any other feature | TAR-based* | Depends on TAR |

*TAR (Tail Alpha Ratio) > 1.2 → Log transform, else Winsorize

### Integration Points

| File | Function | What Happens |
|------|----------|--------------|
| `model_trainer.py` | `train_model_walk_forward()` | Fit → transform → save to `models/preprocessing_config.json` |
| `daily_scanner.py` | `run_daily_scanner()` | Load config → transform before scoring |

### Config File Format

`models/preprocessing_config.json`:
```json
{
  "features": {
    "volume_acceleration": {"transform": "log", "category": "explosive"},
    "RSI_14": {"transform": "winsorize", "lower_bound": 18.5, "upper_bound": 82.3}
  },
  "fitted_at": "2026-01-30T10:30:00",
  "n_samples": 14523
}
```

---

## Configuration Reference

### WorkflowConfig (m01_workflow.py)

```python
@dataclass
class WorkflowConfig:
    start_date: str = '2018-01-01'
    end_date: str = '2023-12-31'
    ks_threshold: float = 0.15           # Composite/KS threshold
    correlation_threshold: float = 0.7   # Clustering threshold
    auto_select: bool = True             # Use passed features only
    fast_eda: bool = False               # Use KS-only pipeline
    target_type: str = 'log_space'       # Training target
    tune: bool = False                   # Optuna tuning
    save_model: bool = False             # NEVER auto-save
```

### Workflow CLI Arguments (model_runner.py workflow)

| Argument | Default | Description |
|----------|---------|-------------|
| `--steps` | all | Steps to run: load, eda, select, train, report |
| `--ks-threshold` | 0.05 | Composite/KS test threshold |
| `--correlation-threshold` | 0.7 | Correlation threshold for clustering |
| `--fast-eda` | False | Use KS-only pipeline (skip 4-pillar) |
| `--no-auto-select` | False | Use all candidates (skip screening) |
| `--features` | None | Explicit feature list |

### M01 CLI Arguments (model_runner.py m01)

| Argument | Default | Description |
|----------|---------|-------------|
| `--start` | 2018-01-01 | Training start date |
| `--end` | 2023-12-31 | Training end date |
| `--target` | log_space | Target type |
| `--tune` | False | Enable Optuna tuning |
| `--report` | False | Generate markdown report |
| `--survivor` | False | Enable survivor model |

---

## Current Production Configuration

**Features:** 21 (defined in `M01_FEATURES`)
**Target:** `log_space`
**Model:** `models/m01.json`
**Calibration:** `models/m01_calibration.json` (decile-based lookup)

---

## Dependencies

```
model_runner.py
    └── src/pipeline/
            ├── m01_workflow.py (WorkflowConfig, M01Workflow)
            ├── m01_trainer.py (M01Trainer)
            ├── data_pipeline.py (DataPipeline)
            └── base_trainer.py (BaseTrainer)
    └── src/evaluation/
            ├── feature_screener.py (FeatureScreener)
            ├── feature_analyzer.py (FeatureAnalyzer) ← NEW
            ├── targets.py (TargetEngineer)
            └── m01_evaluator.py (M01Evaluator)
    └── src/feature_config.py (M01_FEATURES, M01_CANDIDATE_FEATURES)
```

---

## Troubleshooting

### "feature_names mismatch" Error

**Cause:** Model was trained with different features than `M01_FEATURES`
**Fix:** Retrain model or restore from git:
```bash
git checkout HEAD -- models/m01.json models/m01_config.json
```

### "No calibrator fitted" Error

**Cause:** `models/m01_calibration.json` missing or invalid
**Fix:** Regenerate calibration after training (future enhancement)

### Low IC / Selection Edge

**Possible causes:**
1. Wrong target type (use `log_space`)
2. Data leakage in features
3. Insufficient training data (need 4+ years)

### "statsmodels not installed"

**Cause:** Optional dependency for ADF stationarity test
**Fix:** `pip install statsmodels` or ignore (stationarity is warning-only)

---

*Documentation generated for session handover. See `docs/session_logs/` for context.*
