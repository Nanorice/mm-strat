# Quantamental SEPA System (QSS)

A professional-grade, event-driven quantitative trading system implementing **Mark Minervini's SEPA (Specific Entry Point Analysis)** methodology with robust risk management.

## 🎯 Features

- **Object-Oriented Architecture**: Clean, modular design for maintainability
- **Parquet Caching**: Smart data caching to minimize API calls and bandwidth
- **Event-Driven Backtesting**: Realistic simulation with position limits and cash constraints
- **Watchlist Tracking**: SQLite database tracks stocks in setup phase (days on watchlist)
- **Comprehensive Reporting**: Performance metrics, equity curves, and HTML reports
- **SEPA Strategy**: Full implementation of Minervini's Stage 2 uptrend methodology

## 📁 Project Structure

```
quantamental/
│
├── data/                   # [GitIgnored] Market data cache
│   ├── price/              # Parquet files (NVDA.parquet, SPY.parquet, etc.)
│   └── fundamentals/       # Future: earnings/sales data
│
├── database/               # [GitIgnored] SQLite databases
│   └── trades.db           # Watchlist & trade log
│
├── src/                    # Core OOP modules
│   ├── __init__.py
│   ├── data_engine.py      # DataRepository class
│   ├── indicators.py       # TechnicalAnalysis class
│   ├── strategy.py         # SEPAStrategy class
│   ├── backtester.py       # BacktestEngine & PortfolioManager
│   ├── reporting.py        # PerformanceReporter class
│   └── database.py         # DatabaseManager class
│
├── notebooks/              # Jupyter notebooks for research
│
├── config.py               # Central configuration
├── main_scanner.py         # Daily scanner script
├── main_backtest.py        # Backtesting script
├── requirements.txt        # Dependencies
└── README.md               # This file
```

## 🚀 Quick Start

### 1. Installation

```bash
# Clone or navigate to project directory
cd quantamental

# Install dependencies
pip install -r requirements.txt
```

### 2. Run Daily Scanner

Scans S&P 500 for SEPA setups and updates watchlist database:

```bash
python main_scanner.py
```

**Output:**
- List of stocks triggering buy signals today
- Entry/stop/target prices with ATR-based trade plan
- Watchlist summary (stocks in setup phase)

### 3. Run Backtest

Tests strategy performance on historical data:

```bash
# Full backtest (all S&P 500 stocks)
python main_backtest.py

# Quick test with 50 stocks
python main_backtest.py --subset 50

# Skip HTML report generation
python main_backtest.py --no-report
```

**Output:**
- Performance metrics (Sharpe, Win Rate, Max Drawdown, etc.)
- Equity curve visualization
- Trade log CSV
- HTML performance report

## ⚙️ Configuration

All strategy parameters are in [`config.py`](config.py):

### Key Settings

| Parameter | Default | Description |
|-----------|---------|-------------|
| `INITIAL_CAPITAL` | $100,000 | Starting portfolio size |
| `MAX_POSITIONS` | 8 | Maximum concurrent positions |
| `POSITION_SIZE_PCT` | 12.5% | Fixed position size (1/8 of capital) |
| `STOP_LOSS_PCT` | 8% | Hard stop loss |
| `PROFIT_TARGET_R` | 3.0 | Profit target (3x risk) |
| `VOL_SPIKE_THRESHOLD` | 1.3 | Volume must be 130% of average |
| `CONSOLIDATION_PERIOD` | 20 | Breakout of 20-day high |

### Data Settings

| Parameter | Default | Description |
|-----------|---------|-------------|
| `LOOKBACK_PERIOD` | 2 years | History for 200-day MA calculation |
| `BATCH_SIZE` | 50 | Download batch size |
| `DATA_CACHE_DAYS` | 1 | Re-download if data older than N days |

## 📊 Strategy Overview (SEPA)

The system implements Mark Minervini's **Specific Entry Point Analysis**:

### 1. Trend Filter (Stage 2 Uptrend)
- Price > 150 SMA > 200 SMA
- 150 SMA > 200 SMA
- 200 SMA trending up
- Price > 50 SMA
- Price > 30% above 52-week low
- Price within 25% of 52-week high

### 2. Structure (VCP - Volatility Contraction Pattern)
- Price breaking above 20-day high
- Volume spike (>130% of 50-day average)

### 3. Confirmation (Relative Strength)
- Stock outperforming SPY benchmark

### 4. Risk Management
- Fixed 8% stop loss
- 3R profit target (24% gain)
- Max 8 concurrent positions
- 12.5% position sizing (fixed fractional)

## 🧪 Example Usage

### Python API

```python
from src.data_engine import DataRepository
from src.strategy import SEPAStrategy
from src.backtester import BacktestEngine, PortfolioManager

# Initialize
data_repo = DataRepository()
tickers = data_repo.update_universe()

# Get data
benchmark = data_repo.get_benchmark_data()
strategy = SEPAStrategy(benchmark_data=benchmark)

# Run backtest
portfolio = PortfolioManager()
engine = BacktestEngine(strategy, portfolio)
trades_df, equity = engine.run(price_data)

# Generate report
from src.reporting import PerformanceReporter
reporter = PerformanceReporter(trades_df, equity)
reporter.print_summary()
reporter.plot_performance()
```

### Database Access

```python
from src.database import DatabaseManager

db = DatabaseManager()

# Get current watchlist
watchlist = db.get_watchlist(active_only=True)
print(watchlist)

# Get trade history
trades = db.get_trade_history(closed_only=True)
print(trades)

# Performance summary
summary = db.get_performance_summary()
print(summary)
```

## 📈 Performance Metrics

The system calculates:

- **Total Return**: Overall portfolio performance
- **CAGR**: Compound Annual Growth Rate
- **Sharpe Ratio**: Risk-adjusted returns
- **Sortino Ratio**: Downside risk-adjusted returns
- **Max Drawdown**: Largest peak-to-trough decline
- **Win Rate**: Percentage of profitable trades
- **Profit Factor**: Gross profit / gross loss
- **Expectancy**: Average trade outcome

## 🗄️ Database Schema

### Watchlist Table
Tracks stocks in setup phase:

| Column | Type | Description |
|--------|------|-------------|
| ticker | TEXT | Stock symbol (primary key) |
| first_seen | DATE | First date in setup |
| last_seen | DATE | Most recent scan date |
| days_on_watchlist | INT | Days in setup phase |
| avg_rs | REAL | Average relative strength |
| avg_volume_ratio | REAL | Average volume ratio |
| status | TEXT | 'active', 'removed', 'stale' |

### Trades Table
Historical trade log:

| Column | Type | Description |
|--------|------|-------------|
| ticker | TEXT | Stock symbol |
| entry_date | DATE | Entry date |
| entry_price | REAL | Entry price |
| exit_date | DATE | Exit date |
| exit_price | REAL | Exit price |
| shares | INT | Position size |
| pnl_dollars | REAL | Profit/loss in $ |
| pnl_percent | REAL | Profit/loss in % |
| exit_reason | TEXT | 'Stop Loss', 'Trend Break', etc. |

## 🔮 Future Enhancements (Roadmap)

### Phase 5: Machine Learning Integration
- [ ] Meta-labeling with Random Forest
- [ ] Feature importance analysis
- [ ] Probability-based signal scoring (0-100%)
- [ ] Dynamic position sizing based on ML confidence

### Fundamental Data
- [ ] Earnings growth filters
- [ ] Sales growth filters
- [ ] Sector rotation analysis

### Advanced Features
- [ ] Real-time scanning (scheduled jobs)
- [ ] Email/Slack alerts for new setups
- [ ] Multi-timeframe analysis
- [ ] Advanced exit strategies (trailing stops, partial profits)

### Performance Optimizations
- [ ] Parallel processing for faster scans
- [ ] Database indexing for faster queries
- [ ] GPU acceleration for ML models

## 🛠️ Development

### Adding Custom Indicators

Edit [`src/indicators.py`](src/indicators.py):

```python
class TechnicalAnalysis:
    @staticmethod
    def add_custom_indicator(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        # Your indicator logic here
        df['Custom'] = ...
        return df
```

### Modifying Strategy Logic

Edit [`src/strategy.py`](src/strategy.py):

```python
class SEPAStrategy(AlphaModel):
    def screen_candidates(self, df, date):
        # Modify screening criteria
        pass
```

### Adjusting Risk Parameters

Edit [`config.py`](config.py):

```python
STOP_LOSS_PCT = 0.10  # Change to 10% stop
PROFIT_TARGET_R = 2.0  # Change to 2R target
MAX_POSITIONS = 10     # Allow 10 positions
```

## 📝 Notes

- **Data Source**: Uses `yfinance` for historical data (free, no API key required)
- **Universe**: S&P 500 from State Street SSGA ETF holdings
- **Timezone**: All dates are in market timezone (US/Eastern)
- **Commission**: Currently set to $0 (modern brokers). Update in config for realistic modeling.
- **Slippage**: Not currently modeled. TODO in config.py for future implementation.

## 📄 License

This is a personal trading system. Use at your own risk. No warranty or guarantee of profitability.

## 🙏 Acknowledgments

Strategy based on:
- **Mark Minervini**: SEPA methodology, VCP patterns
- **Marcos López de Prado**: Risk management, meta-labeling concepts

## 📧 Support

For issues or questions, please open an issue in the repository.

---

**Disclaimer**: This system is for educational and research purposes only. Past performance does not guarantee future results. Always perform your own due diligence before trading.
