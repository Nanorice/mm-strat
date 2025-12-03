# QSS Project Organization

**Visual guide to project structure (updated 2024-12-02)**

This document provides a visual overview of the newly organized project structure.

---

## Directory Tree

```
quantamental/
│
├── 📁 .claude/                      # Project management & standards
│   ├── PROJECT_STANDARDS.md        # Comprehensive standards guide
│   ├── CONTRIBUTING.md             # Quick contribution reference
│   └── settings.local.json         # Local settings
│
├── 📁 src/                          # Core library modules (production code)
│   ├── data_engine.py              # Data acquisition & caching
│   ├── features.py                 # Feature engineering
│   ├── alpha_factors.py            # WorldQuant alpha factors
│   ├── fundamental_engine.py       # Fundamental data acquisition
│   ├── fundamental_processor.py    # Fundamental preprocessing
│   ├── fundamental_merger.py       # Fundamental-price merging
│   ├── fundamental_data.py         # Fundamental data manager
│   ├── temporal_validator.py       # Data leakage prevention
│   ├── strategy.py                 # SEPA signal generation
│   ├── trade_simulator.py          # Historical simulation engine
│   ├── trade_simulator_fast.py     # Fast simulator (optimized)
│   ├── trading_config.py           # Trading configuration
│   ├── database.py                 # SQLite operations
│   ├── dataset_merger.py           # Dataset A + B merging
│   ├── model_preparation.py        # ML preparation (splitting, selection)
│   ├── train_model.py              # XGBoost training
│   ├── evaluate_model.py           # Model evaluation
│   └── ml_scorer.py                # Production ML inference
│
├── 📁 scripts/                      # Operational scripts (regular use)
│   ├── README.md                   # 📖 Script documentation
│   ├── init_fundamentals.py        # Download fundamental data
│   ├── initialise_price_data.py    # Download price data
│   ├── initialise_dataset_b.py     # Initialize Dataset B
│   ├── view_buy_list.py            # View current buy list
│   ├── view_buy_list_db.py         # View buy list (database details)
│   ├── view_fundamentals.py        # Inspect fundamental coverage
│   ├── show_buy_list.py            # Legacy buy list viewer
│   ├── clear_buy_list.py           # Clear buy list database
│   └── rebuild_ml_scores.py        # Recalculate ML scores
│
├── 📁 tools/                        # Debugging & diagnostic utilities
│   ├── README.md                   # 📖 Tool documentation
│   ├── inspect_dataset_b.py        # Analyze Dataset B quality
│   ├── inspect_merged.py           # Validate merged dataset
│   ├── validate_features.py        # Check feature correctness
│   ├── verify_dataset_a.py         # Quick Dataset A check
│   ├── verify_dataset_b.py         # Quick Dataset B check
│   ├── verify_features.py          # Verify specific features
│   ├── check_all_dates.py          # Check date coverage
│   ├── check_cache_dates.py        # Check cache freshness
│   ├── check_dates.py              # Check date alignment
│   ├── check_recent_cache.py       # List recent cache updates
│   ├── debug_missing_columns.py    # Debug missing features
│   ├── test_fast_simulator.py      # Test simulator performance
│   └── test_yfinance_fix.py        # Test yfinance connectivity
│
├── 📁 test/                         # Unit & integration tests
│   ├── README.md                   # Test documentation
│   └── test_*.py                   # Test files
│
├── 📁 notebooks/                    # Jupyter notebooks (exploration)
│   └── *.ipynb                     # Analysis notebooks
│
├── 📁 docs/                         # Documentation
│   ├── ARCHITECTURE.md             # 📖 System architecture (detailed)
│   ├── DATASET_A_GUIDE.md          # Dataset A documentation
│   ├── DATASET_B_GUIDE.md          # Dataset B documentation
│   ├── MODEL_TRAINING_GUIDE.md     # ML training guide
│   ├── IMPLEMENTATION_SUMMARY.md   # Training implementation summary
│   └── ... (other guides)
│
├── 📁 data/                         # Data storage (gitignored)
│   ├── price/                      # Cached price data (*.parquet)
│   ├── fundamental_cache/          # Fundamental data (*.parquet)
│   ├── ml/                         # ML datasets
│   │   ├── dataset_a.parquet      # Feature snapshots
│   │   ├── dataset_b.parquet      # Trade labels
│   │   └── training_dataset_final.parquet
│   ├── predictions_log.parquet     # ML prediction tracking
│   └── scanner_output/             # Scanner CSV exports
│
├── 📁 models/                       # Trained ML models (gitignored)
│   ├── model_fold_*.json           # XGBoost models
│   └── model_metadata_fold_*.json  # Model metadata
│
├── 📁 evaluation/                   # Model evaluation outputs
│   ├── evaluation_report.json      # Comprehensive metrics
│   ├── roc_curve_fold_*.png        # ROC curves
│   ├── pr_curve_fold_*.png         # Precision-recall curves
│   └── feature_importance_fold_*.png
│
├── 📁 database/                     # SQLite databases (gitignored)
│   └── qss_scanner.db              # Scanner database
│
├── 📁 Misc/                         # Archive (deprecated/experimental)
│   ├── README.md                   # 📖 Archive documentation
│   ├── example_scanner.py          # Example implementation
│   ├── example_backtest.py         # Example backtest
│   └── BUGFIX_NOTES.md             # Historical bug notes
│
├── 📄 Main Pipeline Scripts (root level)
│   ├── build_dataset_a.py          # Generate feature snapshots
│   ├── build_dataset_b.py          # Generate trade labels
│   ├── merge_datasets.py           # Merge Dataset A + B
│   ├── prepare_training_dataset.py # Prepare training data
│   ├── train_sepa_model.py         # Master training orchestrator
│   ├── train_production_model.py   # Production model training
│   ├── optimized_scanner.py        # 🚀 Main scanner application
│   ├── main_scanner.py             # Legacy scanner
│   ├── main_backtest.py            # Backtest runner
│   └── build_fundamentals.py       # Build fundamental dataset
│
├── 📄 Configuration & Support
│   ├── config.py                   # ⚙️ Global configuration
│   ├── requirements.txt            # Python dependencies
│   ├── .env                        # API keys (gitignored)
│   ├── .gitignore                  # Git ignore rules
│   └── WorldQuant_101.py           # Alpha factor library
│
└── 📄 Documentation (root level)
    ├── USER_GUIDE.md               # 📖 User manual (START HERE!)
    ├── README.md                   # Project overview
    ├── QUICKSTART.md               # Quick start guide
    ├── PROJECT_ORGANIZATION.md     # This file
    ├── QSS.md                      # System overview
    ├── WORKFLOW_CHART.md           # Workflow visualization
    └── ... (other docs)
```

---

## Quick Navigation

### "I want to..."

| Goal | Go to |
|------|-------|
| **Learn how to use the system** | [USER_GUIDE.md](USER_GUIDE.md) |
| **Understand system architecture** | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| **Run the scanner daily** | `python optimized_scanner.py --use-ml` |
| **Train ML model** | See [USER_GUIDE.md](USER_GUIDE.md#model-training) |
| **View buy list** | `python scripts/view_buy_list.py` |
| **Debug data issues** | See [tools/README.md](tools/README.md) |
| **Contribute code** | See [.claude/CONTRIBUTING.md](.claude/CONTRIBUTING.md) |
| **Understand project standards** | See [.claude/PROJECT_STANDARDS.md](.claude/PROJECT_STANDARDS.md) |

---

## File Categories

### 🟢 Production Code (Don't touch unless you know what you're doing)

- `src/` - Core library modules
- Main pipeline scripts (root level)
- `config.py`

### 🟡 Operational Scripts (Run regularly)

- `scripts/` - Data initialization, viewing, maintenance
- `optimized_scanner.py` - Main scanner

### 🔵 Development Tools (Use for debugging)

- `tools/` - Debugging, testing, validation scripts
- `test/` - Unit tests

### 🟣 Documentation (Read these!)

- `USER_GUIDE.md` - How to use the system
- `docs/` - Detailed guides
- `.claude/` - Project standards

### ⚪ Archive (Reference only)

- `Misc/` - Deprecated/experimental code

---

## Data Flow

```
┌─────────────────────────────────────────────────────────────┐
│                    DATA FLOW DIAGRAM                        │
└─────────────────────────────────────────────────────────────┘

1. DATA SOURCING
   ├── scripts/initialise_price_data.py → data/price/*.parquet
   └── scripts/init_fundamentals.py → data/fundamental_cache/*.parquet

2. DATASET BUILDING
   ├── build_dataset_b.py → data/ml/dataset_b.parquet (trade labels)
   ├── build_dataset_a.py → data/ml/dataset_a.parquet (features)
   └── merge_datasets.py → data/ml/training_dataset_final.parquet

3. MODEL TRAINING
   └── train_sepa_model.py
       ├── → models/model_fold_*.json
       ├── → models/model_metadata_fold_*.json
       └── → evaluation/*.png

4. SCANNER APPLICATION
   └── optimized_scanner.py --use-ml
       ├── Uses: models/model_fold_1.json
       ├── Updates: database/qss_scanner.db
       └── Logs: data/predictions_log.parquet
```

---

## Module Dependencies

```
┌─────────────────────────────────────────────────────────────┐
│                  MODULE DEPENDENCY GRAPH                    │
└─────────────────────────────────────────────────────────────┘

optimized_scanner.py
├── src/data_engine.py
├── src/features.py
│   └── src/alpha_factors.py
├── src/strategy.py
├── src/fundamental_merger.py
│   ├── src/fundamental_processor.py
│   └── src/fundamental_engine.py
├── src/ml_scorer.py
└── src/database.py

train_sepa_model.py
├── src/model_preparation.py
├── src/train_model.py
└── src/evaluate_model.py

build_dataset_a.py
├── src/data_engine.py
├── src/features.py
└── src/fundamental_merger.py

build_dataset_b.py
├── src/data_engine.py
├── src/features.py
├── src/strategy.py
└── src/trade_simulator.py
```

---

## Cheat Sheet

### Daily Operations

```bash
# Run scanner with ML
python optimized_scanner.py --use-ml

# View buy list
python scripts/view_buy_list.py

# Update price data
python scripts/initialise_price_data.py --force
```

### Model Training (Quarterly)

```bash
# 1. Generate Dataset B
python build_dataset_b.py --start 2023-01-01 --end 2024-12-31

# 2. Generate Dataset A
python build_dataset_a.py --start 2023-01-01 --end 2024-12-31

# 3. Merge datasets
python merge_datasets.py \
  --dataset-a data/ml/dataset_a.parquet \
  --dataset-b data/ml/dataset_b.parquet

# 4. Train model
python train_sepa_model.py --input data/ml/training_dataset_final.parquet
```

### Debugging

```bash
# Check data quality
python tools/inspect_dataset_b.py data/ml/dataset_b.parquet

# Validate features
python tools/validate_features.py AAPL

# Check cache freshness
python tools/check_cache_dates.py
```

---

## Recent Changes (2024-12-02)

### ✅ Completed

1. **Created `USER_GUIDE.md`** - Comprehensive user manual for operational workflows
2. **Organized files into folders**:
   - Moved operational scripts → `scripts/`
   - Moved debugging tools → `tools/`
   - Kept main pipeline scripts in root
3. **Created folder README files**:
   - `scripts/README.md` - Documents operational scripts
   - `tools/README.md` - Documents debugging tools
   - `Misc/README.md` - Documents archived code
4. **Created project standards**:
   - `.claude/PROJECT_STANDARDS.md` - Comprehensive standards
   - `.claude/CONTRIBUTING.md` - Quick contribution guide
5. **Updated documentation hierarchy**:
   - `USER_GUIDE.md` - For users (how to use)
   - `docs/ARCHITECTURE.md` - For developers (how it works)

### 📊 Impact

**Before**:
- 33 Python files in root directory
- No clear separation of concerns
- Hard to find relevant scripts
- Unclear which files to run vs debug

**After**:
- 10 main pipeline scripts in root
- 9 operational scripts in `scripts/`
- 13 debugging tools in `tools/`
- Clear documentation for each category
- Comprehensive standards and contribution guides

---

## Best Practices

### When Adding New Files

1. **Choose correct directory** (see [.claude/PROJECT_STANDARDS.md](.claude/PROJECT_STANDARDS.md))
2. **Follow naming conventions**
3. **Add documentation** (README, docstrings)
4. **Update this guide** if adding new major category

### When Modifying Workflows

1. **Update USER_GUIDE.md** if user-facing
2. **Update ARCHITECTURE.md** if changing modules
3. **Update folder README** if script behavior changes
4. **Test thoroughly** before committing

### When Debugging

1. **Check `tools/` folder** for existing debugging scripts
2. **Create new tool if needed** (add to `tools/`, document in README)
3. **Don't clutter root directory**

---

## Questions?

- **How do I use this system?** → [USER_GUIDE.md](USER_GUIDE.md)
- **How does this work internally?** → [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- **How do I contribute?** → [.claude/CONTRIBUTING.md](.claude/CONTRIBUTING.md)
- **What are the standards?** → [.claude/PROJECT_STANDARDS.md](.claude/PROJECT_STANDARDS.md)
- **Where do I put my file?** → [.claude/PROJECT_STANDARDS.md#directory-structure](.claude/PROJECT_STANDARDS.md#directory-structure)

---

## Industry Best Practices Applied

This organization follows industry standards from:

1. **Django** - Separation of apps, clear directory structure
2. **FastAPI** - Documentation hierarchy (user vs developer docs)
3. **scikit-learn** - `src/` for library, `examples/` for scripts
4. **Conventional Commits** - Standardized commit messages
5. **GitFlow** - Branching strategy
6. **Clean Architecture** - Separation of concerns (data, features, strategy, ML)

**Rationale**: Makes project maintainable, scalable, and collaborative.
