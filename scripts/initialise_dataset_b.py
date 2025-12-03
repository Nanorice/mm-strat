from src.data_engine import DataRepository
from src.fundamental_engine import FundamentalEngine

repo = DataRepository()
fund_engine = FundamentalEngine()
# Scan price folder for tickers
import config
from pathlib import Path
price_dir = config.PRICE_DATA_DIR
tickers = [f.stem for f in price_dir.glob('*.parquet')]
print(f"Found {len(tickers)} tickers in price folder")
fund_engine.update_fundamentals_cache(tickers, show_progress=True)