---
name: module-passport
description: |
  Generate or update technical documentation ("Passport") for Python code modules.
  Use when: (1) ending a coding session and need to document changes, (2) user asks
  to document a module, (3) user wants to create/update module documentation,
  (4) user mentions "passport" for a module. Triggers: "document this module",
  "create passport for", "update module docs", "generate module documentation".
---

# Module Passport Generator

Creates comprehensive technical documentation for Python modules by analyzing source code.

## Usage

Run the passport generator script:

```bash
python scripts/generate_passport.py <entry_point_path>
```

**Arguments:**
- `entry_point_path`: Path to any `.py` file within the module (e.g., `src/daily_scanner/scanner.py`)

**Output:** Creates/updates `docs/modules/[module_name].md`

## What Gets Analyzed

The script extracts:
1. **Data Schemas** - TypedDict, dataclass, pandas DataFrame column patterns
2. **Constants** - UPPERCASE_VARIABLES with their values
3. **Public API** - Class and function signatures (excludes `_private` names)
4. **File Dependencies** - Import relationships for Mermaid diagram

## Output Structure

```markdown
# Module: [name]
## 1. Overview
## 2. Visual Architecture (Mermaid)
## 3. Data Schemas
## 4. Implementation Rules
## 5. Public Interface
## 6. Maintenance Log
```

## Example

```bash
python scripts/generate_passport.py src/backtest/runner.py
# Output: Updated backtest passport at docs/modules/backtest.md. Detected 5 files.
```
