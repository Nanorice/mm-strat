from src.buy_list_manager import BuyListManager
from src.strategy import SEPAStrategy
from src.data_engine import DataRepository

manager = BuyListManager()
data_repo = DataRepository()
strategy = SEPAStrategy()

# Populate complete history from Nov 2025
history = manager.backfill('2025-11-17', '2025-11-26', data_repo, strategy)
print(f"Logged {len(history)} events for ML training")