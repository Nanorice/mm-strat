"""
Clear all buy_list and buy_list_activity records from the database.
"""
import sqlite3
import sys
sys.path.append('.')
import config

db_path = config.DB_PATH
print(f"Using database: {db_path}\n")

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Count records before deletion
cursor.execute('SELECT COUNT(*) FROM buy_list')
buy_list_count = cursor.fetchone()[0]

cursor.execute('SELECT COUNT(*) FROM buy_list_activity')
activity_count = cursor.fetchone()[0]

print(f"Records to delete:")
print(f"  - buy_list: {buy_list_count}")
print(f"  - buy_list_activity: {activity_count}")
print()

# Confirm deletion
response = input("Proceed with deletion? (yes/no): ").strip().lower()

if response == 'yes':
    # Delete all records
    cursor.execute('DELETE FROM buy_list')
    cursor.execute('DELETE FROM buy_list_activity')
    
    conn.commit()
    
    print(f"\n✓ Deleted {buy_list_count} records from buy_list")
    print(f"✓ Deleted {activity_count} records from buy_list_activity")
    print("\nDatabase cleared successfully!")
else:
    print("\nDeletion cancelled.")

conn.close()
