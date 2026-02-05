
import logging
import sys
from pathlib import Path
import pandas as pd
import backtrader as bt
from datetime import datetime

# Add src to path
sys.path.append(str(Path.cwd()))

# Adjust path imports to match project structure
try:
    from src.backtest.runner import SEPABacktestRunner
    from src.backtest.sepa_strategy import SEPAHybridV1
    from src.backtest.feeds import M03RegimeFeed, SEPAStockFeed
    from src.backtest.price_feed import get_qualifying_tickers
except ImportError:
    # Fallback if run from root
    sys.path.append('c:/Users/Hang/PycharmProjects/quantamental')
    from src.backtest.runner import SEPABacktestRunner
    from src.backtest.sepa_strategy import SEPAHybridV1
    from src.backtest.feeds import M03RegimeFeed, SEPAStockFeed
    from src.backtest.price_feed import get_qualifying_tickers

# Subclass Strategy to add debug logging
class DebugSEPA(SEPAHybridV1):
    def next(self):
        # Call original next first to update tracker
        super().next()
        
        # Now log the state
        tracker_count = self.position_tracker.get_open_count()
        tracker_positions = list(self.position_tracker.positions.keys())
        
        broker_value = self.broker.getvalue()
        broker_cash = self.broker.getcash()
        broker_pos_value = broker_value - broker_cash
        
        # Calculate calculated exposure
        calc_exposure = (broker_pos_value / broker_value * 100) if broker_value > 0 else 0
        
        # Get actual broker positions
        broker_positions = []
        for d in self.datas:
            if d._name == 'regime': continue
            pos = self.getposition(d)
            if pos.size != 0:
                broker_positions.append((d._name, pos.size))
        
        # Only log if there's activity or periodic
        if tracker_count > 0 or len(broker_positions) > 0:
            print(f"Date: {self.datetime.date()}")
            print(f"  Tracker: {tracker_count} positions {tracker_positions}")
            print(f"  Broker:  Value=${broker_value:,.0f} Cash=${broker_cash:,.0f} PosValue=${broker_pos_value:,.0f} ({calc_exposure:.2f}%)")
            print(f"  RealPos: {len(broker_positions)} positions {broker_positions}")
            
            if len(broker_positions) != tracker_count:
                print("  MISMATCH DETECTED!")
                # Check for zombies
                for ticker in tracker_positions:
                    found = False
                    for bt_ticker, size in broker_positions:
                        if bt_ticker == ticker:
                            found = True
                            break
                    if not found:
                         print(f"  ZOMBIE ALERT: {ticker} in tracker but not in broker!")
                
                # Check for un-tracked interactions
                for bt_ticker, size in broker_positions:
                    if bt_ticker not in tracker_positions:
                        print(f"  GHOST ALERT: {bt_ticker} in broker but not in tracker!")

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    
    cerebro = bt.Cerebro()
    
    # Setup paths
    # Using absolute paths to be safe
    base_dir = Path('c:/Users/Hang/PycharmProjects/quantamental')
    regime_path = base_dir / 'data/backtest/m03_feed.parquet'
    scores_path = base_dir / 'data/backtest/universe_scores.parquet'
    prices_dir = base_dir / 'data/backtest/prices'
    
    print("Loading data...")
    # Load M03
    regime_df = pd.read_parquet(regime_path)
    # Filter to 2021
    regime_df = regime_df[(regime_df.index >= '2021-01-01') & (regime_df.index <= '2021-12-31')]
    
    cerebro.adddata(M03RegimeFeed(dataname=regime_df, name='regime'))
    
    # Load Prices (limit to top tickers for debug speed)
    print("Getting tickers...")
    tickers = sorted(list(get_qualifying_tickers(scores_path)))[:50] # Check 50 tickers
    
    print(f"Loading {len(tickers)} price feeds...")
    for ticker in tickers:
        p = prices_dir / f'{ticker}.parquet'
        if p.exists():
            df = pd.read_parquet(p)
            df = df[(df.index >= '2021-01-01') & (df.index <= '2021-12-31')]
            if len(df) > 50:
                cerebro.adddata(SEPAStockFeed(dataname=df, name=ticker))

    # Add Strategy with debug enabled
    cerebro.addstrategy(DebugSEPA, min_percentile=0.9, min_score=30.0)
    
    cerebro.broker.setcash(100000)
    
    print("Running Debug Backtest...")
    cerebro.run()
