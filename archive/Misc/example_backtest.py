import yfinance as yf
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import requests
import io
import gc

# ==============================================================================
# 1. CONFIGURATION
# ==============================================================================
BENCHMARK = 'SPY'
START_DATE = '2020-01-01'
BACKTEST_START = '2021-01-01'

# Strategy Risk Settings
ACCOUNT_SIZE = 100000          # Starting Capital
ACCOUNT_RISK_PER_TRADE = 0.01  # Risk 1% of equity per trade
STOP_LOSS_PCT = 0.08           # 8% Hard Stop (Fixed as requested)
VOL_SPIKE_THRESH = 1.3         # Volume > 130% of average
CONSOLIDATION_PERIOD = 20      # Breakout of 20-day High
BATCH_SIZE = 30                # Batch size for stability

# ==============================================================================
# 2. ROBUST DATA ENGINE
# ==============================================================================
def safe_extract_close(df):
    """Safely finds 'Close' column in messy yfinance DataFrames."""
    if df is None or df.empty: return None
    if isinstance(df, pd.Series): return df

    if 'Close' in df.columns:
        if isinstance(df['Close'], pd.DataFrame):
            return df['Close'].iloc[:, 0]
        return df['Close']

    if isinstance(df.columns, pd.MultiIndex):
        for i in range(df.columns.nlevels):
            if 'Close' in df.columns.get_level_values(i):
                try:
                    slice_df = df.xs('Close', axis=1, level=i)
                    if len(slice_df.columns) == 1: return slice_df.iloc[:, 0]
                    return slice_df
                except: continue

    if 'Adj Close' in df.columns: return df['Adj Close']
    if len(df.columns) == 1: return df.iloc[:, 0]
    return None

def get_sp500_tickers():
    print("Fetching S&P 500 holdings from SSGA (SPY ETF)...")
    url = 'https://www.ssga.com/us/en/intermediary/etfs/library-content/products/fund-data/etfs/us/holdings-daily-us-en-spy.xlsx'
    try:
        df = pd.read_excel(url, engine='openpyxl', skiprows=4)
        tickers = df['Ticker'].dropna().tolist()
        clean = [str(t).strip().replace('.', '-') for t in tickers if str(t).strip() not in ['CASH_USD', '']]
        print(f"Successfully loaded {len(clean)} unique tickers.")
        return list(set(clean))
    except Exception as e:
        print(f"Error fetching list: {e}. Using Fallback.")
        return ['NVDA', 'AAPL', 'MSFT', 'AMZN', 'GOOGL', 'META', 'TSLA', 'AMD', 'JPM', 'LLY', 'AVGO', 'V', 'MA']

def download_robust(tickers):
    print(f"   Downloading batch of {len(tickers)} tickers...")
    try:
        data = yf.download(tickers, start=START_DATE, group_by='ticker', auto_adjust=True, progress=False, threads=True)
        return data
    except Exception:
        return pd.DataFrame()

def get_single_ticker_data(data, ticker):
    try:
        if isinstance(data.columns, pd.MultiIndex):
            if ticker in data.columns.levels[0]:
                df = data[ticker].copy()
            else: return None
        else:
            if ticker == data.columns.name or len(data.columns) > 0:
                df = data.copy()
            else: return None

        if isinstance(df['Close'], pd.DataFrame):
            df['Close'] = df['Close'].iloc[:, 0]
        return df.dropna(subset=['Close'])
    except: return None

# ==============================================================================
# 3. SEPA SIGNAL LOGIC
# ==============================================================================
def calculate_sepa_signals(df, spy_series):
    close = safe_extract_close(df)
    if 'Volume' in df.columns: volume = df['Volume']
    elif isinstance(df.columns, pd.MultiIndex) and 'Volume' in df.columns.get_level_values(1):
         volume = df.xs('Volume', axis=1, level=1).iloc[:,0]
    else: return None, None

    if close is None or volume is None: return None, None

    spy_aligned = spy_series.reindex(close.index).ffill()

    # Trend
    sma_50 = close.rolling(50).mean()
    sma_150 = close.rolling(150).mean()
    sma_200 = close.rolling(200).mean()

    if len(close) < 260:
        c_trend = (close > sma_50) & (close > close.rolling(20).mean())
    else:
        c1 = (close > sma_150) & (close > sma_200)
        c2 = (sma_150 > sma_200)
        c3 = sma_200 > sma_200.shift(20)
        c4 = close > sma_50
        c5 = close > close.rolling(252).min() * 1.3
        c_trend = c1 & c2 & c3 & c4 & c5

    # Breakout & Volume
    rolling_high = close.shift(1).rolling(CONSOLIDATION_PERIOD).max()
    breakout = (close > rolling_high)
    vol_spike = volume > (volume.shift(1).rolling(50).mean() * VOL_SPIKE_THRESH)

    # RS
    rs = close / spy_aligned
    rs_ok = rs > rs.rolling(63).mean()

    buy = c_trend & breakout & vol_spike & rs_ok
    sell = close < sma_50

    return buy, sell

# ==============================================================================
# 4. BACKTEST EXECUTION
# ==============================================================================
def run_sp500_backtest():
    tickers = get_sp500_tickers()
    print("Downloading Benchmark (SPY)...")
    spy_data = yf.download(BENCHMARK, start=START_DATE, progress=False, auto_adjust=True)
    spy_close = safe_extract_close(spy_data)

    if spy_close is None: return pd.DataFrame(), pd.DataFrame()

    closed_trades = []
    open_trades = [] # New list for active positions

    total_chunks = len(tickers) // BATCH_SIZE + 1
    for i in range(0, len(tickers), BATCH_SIZE):
        batch = tickers[i : i + BATCH_SIZE]
        print(f"Processing Batch {i//BATCH_SIZE + 1}/{total_chunks}...")
        batch_data = download_robust(batch)

        if batch_data.empty: continue

        for ticker in batch:
            df = get_single_ticker_data(batch_data, ticker)
            if df is None or len(df) < 50: continue

            try:
                buy, sell = calculate_sepa_signals(df, spy_close)
                if buy is None: continue

                sim = pd.DataFrame({'Close': safe_extract_close(df), 'Low': df['Low'], 'Buy': buy, 'Sell': sell}).loc[BACKTEST_START:]
                if sim.empty: continue

                in_pos = False; entry_price = 0; entry_date = None; size_pct = 0; stop_price = 0

                for date, row in sim.iterrows():
                    if not in_pos:
                        if row['Buy']:
                            in_pos = True
                            entry_price = row['Close']
                            entry_date = date
                            stop_price = entry_price * (1 - STOP_LOSS_PCT)
                            risk_per_share = entry_price - stop_price
                            size_pct = (ACCOUNT_RISK_PER_TRADE / (risk_per_share/entry_price)) if risk_per_share > 0 else 0
                    else:
                        exit_reason = None
                        exit_price = 0
                        if row['Low'] < stop_price:
                            exit_price = stop_price; exit_reason = 'Stop Loss'
                        elif row['Sell']:
                            exit_price = row['Close']; exit_reason = 'Trend Break'

                        if exit_reason:
                            pnl = (exit_price - entry_price) / entry_price
                            closed_trades.append({
                                'Ticker': ticker, 'Entry Date': entry_date, 'Exit Date': date,
                                'Size %': round(size_pct * 100, 1), 'Entry': round(entry_price, 2),
                                'Exit': round(exit_price, 2), 'PnL %': round(pnl * 100, 2),
                                'Reason': exit_reason
                            })
                            in_pos = False

                # Check for Open Position at end of simulation
                if in_pos:
                    current_price = sim.iloc[-1]['Close']
                    unrealized_pnl = (current_price - entry_price) / entry_price
                    open_trades.append({
                        'Ticker': ticker,
                        'Entry Date': entry_date,
                        'Entry': round(entry_price, 2),
                        'Current': round(current_price, 2),
                        'Size %': round(size_pct * 100, 1),
                        'Unrealized PnL %': round(unrealized_pnl * 100, 2),
                        'Stop Price': round(stop_price, 2)
                    })

            except: continue
        del batch_data; gc.collect()

    return pd.DataFrame(closed_trades), pd.DataFrame(open_trades)

# ==============================================================================
# 5. COMPREHENSIVE REPORTING
# ==============================================================================
if __name__ == "__main__":
    trades, open_positions = run_sp500_backtest()

    if not trades.empty:
        trades = trades.sort_values('Entry Date')

        # --- 1. METRICS ---
        wins = trades[trades['PnL %'] > 0]
        losses = trades[trades['PnL %'] <= 0]

        win_rate = len(wins) / len(trades)
        avg_win = wins['PnL %'].mean() if not wins.empty else 0
        avg_loss = losses['PnL %'].mean() if not losses.empty else 0
        profit_factor = abs(wins['PnL %'].sum() / losses['PnL %'].sum()) if not losses.empty else 0

        # Build Equity Curve (Closed Trades Only for Realized Equity)
        equity_series = pd.Series(index=trades['Exit Date'].unique(), data=0.0).sort_index()
        running_balance = ACCOUNT_SIZE

        for date in equity_series.index:
            closing = trades[trades['Exit Date'] == date]
            day_pnl = sum(running_balance * (t['Size %']/100) * (t['PnL %']/100) for _, t in closing.iterrows())
            running_balance += day_pnl
            equity_series[date] = running_balance

        equity_curve = equity_series.reindex(pd.date_range(start=trades['Entry Date'].min(), end=trades['Exit Date'].max())).ffill().fillna(ACCOUNT_SIZE)

        # Drawdown
        rolling_max = equity_curve.cummax()
        drawdown = (equity_curve - rolling_max) / rolling_max
        max_drawdown = drawdown.min()
        total_return = (running_balance / ACCOUNT_SIZE) - 1

        # --- 2. TEXT REPORT ---
        print("\n" + "="*60)
        print(f"SEPA STRATEGY PERFORMANCE REPORT (S&P 500)")
        print("="*60)
        print(f"Time Period:      {BACKTEST_START} to Present")
        print(f"Start Capital:    ${ACCOUNT_SIZE:,.0f}")
        print(f"Realized Cap:     ${running_balance:,.0f}")
        print("-" * 60)
        print(f"Total Return:     {total_return:.2%}")
        print(f"Max Drawdown:     {max_drawdown:.2%}")
        print(f"Total Trades:     {len(trades)}")
        print(f"Win Rate:         {win_rate:.1%}")
        print(f"Profit Factor:    {profit_factor:.2f}")
        print(f"Avg Win:          {avg_win:.2f}%")
        print(f"Avg Loss:         {avg_loss:.2f}%")
        print("="*60)

        # --- 3. OPEN POSITIONS ---
        if not open_positions.empty:
            print("\n🟢 CURRENT OPEN POSITIONS:")
            print(open_positions.sort_values('Unrealized PnL %', ascending=False).to_string(index=False))
        else:
            print("\n⚪ NO OPEN POSITIONS")

        # --- 4. TOP WINNERS & LOSERS ---
        print("\n🏆 TOP 5 WINNERS (Hall of Fame):")
        print(trades.sort_values('PnL %', ascending=False).head(5)[['Ticker', 'Entry Date', 'Exit Date', 'PnL %', 'Reason']].to_string(index=False))

        print("\n🛑 TOP 5 LOSERS (Hall of Shame):")
        print(trades.sort_values('PnL %', ascending=True).head(5)[['Ticker', 'Entry Date', 'Exit Date', 'PnL %', 'Reason']].to_string(index=False))

        # --- 5. VISUALIZATIONS ---
        fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(12, 15))

        # Chart 1: Equity Curve
        ax1.plot(equity_curve.index, equity_curve.values, color='blue', lw=1.5)
        ax1.axhline(y=ACCOUNT_SIZE, color='red', linestyle='--', alpha=0.5, label='Start')
        ax1.set_title(f'Realized Equity Curve (Final: ${running_balance:,.0f})', fontsize=12, fontweight='bold')
        ax1.set_ylabel('Portfolio Value ($)')
        ax1.grid(True, alpha=0.3)

        # Chart 2: Underwater Plot (Drawdown)
        ax2.fill_between(drawdown.index, drawdown.values, 0, color='red', alpha=0.3)
        ax2.plot(drawdown.index, drawdown.values, color='red', lw=1)
        ax2.set_title(f'Drawdown (Max: {max_drawdown:.2%})', fontsize=12, fontweight='bold')
        ax2.set_ylabel('Drawdown %')
        ax2.grid(True, alpha=0.3)

        # Chart 3: PnL Distribution (Histogram)
        sns.histplot(trades['PnL %'], bins=50, kde=True, ax=ax3, color='green')
        ax3.axvline(0, color='black', linestyle='--')
        ax3.set_title('Trade PnL Distribution (Fat Tail Check)', fontsize=12, fontweight='bold')
        ax3.set_xlabel('PnL %')

        plt.tight_layout()
        plt.show()

    else:
        print("No trades found. Criteria may be too strict or data download failed.")