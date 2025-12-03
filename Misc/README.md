# Misc Directory

**Archive for deprecated, experimental, and old code**

This folder contains code that's no longer actively used but may be useful for reference.

---

## What Goes Here

- **Deprecated scripts**: Old versions of scripts that have been replaced
- **Experimental code**: Prototypes and experiments that didn't make it to production
- **Example code**: Sample scripts for learning purposes
- **Legacy implementations**: Old implementations kept for reference

---

## Current Contents

### Example Scripts

#### `example_scanner.py`
**Purpose**: Example implementation of basic scanner

**Status**: Replaced by `optimized_scanner.py`

**Use for**: Learning how scanner logic works, reference implementation

---

#### `example_backtest.py`
**Purpose**: Example backtest implementation

**Status**: Replaced by `main_backtest.py` and `TradeSimulator`

**Use for**: Understanding backtest logic

---

### Bug Fix Notes

#### `BUGFIX_NOTES.md`
**Purpose**: Historical notes on bug fixes

**Status**: Archived - bug tracking moved to GitHub Issues

**Use for**: Understanding past issues and solutions

---

## Guidelines

### When to Add Files Here

Move files to `Misc/` when:
- Replacing old script with new version
- Deprecating functionality
- Archiving experimental code
- Keeping reference implementations

### When NOT to Add Files Here

Don't put files here if they're:
- Actively used (belongs in `scripts/`, `tools/`, or `src/`)
- Test files (belongs in `test/`)
- Documentation (belongs in `docs/`)
- Truly useless (just delete them)

---

### File Naming in Misc

Prefix with status:
- `deprecated_*.py` - Old version of current script
- `experiment_*.py` - Experimental code
- `old_*.py` - Legacy implementation
- `example_*.py` - Example/tutorial code

**Example**:
```
Misc/
├── deprecated_scanner_v1.py
├── experiment_ml_ranking.py
├── old_feature_engine.py
└── example_backtest.py
```

---

## Cleaning Up

**Quarterly review**:
1. Review files in `Misc/`
2. Delete files that are truly obsolete
3. Move files that are still useful to proper locations
4. Update this README

**Ask yourself**:
- Will I ever need this for reference?
- Does this contain useful patterns/logic?
- Is this documented elsewhere?

If all answers are "no", delete it.

---

## Recovering Deleted Code

If you need code that was deleted:

```bash
# Search git history
git log --all --full-history -- path/to/file.py

# View file at specific commit
git show <commit-hash>:path/to/file.py

# Restore file
git checkout <commit-hash> -- path/to/file.py
```

---

## Best Practices

1. **Document reason for deprecation** in file header:
   ```python
   """
   DEPRECATED: 2024-12-01
   Reason: Replaced by optimized_scanner.py
   Use this for: Reference only
   """
   ```

2. **Keep README updated** when adding files

3. **Delete, don't hoard** - Git history preserves everything

4. **Link to replacement** in docstring:
   ```python
   """
   DEPRECATED: Use scripts/new_script.py instead
   See: scripts/README.md for new usage
   """
   ```

---

## Questions?

Not sure if something should go in `Misc/`? Ask yourself:

- **Is it used in any workflow?** → No, archive it
- **Will I run this regularly?** → No, archive it
- **Does it provide unique value?** → No, delete it
- **Is it just a different version?** → Archive old, keep new

**When in doubt, ask!**
