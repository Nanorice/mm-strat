# ML Pipeline Documentation

## Overview

The SEPA ML system uses two models:

| Model | Type | Purpose | Features |
|-------|------|---------|----------|
| **M01** | Regression | Predicts expected return % | 21 features |
| **M02** | Classification | Predicts ignition probability (TP hit before SL) | 38 velocity-focused features |

## Pipeline Architecture

```
src/pipeline/
├── __init__.py          # Exports: DataPipeline, M01Trainer, M02Trainer
├── data_pipeline.py     # DataPipeline class - data generation
├── base_trainer.py      # BaseTrainer - shared training logic
├── m01_trainer.py       # M01Trainer - regression model
└── m02_trainer.py       # M02Trainer - classification model
```

## Data Flow

```
M01 (Regression):
    scan() → d1.parquet → features() → d2.parquet → M01Trainer.train()

M02 (Classification):  
    scan() → d1.parquet → hydrate() → d2r_120d.parquet → label() → d3_120d.parquet → M02Trainer.train()
```

## Quick Start

### Training M01 (Return Predictor)

```python
from src.pipeline import DataPipeline, M01Trainer

# Generate data
pipeline = DataPipeline()
d1 = pipeline.scan('2020-01-01', '2023-12-31')
d2 = pipeline.features(d1)

# Train model
trainer = M01Trainer()
model, metrics = trainer.train(d2, tune=False)
trainer.save(model, metrics)
```

### Training M02 (Ignition Classifier)

```python
from src.pipeline import DataPipeline, M02Trainer

# Generate data
pipeline = DataPipeline()
d1 = pipeline.scan('2020-01-01', '2023-12-31')
d2r = pipeline.hydrate(d1, horizon_days=120)
d3 = pipeline.label(d2r)

# Train model
trainer = M02Trainer()
model, metrics = trainer.train(d3, tune=False)
trainer.save(model, metrics)
```

## CLI Usage

### New Clean CLI (`model.py`)

```bash
# Train M01 (regression)
python model.py m01 --start 2020-01-01 --end 2023-12-31

# Train M02 (classification)  
python model.py m02 --start 2020-01-01 --end 2023-12-31 --horizon 120

# Run specific steps only
python model.py m01 --steps scan features  # Data prep only
python model.py m02 --steps train --tune   # Train with tuning
```

### Legacy CLI (`model_trainer.py`)

The original CLI is preserved for backward compatibility:

```bash
# M01 pipeline (legacy)
python model_trainer.py --steps d1 d2 train

# M02 pipeline (legacy)
python model_trainer.py --steps d1 d2rh d3 d3train --horizon 120
```

## File Naming Convention

| File | Description |
|------|-------------|
| `d1.parquet` | Trade candidates from SEPA screener |
| `d2.parquet` | Features at entry date |
| `d2r_sepa.parquet` | Rehydrated with SEPA exits |
| `d2r_{N}d.parquet` | Rehydrated with N-day horizon |
| `d3_{N}d.parquet` | Triple barrier labels |
| `m01.json` | M01 model file |
| `m02.json` | M02 model file |

## Feature Sets

### M01_FEATURES (21 features)
Used by M01 regression model. Mix of alphas, technicals, and fundamentals.

### M02_FEATURES (38 features)
Used by M02 classifier. Velocity-focused features for ignition detection:
- Velocity Squad: `volume_acceleration`, `rs_velocity`, `breakout_momentum`
- WorldQuant Alphas: `alpha046`, `alpha051`, `alpha101`
- Context: `consolidation_duration`, `Breakout`, `VCP_Ratio`

See `src/feature_config.py` for complete lists.

---
*Created: 2026-01-26*
