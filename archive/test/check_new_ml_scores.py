"""
Check ML scores for recently added signals to verify the fix is working.
"""
import sqlite3
import sys
sys.path.append('.')
import config

db_path = config.DB_PATH
print(f"Using database: {db_path}\n")
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Check signals added today vs older signals
print("="*100)
print("ML SCORES BY SIGNAL DATE")
print("="*100)

cursor.execute('''
    SELECT signal_date, ticker, ml_probability, ml_rank, ml_model_version
    FROM buy_list 
    WHERE signal_date >= "2025-11-17"
    ORDER BY signal_date DESC, ticker
''')

rows = cursor.fetchall()
print(f"\nTotal signals since 2025-11-17: {len(rows)}\n")

current_date = None
for row in rows:
    signal_date, ticker, prob, rank, version = row
    
    # Print date header
    if signal_date != current_date:
        if current_date is not None:
            print()
        print(f"Signals from {signal_date}:")
        print("-" * 100)
        current_date = signal_date
    
    # Format the output - handle bytes gracefully
    if prob is None:
        prob_str = "None"
    elif isinstance(prob, bytes):
        prob_str = "BINARY"
    else:
        try:
            prob_str = f"{float(prob):.3f}"
        except:
            prob_str = "ERROR"
    
    if rank is None:
        rank_str = "None"
    elif isinstance(rank, bytes):
        rank_str = "BINARY"
    elif isinstance(rank, int):
        rank_str = str(rank)
    else:
        try:
            rank_str = str(int(rank))
        except:
            rank_str = "ERROR"
    
    version_str = str(version)[:30] if version else "None"
    
    print(f"  {ticker:6s} | prob={prob_str:8s} | rank={rank_str:10s} | version={version_str}")

# Summary statistics
print("\n" + "="*100)
print("SUMMARY STATISTICS")
print("="*100)

cursor.execute('''
    SELECT 
        COUNT(*) as total,
        SUM(CASE WHEN ml_probability IS NULL THEN 1 ELSE 0 END) as null_prob,
        SUM(CASE WHEN ml_rank IS NULL THEN 1 ELSE 0 END) as null_rank,
        SUM(CASE WHEN ml_probability IS NOT NULL THEN 1 ELSE 0 END) as valid_prob,
        COUNT(DISTINCT signal_date) as unique_dates
    FROM buy_list 
    WHERE signal_date >= "2025-11-17"
''')

stats = cursor.fetchone()
total, null_prob, null_rank, valid_prob, unique_dates = stats

print(f"\nTotal signals: {total}")
print(f"Unique signal dates: {unique_dates}")
print(f"Valid ML probabilities: {valid_prob} ({valid_prob/total*100:.1f}%)")
print(f"NULL ML probabilities: {null_prob} ({null_prob/total*100:.1f}%)")
print(f"NULL ML ranks: {null_rank} ({null_rank/total*100:.1f}%)")

# Check if any have binary rank issue
cursor.execute('''
    SELECT ticker, signal_date, ml_rank, ml_probability
    FROM buy_list 
    WHERE signal_date >= "2025-11-17" AND (ml_rank IS NOT NULL OR ml_probability IS NOT NULL)
''')
binary_prob_count = 0
binary_rank_count = 0
for row in cursor.fetchall():
    ticker, date, rank, prob = row
    if isinstance(prob, bytes):
        binary_prob_count += 1
    if isinstance(rank, bytes):
        binary_rank_count += 1

if binary_prob_count > 0 or binary_rank_count > 0:
    print(f"\n⚠️  WARNING:")
    if binary_prob_count > 0:
        print(f"   - {binary_prob_count} signals have binary probability data")
    if binary_rank_count > 0:
        print(f"   - {binary_rank_count} signals have binary rank data")
    print(f"\n💡 SOLUTION: Run rebuild_ml_scores.py to fix old signals")
    print(f"   Example: python rebuild_ml_scores.py --start-date 2025-11-17 --end-date 2025-11-28")
else:
    print(f"\n✓  No binary data issues found!")

conn.close()
