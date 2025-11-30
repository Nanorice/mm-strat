from src.data_engine import DataRepository
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)

def main():
    repo = DataRepository()
    
    # 1. Get Universe
    tickers = repo.update_universe()
    print(f"Universe size: {len(tickers)}")
    
    # 2. Update Price Data (Force update to ensure we get the new 2010 history)
    print("Updating Price Data (Source: FMP, Start: 2000)...")
    repo.update_cache(tickers, force=True, source='yfinance')
    
    print("Done!")

if __name__ == "__main__":
    main()