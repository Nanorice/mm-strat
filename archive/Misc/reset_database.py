"""Delete and recreate database with new schema"""
import os
from src.database import DatabaseManager

db_path = 'database/trades.db'
if os.path.exists(db_path):
    os.remove(db_path)
    print('✓ Old database deleted')

db = DatabaseManager()
print('✓ New database created with updated schema')
print(f'Database location: {db.db_path}')
