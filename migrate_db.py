"""
Database Migration Script - Add missing columns to buy_list table
"""
import sqlite3

db_path = 'c:/Users/Hang/PycharmProjects/quantamental/database/trades.db'
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Check current schema
cursor.execute('PRAGMA table_info(buy_list)')
existing_columns = {row[1] for row in cursor.fetchall()}

print("Existing columns:", existing_columns)

# Define new columns to add
new_columns = {
    'entry_price': 'REAL',
    'stop_price': 'REAL',
    'target_price': 'REAL',
    'atr': 'REAL'
}

# Add missing columns
for col_name, col_type in new_columns.items():
    if col_name not in existing_columns:
        try:
            cursor.execute(f'ALTER TABLE buy_list ADD COLUMN {col_name} {col_type}')
            print(f"✓ Added column: {col_name}")
        except sqlite3.OperationalError as e:
            print(f"✗ Failed to add {col_name}: {e}")

# Create buy_list_activity table if it doesn't exist
cursor.execute("""
    CREATE TABLE IF NOT EXISTS buy_list_activity (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticker TEXT NOT NULL,
        action TEXT NOT NULL,
        action_date DATE NOT NULL,
        reason TEXT,
        entry_price REAL,
        stop_price REAL,
        target_price REAL,
        rs REAL,
        vol_ratio REAL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
""")
print("✓ buy_list_activity table created/verified")

conn.commit()
conn.close()

print("\nMigration complete!")
