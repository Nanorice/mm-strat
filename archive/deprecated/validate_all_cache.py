"""
Comprehensive validation of ALL cached data
Checks for corruption patterns in price, fundamental, and company profile data
"""
import pandas as pd
import sys
from pathlib import Path
from collections import defaultdict
import hashlib

sys.path.append(str(Path(__file__).parent))

import config

print("=" * 80)
print(" COMPREHENSIVE CACHE VALIDATION")
print("=" * 80)

# ============================================================================
# PRICE DATA VALIDATION
# ============================================================================
print("\n" + "=" * 80)
print(" PRICE DATA VALIDATION")
print("=" * 80)

price_dir = Path(config.PRICE_DATA_DIR)
print(f"\nPrice cache directory: {price_dir}")

if not price_dir.exists():
    print("❌ Price directory not found!")
else:
    price_files = list(price_dir.glob("*.parquet"))
    print(f"Total price cache files: {len(price_files)}")
    
    if len(price_files) == 0:
        print("⚠️  No price cache files found")
    else:
        # Check 1: Identical file sizes (strong indicator of corruption)
        print("\n--- Checking for identical file sizes (corruption indicator) ---")
        size_groups = defaultdict(list)
        for f in price_files:
            size = f.stat().st_size
            size_groups[size].append(f.stem)
        
        duplicates_found = {size: tickers for size, tickers in size_groups.items() if len(tickers) > 1}
        
        if duplicates_found:
            print(f"❌ CORRUPTION DETECTED: Found {len(duplicates_found)} groups with identical file sizes!")
            for size, tickers in sorted(duplicates_found.items(), key=lambda x: len(x[1]), reverse=True)[:10]:
                print(f"   {size:,} bytes: {len(tickers)} files - {', '.join(tickers[:10])}{'...' if len(tickers) > 10 else ''}")
        else:
            print(f"✅ All {len(price_files)} files have unique sizes")
        
        # Check 2: Identical file hashes (definitive corruption proof)
        print("\n--- Checking for identical file hashes (sampling 50 files) ---")
        sample_size = min(50, len(price_files))
        import random
        sample_files = random.sample(price_files, sample_size)
        
        hash_groups = defaultdict(list)
        for f in sample_files:
            with open(f, 'rb') as file:
                file_hash = hashlib.sha256(file.read()).hexdigest()[:16]
                hash_groups[file_hash].append(f.stem)
        
        hash_duplicates = {h: tickers for h, tickers in hash_groups.items() if len(tickers) > 1}
        
        if hash_duplicates:
            print(f"❌ CORRUPTION CONFIRMED: {len(hash_duplicates)} groups of identical files (exact duplicates)!")
            for h, tickers in hash_duplicates.items():
                print(f"   Hash {h}: {', '.join(tickers)}")
        else:
            print(f"✅ All {sample_size} sampled files are unique")
        
        # Check 3: Data content validation (sample)
        print("\n--- Validating data content (sampling 10 files) ---")
        content_sample = random.sample(price_files, min(10, len(price_files)))
        
        for f in content_sample:
            ticker = f.stem
            try:
                df = pd.read_parquet(f)
                
                # Check for reasonable data
                if df.empty:
                    print(f"   ❌ {ticker}: Empty DataFrame")
                elif len(df) < 100:
                    print(f"   ⚠️  {ticker}: Only {len(df)} rows (possibly incomplete)")
                elif df.index.max() > pd.Timestamp.now():
                    print(f"   ❌ {ticker}: Future dates ({df.index.max().date()})")
                else:
                    print(f"   ✅ {ticker}: {len(df)} rows, {df.index.min().date()} to {df.index.max().date()}")
                    
            except Exception as e:
                print(f"   ❌ {ticker}: Failed to read - {e}")

# ============================================================================
# FUNDAMENTAL DATA VALIDATION
# ============================================================================
print("\n" + "=" * 80)
print(" FUNDAMENTAL DATA VALIDATION")
print("=" * 80)

fund_dir = Path(config.FUNDAMENTALS_DIR)
print(f"\nFundamental cache directory: {fund_dir}")

if not fund_dir.exists():
    print("⚠️  Fundamental directory not found")
else:
    fund_files = list(fund_dir.glob("*_fundamentals.parquet"))
    print(f"Total fundamental files: {len(fund_files)}")
    
    if len(fund_files) == 0:
        print("⚠️  No fundamental cache files found")
    else:
        # Check for identical sizes
        print("\n--- Checking for identical file sizes ---")
        size_groups = defaultdict(list)
        for f in fund_files:
            size = f.stat().st_size
            ticker = f.stem.replace('_fundamentals', '')
            size_groups[size].append(ticker)
        
        duplicates_found = {size: tickers for size, tickers in size_groups.items() if len(tickers) > 1}
        
        if duplicates_found:
            print(f"⚠️  Found {len(duplicates_found)} groups with identical file sizes")
            for size, tickers in sorted(duplicates_found.items(), key=lambda x: len(x[1]), reverse=True)[:5]:
                print(f"   {size:,} bytes: {len(tickers)} files - {', '.join(tickers[:10])}")
        else:
            print(f"✅ All {len(fund_files)} fundamental files have unique sizes")
        
        # Sample content check
        print("\n--- Validating fundamental data content (sampling 5 files) ---")
        content_sample = random.sample(fund_files, min(5, len(fund_files)))
        
        for f in content_sample:
            ticker = f.stem.replace('_fundamentals', '')
            try:
                df = pd.read_parquet(f)
                
                # Check if symbol column matches filename
                if 'symbol' in df.columns:
                    symbols = df['symbol'].unique()
                    if ticker in symbols:
                        print(f"   ✅ {ticker}: {len(df)} rows, symbol matches")
                    else:
                        print(f"   ❌ {ticker}: Symbol mismatch! Found: {symbols}")
                else:
                    print(f"   ⚠️  {ticker}: No symbol column")
                    
            except Exception as e:
                print(f"   ❌ {ticker}: Failed to read - {e}")

# ============================================================================
# COMPANY PROFILE VALIDATION
# ============================================================================
print("\n" + "=" * 80)
print(" COMPANY PROFILE VALIDATION")
print("=" * 80)

db_path = Path('database/stocks.db')
print(f"\nDatabase path: {db_path}")

if not db_path.exists():
    print("⚠️  Database not found")
else:
    import sqlite3
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Check if company_profiles table exists
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='company_profiles'")
    if cursor.fetchone():
        # Count profiles
        cursor.execute("SELECT COUNT(*) FROM company_profiles")
        total_profiles = cursor.fetchone()[0]
        print(f"Total company profiles: {total_profiles}")
        
        # Check for duplicates
        cursor.execute("""
            SELECT symbol, COUNT(*) as count 
            FROM company_profiles 
            GROUP BY symbol 
            HAVING count > 1
        """)
        duplicates = cursor.fetchall()
        
        if duplicates:
            print(f"❌ Found {len(duplicates)} duplicate symbols!")
            for symbol, count in duplicates[:10]:
                print(f"   {symbol}: {count} entries")
        else:
            print(f"✅ No duplicate symbols")
        
        # Sample some profiles
        cursor.execute("SELECT symbol, company_name, sector FROM company_profiles LIMIT 5")
        print("\nSample profiles:")
        for symbol, name, sector in cursor.fetchall():
            print(f"   {symbol}: {name} ({sector})")
    else:
        print("⚠️  company_profiles table not found")
    
    conn.close()

# ============================================================================
# SUMMARY
# ============================================================================
print("\n" + "=" * 80)
print(" VALIDATION SUMMARY")
print("=" * 80)

print("""
Review the output above for:
1. ❌ Groups of files with identical sizes (strong corruption indicator)
2. ❌ Identical file hashes (definitive corruption proof)
3. ❌ Symbol mismatches in fundamental data
4. ❌ Duplicate entries in company profiles
5. ⚠️  Empty or incomplete data

If corruption is widespread, recommend FULL CACHE REBUILD.
""")
