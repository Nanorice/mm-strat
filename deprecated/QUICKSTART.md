# Quick Start Guide - QSS

Get your SEPA trading system running in 5 minutes!

## Step 1: Install Dependencies

```bash
pip install -r requirements.txt
```

Expected output:
```
Successfully installed pandas numpy yfinance matplotlib seaborn scikit-learn pyarrow fastparquet openpyxl requests
```

## Step 2: Test the Scanner (Recommended First Run)

Run a quick scan with a small subset to verify setup:

```bash
python main_scanner.py
```

This will:
1. ✓ Fetch S&P 500 ticker list
2. ✓ Download price data to `data/price/` (Parquet cache)
3. ✓ Scan for SEPA setups
4. ✓ Create SQLite database at `database/trades.db`
5. ✓ Display buy signals and watchlist

**First run**: ~2-3 minutes (downloads data)
**Subsequent runs**: ~30-60 seconds (uses cache)

### Expected Output Example:

```
================================================================================
 SEPA DAILY SCANNER | 2025-11-25 23:30
================================================================================

[1/5] Fetching S&P 500 Universe...
       Loaded 503 tickers

[2/5] Updating Price Data Cache...
       Updated 503/503 tickers

[3/5] Loading Benchmark (SPY)...

[4/5] Scanning for SEPA Setups...
       Progress: 500/503
       Scan complete: 3 triggered, 45 in setup

[5/5] Updating Watchlist Database...

================================================================================
 SCAN RESULTS | 3 ACTIONABLE SETUPS
================================================================================

🟢 BUY SIGNALS (Triggered Today):

Ticker   Price   Stop    Target  Risk %  Reward %  Vol Ratio  ATR
NVDA     145.20  133.58  167.10  8.00    24.00     1.8x       2.91
AMD      142.35  130.96  164.52  8.00    24.00     1.5x       2.85
PLTR     68.45   62.97   77.91   8.00    24.00     2.1x       1.37

--------------------------------------------------------------------------------
EXECUTION PLAN:
1. ENTRY:  Market buy at open OR limit order near close price
2. STOP:   Hard stop at 'Stop' price (8% fixed)
3. TARGET: Take profit at 'Target' price (3R = 24%)
4. SIZE:   12.5% of portfolio per position (max 8 positions)
--------------------------------------------------------------------------------
```

## Step 3: Run a Quick Backtest

Test with 50 stocks first (faster):

```bash
python main_backtest.py --subset 50
```

This will:
1. ✓ Load historical data (2021-present)
2. ✓ Run event-driven backtest
3. ✓ Calculate performance metrics
4. ✓ Generate equity curve visualization
5. ✓ Export trade log CSV
6. ✓ Create HTML performance report

**Runtime**: ~3-5 minutes for 50 stocks

### Expected Output Example:

```
======================================================================
 SEPA STRATEGY PERFORMANCE REPORT
======================================================================

📊 TRADING STATISTICS
   Total Trades:        47
   Winning Trades:      29
   Losing Trades:       18
   Win Rate:            61.7%

💰 PROFIT & LOSS
   Total P&L:           $23,450.00
   Avg Win:             12.50%
   Avg Loss:            -5.20%
   Largest Win:         45.30%
   Largest Loss:        -8.00%
   Profit Factor:       2.41
   Expectancy:          5.85%

📈 PORTFOLIO PERFORMANCE
   Initial Capital:     $100,000
   Final Equity:        $123,450
   Total Return:        23.45%
   CAGR:                4.89%
   Max Drawdown:        -12.30%
   Sharpe Ratio:        1.85
   Sortino Ratio:       2.67
======================================================================
```

## Step 4: Run Full Backtest

Once you've verified everything works, run the full backtest:

```bash
python main_backtest.py
```

**Runtime**: ~20-30 minutes for all S&P 500 stocks
**Output**: Same as above, but with complete universe

## Step 5: Review Results

After backtest completes, you'll have:

1. **Console Output**: Performance summary
2. **trades_log.csv**: Detailed trade history
3. **performance_report.html**: Interactive HTML report (open in browser)
4. **performance_charts.png**: Equity curve, drawdown, distribution charts
5. **database/trades.db**: SQLite database with all data

### View HTML Report

```bash
# Windows
start performance_report.html

# Mac
open performance_report.html

# Linux
xdg-open performance_report.html
```

## Common Issues & Fixes

### Issue: `ModuleNotFoundError: No module named 'src'`

**Fix**: Make sure you're running from the project root directory:
```bash
cd c:\Users\Hang\PycharmProjects\quantamental
python main_scanner.py
```

### Issue: `yfinance` download timeout

**Fix**: Run again - the cache will pick up where it left off.

### Issue: No setups found

**Cause**: Market may be in a consolidation phase or criteria too strict.
**Solution**: This is normal - SEPA is selective. Try adjusting thresholds in `config.py`:

```python
VOL_SPIKE_THRESHOLD = 1.2  # Reduce from 1.3
CONSOLIDATION_PERIOD = 15   # Reduce from 20
```

## Next Steps

### Daily Workflow

```bash
# Run every morning before market open
python main_scanner.py
```

This updates your watchlist and shows today's buy signals.

### Weekly Review

```bash
# Re-run backtest to validate performance
python main_backtest.py

# Check database stats
python -c "from src.database import DatabaseManager; db = DatabaseManager(); print(db.get_performance_summary())"
```

### Customize Strategy

1. Edit `config.py` to adjust parameters
2. Modify `src/strategy.py` to change entry/exit rules
3. Update `src/indicators.py` to add custom indicators

## Pro Tips

### Faster Scans

Cache is your friend! After first run:
- Data is saved to `data/price/*.parquet`
- Only updates stale data (>1 day old)
- Scans run 10x faster

### Test Changes Quickly

Use `--subset` flag:
```bash
python main_backtest.py --subset 20  # Test with 20 stocks
```

### Database Queries

```python
from src.database import DatabaseManager
db = DatabaseManager()

# Get watchlist sorted by days
wl = db.get_watchlist().sort_values('days_on_watchlist', ascending=False)
print(wl.head(10))

# Get best trades
trades = db.get_trade_history(closed_only=True)
best = trades.nlargest(10, 'pnl_percent')
print(best[['ticker', 'pnl_percent', 'exit_reason']])
```

## Architecture Overview

```
main_scanner.py
    ↓
DataRepository → Parquet Cache
    ↓
SEPAStrategy → TechnicalAnalysis
    ↓
DatabaseManager → SQLite
    ↓
OUTPUT: Buy signals + Watchlist
```

```
main_backtest.py
    ↓
DataRepository → Parquet Cache
    ↓
SEPAStrategy → TechnicalAnalysis
    ↓
BacktestEngine → PortfolioManager
    ↓
PerformanceReporter → Charts + Reports
```

## What's Next?

1. ✅ **You have a working trading system!**
2. Run daily scans to build watchlist
3. Review backtest performance
4. Adjust parameters based on your risk tolerance
5. Consider adding ML scoring (Phase 5 in roadmap)

---

**Need Help?** Check [README.md](README.md) for full documentation.
