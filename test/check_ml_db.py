import sqlite3
import sys
sys.path.append('.')
import config

db_path = config.DB_PATH
print(f"Using database: {db_path}")
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Check recent ML-scored entries
cursor.execute('''
    SELECT ticker, ml_probability, ml_rank, ml_model_version, ml_score_date 
    FROM buy_list 
    WHERE signal_date >= "2025-11-17"
    LIMIT 20
''')

rows = cursor.fetchall()
print("\nML scores from database (since 2025-11-17):")
print("-" * 100)
for row in rows:
    ticker, prob, rank, version, date = row
    print(f"Ticker: {ticker:6s} | Prob: {prob:10} | Rank: {rank:10} | Version: {str(version):20s} | Date: {date}")

# Also check for null values
cursor.execute('''
    SELECT COUNT(*) as total,
           SUM(CASE WHEN ml_probability IS NULL THEN 1 ELSE 0 END) as null_prob,
           SUM(CASE WHEN ml_rank IS NULL THEN 1 ELSE 0 END) as null_rank
    FROM buy_list 
    WHERE signal_date >= "2025-11-17"
''')
stats = cursor.fetchone()
print(f"\nStats: Total={stats[0]}, Null probability={stats[1]}, Null rank={stats[2]}")

conn.close()
