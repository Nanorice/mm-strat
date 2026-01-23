# Contributing to QSS

**Quick reference for making changes to the project**

This guide provides quick answers for common development tasks. For comprehensive standards, see [PROJECT_STANDARDS.md](PROJECT_STANDARDS.md).

---

## Quick Start

### Making a Change

```bash
# 1. Update your local copy
git pull origin main

# 2. Create feature branch
git checkout -b feature/my-feature

# 3. Make changes
# ... edit files

# 4. Test
pytest test/  # If you modified src/
python your_script.py  # If you created a script

# 5. Commit
git add .
git commit -m "feat(module): description of change"

# 6. Push
git push origin feature/my-feature
```

---

## Where Do I Put This File?

| I'm creating... | Put it in... | Example |
|----------------|--------------|---------|
| A reusable class/function | `src/` | `src/portfolio_manager.py` |
| A script I'll run daily/weekly | `scripts/` | `scripts/update_watchlist.py` |
| A debugging/testing script | `tools/` | `tools/check_data_quality.py` |
| A unit test | `test/` | `test/test_portfolio_manager.py` |
| A Jupyter notebook | `notebooks/` | `notebooks/analysis.ipynb` |
| A documentation guide | `docs/` | `docs/PORTFOLIO_GUIDE.md` |
| Old code I want to keep | `Misc/` | `Misc/old_scanner.py` |
| A major pipeline script | Root | `build_portfolio.py` |

---

## How Do I Name This File?

| File Type | Convention | Example |
|-----------|------------|---------|
| Module (in `src/`) | `snake_case.py` | `portfolio_manager.py` |
| Script | `verb_noun.py` | `build_dataset.py` |
| Tool | `prefix_description.py` | `check_cache.py` |
| Test | `test_module.py` | `test_features.py` |
| Major doc | `SCREAMING_SNAKE.md` | `USER_GUIDE.md` |
| Notes/plans | `lowercase.md` | `sprint_plan.md` |

**Tool prefixes**: `check_`, `inspect_`, `validate_`, `verify_`, `debug_`, `test_`

---

## What Documentation Do I Write?

### For New Scripts

1. **Add docstring** at top of file
2. **Update script README**: `scripts/README.md` or `tools/README.md`
3. **Update USER_GUIDE.md**: If users will run it regularly

### For New Modules

1. **Add module docstring**
2. **Add function docstrings** (all functions)
3. **Update ARCHITECTURE.md**: Add module description
4. **Write guide** (if complex): `docs/YOUR_MODULE_GUIDE.md`

### For Bug Fixes

1. **Update docstring** if behavior changed
2. **Update guide** if user-facing behavior changed

---

## Commit Message Format

```
<type>(<scope>): <subject>

<body (optional)>
```

**Types**:
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation only
- `refactor`: Code restructuring
- `test`: Tests
- `chore`: Maintenance

**Examples**:
```
feat(scanner): add ML scoring
fix(features): resolve NaN in alpha calculation
docs: update USER_GUIDE with new workflow
refactor(data_engine): simplify cache logic
test: add tests for feature calculation
chore: update dependencies
```

---

## Code Style Quick Reference

### Imports
```python
# Standard library
import os
from pathlib import Path

# Third-party
import pandas as pd
import numpy as np

# Local
from src.data_engine import DataRepository
from config import FMP_API_KEY
```

### Type Hints
```python
def get_data(ticker: str, start: str = '2024-01-01') -> pd.DataFrame:
    """Always use type hints for function signatures"""
    pass
```

### Naming
```python
# Variables & functions: snake_case
ticker_data = get_ticker_data('AAPL')

# Classes: PascalCase
class DataRepository:
    pass

# Constants: SCREAMING_SNAKE_CASE
MAX_RETRIES = 3
```

### Error Handling
```python
# Use specific exceptions
if not file.exists():
    raise FileNotFoundError(f"File not found: {file}")

# Log errors
import logging
try:
    data = fetch_data(ticker)
except Exception as e:
    logging.error(f"Failed to fetch {ticker}: {e}")
    raise
```

---

## Testing

### Unit Tests (for `src/` modules only)

```python
# test/test_features.py
import pytest
from src.features import calculate_sma

def test_calculate_sma():
    """Test SMA calculation"""
    df = create_sample_data()
    result = calculate_sma(df, period=50)

    assert 'SMA_50' in result.columns
    assert not result['SMA_50'].isna().all()

def test_calculate_sma_invalid_period():
    """Test error handling"""
    df = create_sample_data()
    with pytest.raises(ValueError):
        calculate_sma(df, period=-10)
```

### Running Tests

```bash
# All tests
pytest

# Specific test file
pytest test/test_features.py

# Specific test function
pytest test/test_features.py::test_calculate_sma

# With output
pytest -v
```

---

## Common Tasks

### Adding a New Script

```bash
# 1. Create script in correct folder
touch scripts/my_script.py

# 2. Add docstring
"""
Purpose: What this script does

Usage:
    python scripts/my_script.py --arg value

Parameters:
    --arg: Description

Output:
    What it produces
"""

# 3. Add to script README
# Edit scripts/README.md

# 4. Test
python scripts/my_script.py

# 5. Commit
git add scripts/my_script.py scripts/README.md
git commit -m "feat(scripts): add my_script for XYZ"
```

---

### Adding a New Module

```bash
# 1. Create module
touch src/my_module.py

# 2. Add class/functions with docstrings
class MyClass:
    """Description of class"""

    def my_method(self, arg: str) -> int:
        """Description of method"""
        pass

# 3. Add tests
touch test/test_my_module.py

# 4. Update ARCHITECTURE.md
# Add module description

# 5. Commit
git add src/my_module.py test/test_my_module.py docs/ARCHITECTURE.md
git commit -m "feat(src): add my_module for XYZ"
```

---

### Updating Workflow

```bash
# 1. Make code changes
# ... edit files

# 2. Update USER_GUIDE.md
# Add new section or update existing

# 3. Test workflow
python your_script.py

# 4. Commit both code and docs
git add your_script.py USER_GUIDE.md
git commit -m "feat(workflow): add new XYZ workflow"
```

---

### Fixing a Bug

```bash
# 1. Write a test that reproduces the bug
# test/test_module.py

def test_bug_xyz():
    """Reproduce bug XYZ"""
    result = buggy_function(input)
    assert result == expected  # This should fail

# 2. Fix the bug
# ... edit code

# 3. Verify test passes
pytest test/test_module.py::test_bug_xyz

# 4. Commit
git add src/module.py test/test_module.py
git commit -m "fix(module): resolve XYZ bug"
```

---

## Docstring Templates

### Module Docstring
```python
"""
Module: my_module.py

Purpose: Brief description of what this module does

Key Classes:
    - MyClass: Description

Key Functions:
    - my_function(): Description

Dependencies:
    - pandas
    - src.data_engine

Author: Your Name
Created: 2024-12-01
"""
```

### Function Docstring
```python
def my_function(arg1: str, arg2: int = 10) -> pd.DataFrame:
    """
    Brief description of function.

    Longer description if needed. Explain the purpose,
    algorithm, or important behavior.

    Args:
        arg1: Description of arg1
        arg2: Description of arg2 (default: 10)

    Returns:
        Description of return value

    Raises:
        ValueError: When validation fails
        FileNotFoundError: When file doesn't exist

    Example:
        >>> result = my_function('AAPL', 20)
        >>> print(result.head())
    """
    pass
```

### Class Docstring
```python
class MyClass:
    """
    Brief description of class.

    Longer description. Explain the purpose,
    usage pattern, or important behavior.

    Attributes:
        attr1: Description
        attr2: Description

    Example:
        >>> obj = MyClass(arg='value')
        >>> result = obj.method()
    """

    def __init__(self, arg: str):
        """Initialize MyClass with arg."""
        self.attr1 = arg
```

---

## Pre-commit Checklist

Before committing, verify:

- [ ] Code follows PEP 8 style
- [ ] All functions have docstrings
- [ ] Type hints added
- [ ] Tests pass (`pytest`)
- [ ] Documentation updated
- [ ] No secrets in code (API keys, passwords)
- [ ] Descriptive commit message

---

## Getting Help

### Where to Look

1. **USER_GUIDE.md** - How to use the system
2. **ARCHITECTURE.md** - How the system works
3. **PROJECT_STANDARDS.md** - Detailed standards
4. **Script/Tool README** - Specific script documentation

### Ask Questions

Create a GitHub issue:

```markdown
## Question

[Your question here]

## Context

- What are you trying to do?
- What have you tried?
- What documentation have you checked?

## Environment

- OS: Windows/Linux/Mac
- Python: 3.11
```

---

## Review Process

### Self-Review

Before requesting review:

1. **Read your own diff**
   ```bash
   git diff main
   ```

2. **Check documentation**
   - Did you update relevant docs?
   - Are docstrings clear?

3. **Test thoroughly**
   - Unit tests pass?
   - Manual testing done?

4. **Clean commit history**
   ```bash
   # If commits are messy, squash them
   git rebase -i HEAD~3
   ```

---

## Tips & Best Practices

### DRY (Don't Repeat Yourself)

```python
# ✅ Good - Reusable function
def fetch_data(ticker: str) -> pd.DataFrame:
    """Fetch and cache data for ticker"""
    # ... logic

aapl_data = fetch_data('AAPL')
msft_data = fetch_data('MSFT')

# ❌ Bad - Repeated code
aapl_data = pd.read_parquet(f'data/{ticker}.parquet')
if aapl_data is None:
    aapl_data = yf.download('AAPL')
    aapl_data.to_parquet('data/AAPL.parquet')

msft_data = pd.read_parquet(f'data/{ticker}.parquet')
if msft_data is None:
    msft_data = yf.download('MSFT')
    # ... same code repeated
```

---

### Single Responsibility

```python
# ✅ Good - Each function does one thing
def load_data(ticker: str) -> pd.DataFrame:
    """Load data from cache"""
    return pd.read_parquet(f'data/{ticker}.parquet')

def calculate_sma(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate SMA"""
    df['SMA_50'] = df['Close'].rolling(50).mean()
    return df

# ❌ Bad - Function does too much
def load_and_process(ticker: str) -> pd.DataFrame:
    """Load data, calculate features, save results"""
    df = pd.read_parquet(f'data/{ticker}.parquet')
    df['SMA_50'] = df['Close'].rolling(50).mean()
    df.to_csv('output.csv')
    return df
```

---

### Fail Fast

```python
# ✅ Good - Validate early
def process_ticker(ticker: str, df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        raise ValueError(f"Empty data for {ticker}")

    if 'Close' not in df.columns:
        raise ValueError(f"Missing 'Close' column for {ticker}")

    # ... proceed with processing

# ❌ Bad - Fail late
def process_ticker(ticker: str, df: pd.DataFrame) -> pd.DataFrame:
    # ... 100 lines of processing
    result = df['Close'].mean()  # Crashes here if 'Close' missing
```

---

### Use Configuration

```python
# ✅ Good - Use config.py
from config import SMA_FAST, SMA_SLOW

def calculate_sma(df: pd.DataFrame) -> pd.DataFrame:
    df[f'SMA_{SMA_FAST}'] = df['Close'].rolling(SMA_FAST).mean()
    return df

# ❌ Bad - Magic numbers
def calculate_sma(df: pd.DataFrame) -> pd.DataFrame:
    df['SMA_50'] = df['Close'].rolling(50).mean()  # Where did 50 come from?
    return df
```

---

## Resources

- [PEP 8 Style Guide](https://pep8.org/)
- [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html)
- [Conventional Commits](https://www.conventionalcommits.org/)
- [pytest Documentation](https://docs.pytest.org/)

---

## Questions?

**Not sure about something?** Check [PROJECT_STANDARDS.md](PROJECT_STANDARDS.md) or create an issue.

**Found a bug in these docs?** Create an issue or submit a PR!
