import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import sys

# ==============================================================================
# 1. CONFIGURATION
# ==============================================================================
BENCHMARK = 'SPY'
LOOKBACK_PERIOD = "2y"         # Need 1-2 years for 200 SMA calculation

# Minervini / SEPA Criteria
STOP_LOSS_PCT = 0.08           # 8% Hard Stop
TARGET_RATIO = 3.0             # Aim for 3x Risk (approx 24% gain)
VOL_SPIKE_THRESH = 1.3         # Volume > 130% of 50-day average
CONSOLIDATION_PERIOD = 20      # Breakout of 20-day High
BATCH_SIZE = 50                # Batch download size

# ==============================================================================
# 2. DATA ENGINE (SSGA Source)
# ==============================================================================
def get_sp500_tickers():
    print("--- 1. Fetching S&P 500 Tickers from SSGA ---")
    url = 'https://www.ssga.com/us/en/intermediary/etfs/library-content/products/fund-data/etfs/us/holdings-daily-us-en-spy.xlsx'
    try:
        df = pd.read_excel(url, engine='openpyxl', skiprows=4)
        tickers = df['Ticker'].dropna().tolist()
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
    """Extracts 'Close' series from potentially messy yfinance DataFrame."""
    if df is None or df.empty: return None
    if isinstance(df, pd.Series): return df

    # Try standard columns
    if 'Close' in df.columns:
        if isinstance(df['Close'], pd.DataFrame): return df['Close'].iloc[:, 0]
        return df['Close']

    # Try MultiIndex
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
            if ticker in data.columns.levels[0]:
                df = data[ticker].copy()
            else: return None
        else:
            if ticker == data.columns.name or len(data.columns) > 0:
                df = data.copy()
            else: return None

        if isinstance(df['Close'], pd.DataFrame): df['Close'] = df['Close'].iloc[:, 0]
        return df.dropna(subset=['Close'])
    except: return None

# ==============================================================================
# 3. SCANNER LOGIC
# ==============================================================================
def analyze_ticker(df, spy_series):
    """Returns a dictionary if BUY signal found, else None."""
    close = safe_extract_close(df)

    # Volume check
    if 'Volume' in df.columns: volume = df['Volume']
    elif isinstance(df.columns, pd.MultiIndex) and 'Volume' in df.columns.get_level_values(1):
         volume = df.xs('Volume', axis=1, level=1).iloc[:,0]
    else: return None

    if close is None or volume is None or len(close) < 50: return None

    # Align SPY
    spy_aligned = spy_series.reindex(close.index).ffill()

    # --- CALCULATE INDICATORS ---
    sma_50 = close.rolling(50).mean()
    sma_150 = close.rolling(150).mean()
    sma_200 = close.rolling(200).mean()

    # --- LOGIC: LATEST DAY ONLY ---
    # We only care about the LAST available bar (Today)
    curr_close = close.iloc[-1]
    curr_vol = volume.iloc[-1]
    curr_date = close.index[-1]

    # 1. Trend Template (Stage 2)
    if len(close) < 260: # Recent IPO Logic
        trend_ok = (curr_close > sma_50.iloc[-1]) and (curr_close > close.rolling(20).mean().iloc[-1])
    else:
        c1 = curr_close > sma_150.iloc[-1] and curr_close > sma_200.iloc[-1]
        c2 = sma_150.iloc[-1] > sma_200.iloc[-1]
        c3 = sma_200.iloc[-1] > sma_200.iloc[-20] # Rising 200
        c4 = curr_close > sma_50.iloc[-1]
        c5 = curr_close > close.rolling(252).min().iloc[-1] * 1.3 # 30% above lows
        c6 = curr_close > close.rolling(252).max().iloc[-1] * 0.75 # Near highs
        trend_ok = c1 and c2 and c3 and c4 and c5 and c6

    if not trend_ok: return None

    # 2. Breakout (Price > Highest High of prev 20 days)
    # Note: Shift(1) because we want to see if TODAY broke previous range
    prev_20_high = close.shift(1).rolling(CONSOLIDATION_PERIOD).max().iloc[-1]
    breakout = curr_close > prev_20_high

    if not breakout: return None

    # 3. Volume Spike
    avg_vol_50 = volume.shift(1).rolling(50).mean().iloc[-1]
    vol_ok = curr_vol > (avg_vol_50 * VOL_SPIKE_THRESH)

    if not vol_ok: return None

    # 4. Relative Strength (vs SPY)
    rs = close / spy_aligned
    rs_avg = rs.rolling(63).mean()
    rs_ok = rs.iloc[-1] > rs_avg.iloc[-1]

    if not rs_ok: return None

    # --- SUCCESS! CALCULATE TRADE PLAN ---
    stop_price = curr_close * (1 - STOP_LOSS_PCT)
    risk = curr_close - stop_price
    target_price = curr_close + (risk * TARGET_RATIO)

    return {
        'Date': curr_date.strftime('%Y-%m-%d'),
        'Ticker': df.columns.name if df.columns.name else "UNK", # Ticker Name
        'Price': curr_close,
        'Stop Loss (-8%)': stop_price,
        'Take Profit (+24%)': target_price,
        'Volume Ratio': f"{curr_vol/avg_vol_50:.1f}x",
        'RS Rating': "Pass"
    }

# ==============================================================================
# 4. MAIN JOB
# ==============================================================================
def run_scanner():
    print("="*60)
    print(f" SEPA DAILY SCANNER | {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("="*60)

    tickers = get_sp500_tickers()
    # tickers = tickers[:50] # Uncomment for quick test

    print(f"--- 2. Downloading Market Data ({LOOKBACK_PERIOD})... ---")
    # Download SPY first
    spy_data = yf.download(BENCHMARK, period=LOOKBACK_PERIOD, progress=False, auto_adjust=True)
    spy_close = safe_extract_close(spy_data)

    candidates = []

    # Batch Processing
    total_chunks = len(tickers) // BATCH_SIZE + 1
    for i in range(0, len(tickers), BATCH_SIZE):
        batch = tickers[i : i + BATCH_SIZE]
        sys.stdout.write(f"\rProcessing Batch {i//BATCH_SIZE + 1}/{total_chunks}...")
        sys.stdout.flush()

        try:
            data = yf.download(batch, period=LOOKBACK_PERIOD, group_by='ticker', auto_adjust=True, progress=False, threads=True)

            for t in batch:
                df = get_single_ticker_data(data, t)
                if df is None: continue
                df.columns.name = t # Ensure ticker name is preserved

                res = analyze_ticker(df, spy_close)
                if res:
                    candidates.append(res)
        except Exception:
            continue

    print("\n\n" + "="*80)
    print(f"SCAN COMPLETE: Found {len(candidates)} Candidates")
    print("="*80)

    if candidates:
        results_df = pd.DataFrame(candidates)

        # Reorder columns
        cols = ['Date', 'Ticker', 'Price', 'Stop Loss (-8%)', 'Take Profit (+24%)', 'Volume Ratio']
        results_df = results_df[cols]

        print(results_df.to_string(index=False, float_format=lambda x: "{:.2f}".format(x)))

        print("\nNOTE: 'Take Profit' is a 3:1 guideline. Consider trailing stop (50 SMA) for runners.")
    else:
        print("No setups found today. Market may be chopping or extended.")

if __name__ == "__main__":
    run_scanner()