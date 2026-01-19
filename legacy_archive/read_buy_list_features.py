"""
Export buy list to Excel.
"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent))

from src.database import DatabaseManager

if __name__ == "__main__":
    db = DatabaseManager()
    buy_list = db.get_buy_list(active_only=True)

    if buy_list.empty:
        print("No signals found.")
    else:
        buy_list.to_excel("buy_list.xlsx", index=False, engine='openpyxl')
        print(f"✓ Exported {len(buy_list)} signals to buy_list.xlsx")
