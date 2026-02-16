"""
Systematic audit: compare column references in SQL-querying files
against actual DuckDB daily_features schema.
"""
import duckdb
import re
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "market_data.duckdb"
PROJECT_ROOT = Path(__file__).parent.parent

# 1. Get actual schema
con = duckdb.connect(str(DB_PATH))
actual_cols = set(r[0] for r in con.execute("DESCRIBE daily_features").fetchall())

# 2. Get view definition
view_sql = ""
try:
    rows = con.execute("SELECT sql FROM duckdb_views() WHERE schema_name='main'").fetchall()
    for r in rows:
        view_sql += r[0] + "\n"
except:
    pass

con.close()

print("=" * 60)
print("ACTUAL daily_features COLUMNS")
print("=" * 60)
for c in sorted(actual_cols):
    print(f"  {c}")

print(f"\nTotal: {len(actual_cols)} columns")

# 3. Check files that query daily_features
files_to_check = [
    "src/data_loader_duckdb.py",
    "daily_scanner_duckdb.py",
    "data_curator_duckdb.py",
    "scripts/migrate_to_duckdb.py",
    "scripts/fix_view.py",
]

# Common old->new column name mappings to detect
KNOWN_RENAMES = {
    "pct_from_52w_high": "pct_from_high_52w",
    "avg_volume_20d": "vol_avg_20",
    "max_52w": "high_52w",
    "min_52w": "low_52w",
}

print("\n" + "=" * 60)
print("COLUMN REFERENCE AUDIT")
print("=" * 60)

# Pattern: f.column_name or df.column_name or daily_features.column_name
col_ref_pattern = re.compile(r'(?:f|df|daily_features)\.(\w+)')

issues_found = 0
for filepath in files_to_check:
    full_path = PROJECT_ROOT / filepath
    if not full_path.exists():
        print(f"\n[SKIP] {filepath} (not found)")
        continue

    content = full_path.read_text(encoding='utf-8')
    refs = col_ref_pattern.findall(content)
    
    # Filter to unique references that look like column names
    skip_words = {'ticker', 'date', 'copy', 'empty', 'columns', 'index', 'values', 
                  'to_string', 'head', 'tail', 'shape', 'dtypes', 'fetchdf', 'fetchone',
                  'fetchall', 'df', 'execute', 'connect', 'close', 'read_text', 'exists',
                  'parent', 'name', 'format', 'replace', 'strip', 'split', 'join',
                  'append', 'extend', 'items', 'keys', 'get', 'set_index', 'reset_index',
                  'groupby', 'merge', 'sort_values', 'drop', 'rename', 'apply', 'tolist',
                  'iterrows', 'dropna', 'fillna', 'notna', 'isna', 'astype', 'loc', 'iloc',
                  'describe', 'info', 'to_csv', 'to_parquet', 'read_parquet', 'read_csv',
                  'write', 'path', 'stem', 'suffix', 'mkdir'}
    
    unique_refs = sorted(set(r for r in refs if r.lower() not in skip_words))
    
    # Check which refs don't exist in actual schema
    bad_refs = []
    for ref in unique_refs:
        if ref not in actual_cols and ref in KNOWN_RENAMES:
            bad_refs.append((ref, KNOWN_RENAMES[ref]))
        elif ref not in actual_cols and ref not in skip_words:
            # Could be a company_profiles or price_data column, not necessarily wrong
            pass
    
    if bad_refs:
        issues_found += len(bad_refs)
        print(f"\n[ISSUES] {filepath}:")
        for old, new in bad_refs:
            print(f"  [FIX] {old} -> {new}")
    else:
        print(f"\n[OK] {filepath}: No known column mismatches")

# 4. Check v_sepa_candidates view
print("\n" + "=" * 60)
print("v_sepa_candidates VIEW DEFINITION")
print("=" * 60)
if view_sql:
    print(view_sql[:2000])
    # Check for bad refs in view
    view_refs = col_ref_pattern.findall(view_sql)
    bad_view = [r for r in view_refs if r in KNOWN_RENAMES]
    if bad_view:
        print(f"\n[ISSUES] v_sepa_candidates view:")
        for ref in bad_view:
            print(f"  [FIX] {ref} -> {KNOWN_RENAMES[ref]}")
            issues_found += 1
    else:
        print("\n[OK] View references look correct")
else:
    print("[WARN] Could not retrieve view definition")

print(f"\n{'=' * 60}")
print(f"TOTAL ISSUES: {issues_found}")
print(f"{'=' * 60}")
