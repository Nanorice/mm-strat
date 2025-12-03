import yfinance as yf
import pandas as pd
import numpy as np
import requests
import io
import sys
from datetime import datetime

# ==============================================================================
# 1. SETTINGS
# ==============================================================================
BENCHMARK = 'SPY'
LOOKBACK_PERIOD = "2y"         # Need history for 200-day MA

# SEPA Criteria
VOL_SPIKE_THRESH = 1.3         # Volume must be 130% of average
CONSOLIDATION_PERIOD = 20      # Breakout of 20-day High

# ATR Risk Management
ATR_PERIOD = 14
ATR_STOP_MULT = 2.5            # Stop Loss = 2.5x ATR
TARGET_RISK_RATIO = 3.0        # Take Profit = 3x Risk

# System
BATCH_SIZE = 50                # Download batch size

# ==============================================================================
# 2. ROBUST DATA ENGINE
# ==============================================================================
def get_sp500_tickers():
    print("--- 1. Fetching S&P 500 List from SSGA ---")
    url = 'https://www.ssga.com/us/en/intermediary/etfs/library-content/products/fund-data/etfs/us/holdings-daily-us-en-spy.xlsx'
    try:
        df = pd.read_excel(url, engine='openpyxl', skiprows=4)
        tickers = df['Ticker'].dropna().tolist()
        # Clean tickers (remove cash, fix BRK.B -> BRK-B)
        clean_tickers = []
        for t in tickers:
            t = str(t).strip()
            if len(t) > 0 and t != 'CASH_USD' and len(t) <= 5:
                clean_tickers.append(t.replace('.', '-'))
        print(f"Successfully loaded {len(clean_tickers)} tickers.")
        return list(set(clean_tickers))
    except Exception as e:
        print(f"Error fetching list: {e}. Using Backup Tech List.")
        return ['NVDA', 'AAPL', 'MSFT', 'AMZN', 'GOOGL', 'META', 'TSLA', 'AMD', 'PLTR', 'SMCI']

def safe_extract_close(df):
    """Safely extracts 'Close' column from messy yfinance data."""
    if df is None or df.empty: return None
    if isinstance(df, pd.Series): return df

    # Standard Column
    if 'Close' in df.columns:
        if isinstance(df['Close'], pd.DataFrame): return df['Close'].iloc[:, 0]
        return df['Close']

    # MultiIndex Handling
    if isinstance(df.columns, pd.MultiIndex):
        for i in range(df.columns.nlevels):
            if 'Close' in df.columns.get_level_values(i):
                try:
                    slice_df = df.xs('Close', axis=1, level=i)
                    if len(slice_df.columns) == 1: return slice_df.iloc[:, 0]
                    return slice_df
                except: continue
    return None

def get_single_ticker_data(data, ticker):
    try:
        if isinstance(data.columns, pd.MultiIndex):
            if ticker in data.columns.levels[0]: df = data[ticker].copy()
            else: return None
        else:
            if ticker == data.columns.name or len(data.columns) > 0: df = data.copy()
            else: return None

        if isinstance(df['Close'], pd.DataFrame): df['Close'] = df['Close'].iloc[:, 0]
        return df.dropna(subset=['Close'])
    except: return None

# ==============================================================================
# 3. INDICATOR LOGIC
# ==============================================================================
def calculate_atr(df, period=14):
    high = df['High']
    low = df['Low']
    close = df['Close']
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def analyze_ticker(df, spy_series):
    """Checks if ticker meets SEPA criteria TODAY."""
    close = safe_extract_close(df)
    if 'Volume' in df.columns: volume = df['Volume']
    elif isinstance(df.columns, pd.MultiIndex): volume = df.xs('Volume', axis=1, level=1).iloc[:,0]
    else: return None

    if close is None or volume is None or len(close) < 50: return None

    # 1. Calculate Metrics
    atr_series = calculate_atr(df, ATR_PERIOD)
    spy_aligned = spy_series.reindex(close.index).ffill()

    sma_50 = close.rolling(50).mean()
    sma_150 = close.rolling(150).mean()
    sma_200 = close.rolling(200).mean()

    # Get Latest Data Point
    curr_close = close.iloc[-1]
    curr_vol = volume.iloc[-1]
    curr_atr = atr_series.iloc[-1]

    # 2. Trend Check (Stage 2)
    if len(close) < 260: # IPO/New Stock Logic
        trend_ok = (curr_close > sma_50.iloc[-1]) and (curr_close > close.rolling(20).mean().iloc[-1])
    else:
        c1 = curr_close > sma_150.iloc[-1] and curr_close > sma_200.iloc[-1]
        c2 = sma_150.iloc[-1] > sma_200.iloc[-1]
        c3 = sma_200.iloc[-1] > sma_200.iloc[-20] # Rising 200d
        c4 = curr_close > sma_50.iloc[-1]
        c5 = curr_close > close.rolling(252).min().iloc[-1] * 1.3 # 30% above lows
        c6 = curr_close > close.rolling(252).max().iloc[-1] * 0.75 # Near highs
        trend_ok = c1 and c2 and c3 and c4 and c5 and c6

    if not trend_ok: return None

    # 3. Breakout Check (20-Day High)
    # We check if today's close is higher than the MAX of the previous 20 days
    prev_20_high = close.shift(1).rolling(CONSOLIDATION_PERIOD).max().iloc[-1]
    breakout = curr_close > prev_20_high

    if not breakout: return None

    # 4. Volume Spike Check
    avg_vol_50 = volume.shift(1).rolling(50).mean().iloc[-1]
    vol_ok = curr_vol > (avg_vol_50 * VOL_SPIKE_THRESH)

    if not vol_ok: return None

    # 5. Relative Strength Check
    rs = close / spy_aligned
    rs_avg = rs.rolling(63).mean()
    rs_ok = rs.iloc[-1] > rs_avg.iloc[-1]

    if not rs_ok: return None

    # --- CALCULATE TRADE PLAN (ATR) ---
    stop_dist = curr_atr * ATR_STOP_MULT
    stop_price = curr_close - stop_dist
    risk = curr_close - stop_price
    target_price = curr_close + (risk * TARGET_RISK_RATIO)
    stop_pct = (risk / curr_close) * 100

    return {
        'Ticker': df.columns.name if df.columns.name else "UNK",
        'Price': curr_close,
        'ATR': curr_atr,
        'Stop Price': stop_price,
        'Stop %': f"-{stop_pct:.2f}%",
        'Target Price': target_price,
        'Vol Ratio': f"{curr_vol/avg_vol_50:.1f}x"
    }

# ==============================================================================
# 4. JOB EXECUTION
# ==============================================================================
def run_daily_job():
    print("="*70)
    print(f" SEPA DAILY SCANNER (ATR EDITION) | {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("="*70)

    # 1. Get Tickers
    tickers = get_sp500_tickers()

    # 2. Get Benchmark Data
    print(f"--- 2. Downloading Market Data ({LOOKBACK_PERIOD}) ---")
    spy_data = yf.download(BENCHMARK, period=LOOKBACK_PERIOD, progress=False, auto_adjust=True)
    spy_close = safe_extract_close(spy_data)

    if spy_close is None:
        print("CRITICAL ERROR: Could not download SPY data.")
        return

    # 3. Scan in Batches
    candidates = []
    total = len(tickers)
    print(f"Scanning {total} tickers...")

    for i in range(0, total, BATCH_SIZE):
        batch = tickers[i : i + BATCH_SIZE]
        # Progress bar
        sys.stdout.write(f"\rProcessing {i + len(batch)}/{total}...")
        sys.stdout.flush()

        try:
            data = yf.download(batch, period=LOOKBACK_PERIOD, group_by='ticker', auto_adjust=True, progress=False, threads=True)

            for t in batch:
                df = get_single_ticker_data(data, t)
                if df is None: continue
                df.columns.name = t

                res = analyze_ticker(df, spy_close)
                if res:
                    candidates.append(res)
        except Exception:
            continue

    print("\n\n" + "="*70)
    print(f"SCAN RESULTS: Found {len(candidates)} Trades")
    print("="*70)

    if candidates:
        df_res = pd.DataFrame(candidates)
        # Reorder for readability
        cols = ['Ticker', 'Price', 'Stop Price', 'Stop %', 'Target Price', 'Vol Ratio']
        print(df_res[cols].to_string(index=False, float_format=lambda x: "{:.2f}".format(x)))
        print("-" * 70)
        print("EXECUTION NOTES:")
        print("1. ENTRY: Market Buy at Open (or if Price holds > 20d High).")
        print("2. STOP:  Hard Stop at 'Stop Price'.")
        print("3. EXIT:  Sell 50% at 'Target Price', trail rest on 50-day SMA.")
    else:
        print("No setups found today. Market is likely chopping or consolidating.")

if __name__ == "__main__":
    run_daily_job()