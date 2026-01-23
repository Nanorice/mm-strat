# QSS Project Standards

**Project management, documentation, and development discipline**

This document defines standards for the Quantamental SEPA System (QSS) project to maintain code quality, organization, and clarity.

---

## Table of Contents

1. [Directory Structure](#directory-structure)
2. [File Naming Conventions](#file-naming-conventions)
3. [Documentation Standards](#documentation-standards)
4. [Code Standards](#code-standards)
5. [Git Workflow](#git-workflow)
6. [Development Workflow](#development-workflow)

---

## Directory Structure

### Standard Layout

```
quantamental/
├── .claude/              # Project management & standards (this folder)
│   ├── PROJECT_STANDARDS.md
│   └── settings.local.json
│
├── src/                  # Core library code (production-ready modules)
│   ├── __init__.py
│   ├── data_engine.py          # Data acquisition
│   ├── features.py             # Feature engineering
│   ├── strategy.py             # SEPA strategy
│   ├── trade_simulator.py      # Simulation engine
│   ├── model_preparation.py    # ML preparation
│   ├── train_model.py          # ML training
│   ├── evaluate_model.py       # ML evaluation
│   └── ml_scorer.py            # Production inference
│
├── scripts/              # Operational scripts (run regularly)
│   ├── README.md               # Script documentation
│   ├── init_fundamentals.py
│   ├── initialise_price_data.py
│   ├── view_buy_list.py
│   └── ...
│
├── tools/                # Debugging & diagnostic utilities (one-off use)
│   ├── README.md               # Tool documentation
│   ├── inspect_dataset_b.py
│   ├── validate_features.py
│   ├── debug_missing_columns.py
│   └── ...
│
├── test/                 # Unit & integration tests
│   ├── README.md
│   ├── test_features.py
│   ├── test_strategy.py
│   └── ...
│
├── notebooks/            # Jupyter notebooks (exploration, analysis)
│   ├── README.md
│   └── exploration.ipynb
│
├── docs/                 # Documentation
│   ├── ARCHITECTURE.md         # System architecture
│   ├── DATASET_A_GUIDE.md
│   ├── DATASET_B_GUIDE.md
│   ├── MODEL_TRAINING_GUIDE.md
│   └── ...
│
├── data/                 # Data storage (gitignored)
│   ├── price/                  # Cached price data
│   ├── fundamental_cache/      # Fundamental data
│   ├── ml/                     # ML datasets
│   ├── predictions_log.parquet
│   └── scanner_output/
│
├── models/               # Trained ML models (gitignored)
│   ├── model_fold_1.json
│   └── model_metadata_fold_1.json
│
├── evaluation/           # Model evaluation outputs
│   ├── evaluation_report.json
│   └── *.png
│
├── database/             # SQLite databases (gitignored)
│   └── qss_scanner.db
│
├── Misc/                 # Archived/deprecated code
│   ├── README.md
│   └── old_scripts/
│
├── build_dataset_a.py    # Main pipeline scripts (root level)
├── build_dataset_b.py
├── merge_datasets.py
├── train_sepa_model.py
├── optimized_scanner.py  # Main application
│
├── config.py             # Global configuration
├── requirements.txt
├── .env                  # API keys (gitignored)
├── .gitignore
├── USER_GUIDE.md         # User manual
└── README.md             # Project overview
```

---

### Directory Purpose

| Directory | Purpose | Add Files Here When... |
|-----------|---------|------------------------|
| `src/` | Core library modules | Creating reusable, production-ready classes/functions |
| `scripts/` | Operational scripts | Script will run regularly (daily/weekly/monthly) |
| `tools/` | Debugging utilities | Script is for one-off debugging, testing, validation |
| `test/` | Unit tests | Writing pytest tests |
| `notebooks/` | Exploration | Doing exploratory analysis, prototyping |
| `docs/` | Documentation | Writing architecture docs, guides, design docs |
| `Misc/` | Archive | Deprecating old code you want to keep |
| Root | Main pipelines | Creating a major workflow script (build, train, scan) |

---

## File Naming Conventions

### Python Files

**Modules** (in `src/`): `snake_case.py`
```
data_engine.py          # ✅ Good
DataEngine.py           # ❌ Bad (use snake_case)
dataengine.py           # ❌ Bad (hard to read)
```

**Scripts**: Descriptive verb + noun
```
build_dataset_a.py      # ✅ Good (verb + noun)
init_fundamentals.py    # ✅ Good
dataset_a.py            # ❌ Bad (no verb)
script1.py              # ❌ Bad (not descriptive)
```

**Tools**: Prefix with action verb
```
check_cache_dates.py    # ✅ Good
inspect_merged.py       # ✅ Good
validate_features.py    # ✅ Good
debug_missing_columns.py # ✅ Good
verify_dataset_a.py     # ✅ Good
test_fast_simulator.py  # ✅ Good
dataset_checker.py      # ❌ Bad (use verb first)
tool.py                 # ❌ Bad (not descriptive)
```

**Tool Prefixes**:
- `check_` - Quick status check (dates, cache, etc.)
- `inspect_` - Detailed analysis (datasets, features)
- `validate_` - Correctness validation
- `verify_` - Quick verification
- `debug_` - Debugging utilities
- `test_` - Testing scripts

---

### Documentation Files

**Markdown files**: `SCREAMING_SNAKE_CASE.md` for docs, `lowercase.md` for notes
```
USER_GUIDE.md           # ✅ Good (major doc)
ARCHITECTURE.md         # ✅ Good
README.md               # ✅ Good (standard)
sprint_plan.md          # ✅ Good (notes/planning)
notes.md                # ✅ Good (notes)
UserGuide.md            # ❌ Bad (use SCREAMING_SNAKE_CASE)
```

---

### Data Files

**Datasets**: Descriptive name + date range
```
dataset_a_2023_2024.parquet  # ✅ Good
training_dataset_final.parquet # ✅ Good
data.parquet                   # ❌ Bad (not descriptive)
```

**Models**: Include fold number or version
```
model_fold_1.json              # ✅ Good
model_metadata_fold_1.json     # ✅ Good
model_v2_2024_12_01.json       # ✅ Good
model.json                     # ❌ Bad (no version)
```

---

## Documentation Standards

### Documentation Hierarchy

1. **USER_GUIDE.md** (Root) - How to use the system (workflows, recipes)
2. **README.md** (Root) - Project overview, quick start
3. **docs/ARCHITECTURE.md** - System design, module breakdown (for developers)
4. **docs/[SPECIFIC_GUIDE].md** - Detailed guides (Dataset A, Model Training, etc.)
5. **scripts/README.md** - Script documentation
6. **tools/README.md** - Tool documentation
7. **Inline docstrings** - Function/class documentation

---

### When to Create Documentation

| Type | When to Create |
|------|----------------|
| **USER_GUIDE** | Major workflow changes, new features |
| **Architecture Doc** | New module, major refactor |
| **Specific Guide** | Complex subsystem needs explanation |
| **Script README** | New script added to `scripts/` |
| **Tool README** | New tool added to `tools/` |
| **Inline Docstring** | Every function/class |
| **Code Comment** | Non-obvious logic only |

---

### Documentation Template

**For Scripts**:
```python
"""
Script Name: build_dataset_a.py

Purpose: Generate daily feature snapshots (Dataset A) for ML training

Usage:
    python build_dataset_a.py --start 2023-01-01 --end 2024-12-31

Parameters:
    --start: Start date (YYYY-MM-DD)
    --end: End date (YYYY-MM-DD)
    --mode: 'full' or 'lightweight'
    --output: Output file path

Output:
    Parquet file with daily feature snapshots

Dependencies:
    - src/data_engine.py
    - src/features.py
    - config.py

Author: [Your Name]
Created: 2024-11-15
Last Modified: 2024-12-01
"""
```

**For Modules**:
```python
"""
Module: data_engine.py

Purpose: Data acquisition, caching, and universe management

Key Classes:
    - DataRepository: Central hub for market data operations

Key Functions:
    - update_universe(): Fetch ticker universe
    - get_ticker_data(): Load single ticker
    - update_cache(): Download and cache data

Dependencies:
    - yfinance
    - requests (FMP API)
    - pandas

Author: [Your Name]
"""
```

**For Functions**:
```python
def calculate_features(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """
    Calculate technical and fundamental features for a ticker.

    Args:
        df: Price data with OHLCV columns
        ticker: Stock ticker symbol

    Returns:
        DataFrame with added feature columns

    Raises:
        ValueError: If df is missing required columns

    Example:
        >>> df = repo.get_ticker_data('AAPL')
        >>> df_features = calculate_features(df, 'AAPL')
        >>> print(df_features.columns)
    """
```

---

### Documentation Maintenance

**Update documentation when**:
- Adding new features
- Changing function signatures
- Modifying workflows
- Fixing bugs that affect usage
- Deprecating features

**Review documentation**:
- Monthly: Check for outdated info
- Before releases: Full review
- After major refactors: Update architecture docs

---

## Code Standards

### Python Style

**Follow PEP 8** with these conventions:
- **Indentation**: 4 spaces
- **Line length**: 120 characters (not 79)
- **Imports**: Group by standard library, third-party, local
- **Naming**:
  - Functions/variables: `snake_case`
  - Classes: `PascalCase`
  - Constants: `SCREAMING_SNAKE_CASE`

---

### Type Hints

**Use type hints for**:
- All function signatures
- Class attributes
- Complex variables

```python
# ✅ Good
def get_ticker_data(ticker: str, source: str = 'yfinance') -> pd.DataFrame:
    cache_path: Path = DATA_DIR / f"{ticker}.parquet"
    return pd.read_parquet(cache_path)

# ❌ Bad
def get_ticker_data(ticker, source='yfinance'):
    cache_path = DATA_DIR / f"{ticker}.parquet"
    return pd.read_parquet(cache_path)
```

---

### Error Handling

**Use specific exceptions**:
```python
# ✅ Good
if not os.path.exists(cache_path):
    raise FileNotFoundError(f"Cache file not found: {cache_path}")

# ❌ Bad
if not os.path.exists(cache_path):
    raise Exception("File not found")
```

**Log errors**:
```python
# ✅ Good
try:
    data = fetch_data(ticker)
except requests.RequestException as e:
    logging.error(f"Failed to fetch {ticker}: {e}")
    raise

# ❌ Bad
try:
    data = fetch_data(ticker)
except:
    pass  # Silent failure
```

---

### Configuration

**Use `config.py` for**:
- Global constants
- API endpoints
- Feature parameters
- Strategy thresholds

**Use environment variables for**:
- API keys
- Passwords
- Secrets

```python
# config.py
import os
from dotenv import load_dotenv

load_dotenv()

# Constants
SMA_FAST = 50
SMA_SLOW = 200

# Secrets (from .env)
FMP_API_KEY = os.getenv('FMP_API_KEY')
```

---

## Git Workflow

### Commit Message Format

```
<type>(<scope>): <subject>

<body (optional)>

<footer (optional)>
```

**Types**:
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation only
- `refactor`: Code restructuring
- `test`: Adding tests
- `chore`: Maintenance (dependencies, config)
- `perf`: Performance improvement

**Examples**:
```
feat(scanner): add ML scoring to optimized_scanner.py

- Integrated MLScorer class
- Added --use-ml flag
- Added prediction logging
- Updated database schema with ML columns

Closes #42

---

fix(features): resolve NaN issue in alpha factor calculation

Alpha #006 was producing NaN for low-volume stocks. Added
minimum volume threshold check.

Fixes #38

---

docs: create USER_GUIDE.md for operational workflows

Added comprehensive guide covering data sourcing, scanning,
and model training.
```

---

### Branching Strategy

**Main branches**:
- `main`: Production-ready code
- `develop`: Integration branch (if using GitFlow)

**Feature branches**:
- `feature/ml-integration`
- `feature/fundamental-data`
- `fix/alpha-nan-issue`

**Workflow**:
```bash
# Create feature branch
git checkout -b feature/new-feature

# Work on feature
git add .
git commit -m "feat(module): add new feature"

# Push and create PR
git push origin feature/new-feature
```

---

### What to Commit

**Do commit**:
- Source code (`src/`, root scripts)
- Documentation (`docs/`, `*.md`)
- Configuration (`config.py`, `requirements.txt`)
- Tests (`test/`)

**Don't commit** (add to `.gitignore`):
- Data files (`data/`, `*.parquet`, `*.csv`)
- Models (`models/`, `*.json`)
- Databases (`database/`, `*.db`)
- Secrets (`.env`)
- Cache (`__pycache__`, `.pytest_cache`)
- Notebooks with outputs (`*.ipynb` outputs)

---

## Development Workflow

### Before Starting Work

1. **Update documentation** understanding
   - Read `USER_GUIDE.md` for workflow context
   - Read `docs/ARCHITECTURE.md` for module context

2. **Check existing code**
   - Search for similar functionality
   - Review related modules

3. **Plan the change**
   - Where does this belong? (`src/`, `scripts/`, `tools/`)
   - What will break?
   - What documentation needs updates?

---

### During Development

1. **Follow standards**
   - File naming conventions
   - Code style (PEP 8)
   - Type hints
   - Documentation

2. **Write tests** (for `src/` modules)
   ```python
   # test/test_features.py
   def test_calculate_sma():
       df = create_sample_data()
       result = calculate_sma(df, period=50)
       assert 'SMA_50' in result.columns
       assert not result['SMA_50'].isna().all()
   ```

3. **Update documentation**
   - Add docstrings
   - Update relevant guides
   - Update README files

---

### After Development

1. **Test locally**
   ```bash
   # Run unit tests
   pytest test/

   # Run integration test
   python build_dataset_a.py --start 2024-11-01 --end 2024-11-30
   ```

2. **Update documentation**
   - `USER_GUIDE.md` if workflow changed
   - `docs/ARCHITECTURE.md` if module changed
   - Script/tool README if new script added

3. **Create changelog entry** (if significant)
   ```markdown
   ## [Unreleased]

   ### Added
   - ML scoring integration in scanner (#42)

   ### Fixed
   - Alpha factor NaN issue for low-volume stocks (#38)
   ```

4. **Commit with descriptive message**
   ```bash
   git add .
   git commit -m "feat(scanner): add ML scoring to scanner"
   ```

---

### Adding New Files

**Checklist**:
- [ ] Choose correct directory (`src/`, `scripts/`, `tools/`)
- [ ] Follow naming convention
- [ ] Add file docstring
- [ ] Add function docstrings
- [ ] Add type hints
- [ ] Update directory README if needed
- [ ] Update `USER_GUIDE.md` if user-facing
- [ ] Add to `.gitignore` if data/output file

**Example - Adding New Script**:
```bash
# 1. Create script in correct folder
touch scripts/export_signals.py

# 2. Add docstring and code
# ... (write script)

# 3. Update scripts/README.md
# ... (document script)

# 4. Update USER_GUIDE.md if needed
# ... (add to "Common Tasks" section)

# 5. Test
python scripts/export_signals.py

# 6. Commit
git add scripts/export_signals.py scripts/README.md USER_GUIDE.md
git commit -m "feat(scripts): add export_signals.py for CSV export"
```

---

## Project Management

### Issue Tracking

**Use GitHub Issues for**:
- Bug reports
- Feature requests
- Documentation improvements
- Questions

**Issue Template**:
```markdown
## Issue Type
- [ ] Bug
- [ ] Feature Request
- [ ] Documentation
- [ ] Question

## Description
[Clear description of issue/request]

## Steps to Reproduce (for bugs)
1. Run command: `python build_dataset_a.py`
2. Error appears: [error message]

## Expected Behavior
[What should happen]

## Actual Behavior
[What actually happens]

## Environment
- OS: Windows/Linux/Mac
- Python version: 3.11
- Branch: main

## Additional Context
[Any other relevant info]
```

---

### Milestones & Sprints

**Track in `docs/sprint_plan.md`**:
- Sprint goals
- Completed tasks
- Blockers
- Next steps

**Review monthly**:
- What worked well?
- What needs improvement?
- Documentation gaps?
- Code quality issues?

---

## Review Checklist

### Code Review Checklist

- [ ] Follows file naming conventions
- [ ] In correct directory
- [ ] Has docstrings
- [ ] Has type hints
- [ ] Follows PEP 8
- [ ] No hardcoded secrets
- [ ] Error handling present
- [ ] Tests added (for `src/` modules)
- [ ] Documentation updated
- [ ] Commit message descriptive

---

### Documentation Review Checklist

- [ ] USER_GUIDE updated if workflow changed
- [ ] ARCHITECTURE updated if module changed
- [ ] Script/tool README updated if script added
- [ ] Inline documentation complete
- [ ] Examples provided
- [ ] No broken links
- [ ] Up-to-date with code changes

---

## Questions?

If you're unsure about:
- **Where to put a file**: Check [Directory Structure](#directory-structure)
- **How to name a file**: Check [File Naming Conventions](#file-naming-conventions)
- **What documentation to write**: Check [Documentation Standards](#documentation-standards)
- **How to commit**: Check [Git Workflow](#git-workflow)

**When in doubt, ask!** Create a GitHub issue with your question.

---

## Rationale

**Why these standards?**

1. **Directory separation**: Prevents root directory clutter, improves discoverability
2. **Naming conventions**: Makes file purpose obvious at a glance
3. **Documentation hierarchy**: Separates user docs from developer docs
4. **Type hints**: Catches bugs early, improves IDE support
5. **Git discipline**: Makes history readable, enables collaboration
6. **Tests for src/ only**: Scripts are tested by running them, modules need unit tests

**Industry influences**:
- **Django**: Separation of apps, migrations, tests
- **FastAPI**: Clear documentation hierarchy
- **scikit-learn**: src/ for library code, examples/ for scripts
- **Conventional Commits**: Standardized commit messages
- **GitFlow**: Branching strategy
