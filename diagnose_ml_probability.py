"""
Deep diagnostic of ML probability storage issue.
"""
import sqlite3
import sys
import numpy as np
sys.path.append('.')
import config

db_path = config.DB_PATH
print(f"Database: {db_path}\n")
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Get the latest signals with ML scores
cursor.execute('''
    SELECT ticker, signal_date, ml_probability, ml_rank, ml_model_version
    FROM buy_list 
    WHERE signal_date >= "2025-11-17"
    ORDER BY signal_date DESC, ticker
    LIMIT 20
''')

print("="*100)
print("DETAILED ML SCORE ANALYSIS")
print("="*100)

for row in cursor.fetchall():
    ticker, date, prob, rank, version = row
    
    print(f"\nTicker: {ticker} (Signal Date: {date})")
    print(f"  ml_probability:")
    print(f"    Value: {prob}")
    print(f"    Type: {type(prob)}")
    print(f"    Is None: {prob is None}")
    if prob is not None:
        print(f"    Is bytes: {isinstance(prob, bytes)}")
        try:
            print(f"    Float conversion: {float(prob)}")
        except Exception as e:
            print(f"    Float conversion error: {e}")
    
    print(f"  ml_rank:")
    print(f"    Value: {rank}")
    print(f"    Type: {type(rank)}")
    print(f"    Is None: {rank is None}")

# Check the database schema
cursor.execute("PRAGMA table_info(buy_list)")
schema = cursor.fetchall()

print("\n" + "="*100)
print("DATABASE SCHEMA - buy_list table")
print("="*100)

for col in schema:
    col_id, name, dtype, notnull, default, pk = col
    if 'ml_' in name:
        print(f"{name:20s} | Type: {dtype:10s} | NotNull: {notnull} | Default: {default}")

# Check what Python/numpy types are being stored
cursor.execute('''
    SELECT ml_probability, ml_rank
    FROM buy_list 
    WHERE ml_probability IS NOT NULL 
    LIMIT 5
''')

print("\n" + "="*100)
print("SAMPLE VALUES FROM DATABASE")
print("="*100)

sample_data = cursor.fetchall()
if sample_data:
    for i, (prob, rank) in enumerate(sample_data, 1):
        print(f"\nSample {i}:")
        print(f"  Probability: repr={repr(prob)}, type={type(prob).__name__}, value={prob}")
        print(f"  Rank: repr={repr(rank)}, type={type(rank).__name__}, value={rank}")
else:
    print("No non-NULL ml_probability values found")

conn.close()

# Also test numpy float conversion
print("\n" + "="*100)
print("NUMPY TYPE CONVERSION TEST")
print("="*100)

test_prob = np.float64(0.123)
print(f"Numpy float64: {test_prob}")
print(f"Type: {type(test_prob)}")
print(f"Is NaN: {np.isnan(test_prob)}")
print(f"Python float: {float(test_prob)}")
print(f"Stored in SQLite and retrieved type: ", end="")

# Test what SQLite does with numpy types
test_conn = sqlite3.connect(':memory:')
test_cursor = test_conn.cursor()
test_cursor.execute('CREATE TABLE test (val REAL)')
test_cursor.execute('INSERT INTO test VALUES (?)', (test_prob,))
test_cursor.execute('SELECT val FROM test')
retrieved = test_cursor.fetchone()[0]
print(f"{type(retrieved).__name__}, value={retrieved}")
test_conn.close()
