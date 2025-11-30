import sqlite3
conn = sqlite3.connect('c:/Users/Hang/PycharmProjects/quantamental/database/trades.db')
cursor = conn.cursor()
cursor.execute('PRAGMA table_info(buy_list_activity)')
print('Current buy_list_activity schema:')
for row in cursor.fetchall():
    print(row)
conn.close()
