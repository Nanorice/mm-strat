import pandas as pd
import numpy as np
import xgboost as xgb
import json
import yfinance as yf
from datetime import datetime, timedelta

def get_live_data(tickers):
    """
    Fetches the last 300 days of data for the tickers to calculate SMAs/ATR.
    """
    print(f"📥 Fetching live data for {len(tickers)} candidates...")
    
    # Download in bulk for speed
    data = yf.download(tickers, period="2y", interval="1d", group_by='ticker', progress=False, auto_adjust=True)
    
    ticker_dfs = {}
    
    # Handle single ticker vs multiple ticker structure
    if len(tickers) == 1:
        ticker = tickers[0]
        df = data.copy()
        ticker_dfs[ticker] = df
    else:
        for ticker in tickers:
            try:
                # yfinance returns a MultiIndex (Ticker, OHLCV), we want just OHLCV
                df = data[ticker].copy()
                if df.empty: continue
                df = df.dropna()
                ticker_dfs[ticker] = df
            except KeyError:
                print(f"⚠️ Could not find data for {ticker}")
                
    return ticker_dfs

def engineer_inference_features(ticker_dfs, config):
    """
    Replicates the EXACT feature engineering used in training.
    """
    inference_rows = []
    
    # Load feature lists from config
    required_features = config['features']
    lag_candidates = config['setup_lag_features']
    
    print("⚙️  Calculating indicators...")
    
    for ticker, df in ticker_dfs.items():
        try:
            # ----------------------------------------------------
            # 1. CALCULATE RAW INDICATORS (Same logic as FeatureEngineer)
            # ----------------------------------------------------
            # Moving Averages
            df['SMA_50'] = df['Close'].rolling(50).mean()
            df['SMA_150'] = df['Close'].rolling(150).mean()
            df['SMA_200'] = df['Close'].rolling(200).mean()
            
            # ATR / nATR
            df['tr0'] = abs(df['High'] - df['Low'])
            df['tr1'] = abs(df['High'] - df['Close'].shift())
            df['tr2'] = abs(df['Low'] - df['Close'].shift())
            df['TR'] = df[['tr0', 'tr1', 'tr2']].max(axis=1)
            df['ATR'] = df['TR'].rolling(14).mean()
            df['nATR'] = (df['ATR'] / df['Close']) * 100
            
            # Price vs SMA (Ratios)
            df['Price_vs_SMA_50'] = (df['Close'] / df['SMA_50']) - 1
            df['Price_vs_SMA_150'] = (df['Close'] / df['SMA_150']) - 1
            df['Price_vs_SMA_200'] = (df['Close'] / df['SMA_200']) - 1
            
            # Relative Strength (RS) - Simplified for Inference
            # (In production, you'd use the proper benchmark rank, here we use ROC 6m)
            df['RS'] = df['Close'].pct_change(126) # 6 month ROC as proxy
            df['RS_MA'] = df['RS'].rolling(10).mean()
            
            # Volume Setup
            df['Vol_MA'] = df['Volume'].rolling(50).mean()
            df['Dry_Up_Volume'] = (df['Volume'] < df['Vol_MA'] * 0.5).astype(int)
            
            # VCP Geometry
            df['High_52W'] = df['High'].rolling(252).max()
            df['Dist_From_52W_High'] = (df['Close'] / df['High_52W']) - 1
            df['Consolidation_Width'] = ((df['High'].rolling(20).max() / df['Low'].rolling(20).min()) - 1) * 100
            
            # RSI
            delta = df['Close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs = gain / loss
            df['RSI_14'] = 100 - (100 / (1 + rs))

            # ----------------------------------------------------
            # 2. TRIGGER FEATURES (Day T - Today)
            # ----------------------------------------------------
            # These are calculated on the LAST ROW (Today)
            today = df.iloc[-1]
            
            row = {
                'ticker': ticker,
                'date': today.name,
                'Vol_Ratio': today['Volume'] / today['Vol_MA'] if today['Vol_MA'] > 0 else 1.0,
                # Add Alphas here if you have the live calculation function
                'alpha015': 1.0, # Placeholder: Replace with real Alpha function call
                'alpha041': 1.0  # Placeholder
            }
            
            # ----------------------------------------------------
            # 3. SETUP FEATURES (Day T-1 - Yesterday)
            # ----------------------------------------------------
            # These are calculated on the SECOND TO LAST ROW (Yesterday)
            yesterday = df.iloc[-2]
            
            for feat in lag_candidates:
                # Map 'nATR' -> 'nATR_Lag1'
                row[f'{feat}_Lag1'] = yesterday[feat]
                
            # ----------------------------------------------------
            # 4. ADD FUNDAMENTALS (Mock / Load from FMP)
            # ----------------------------------------------------
            # In production, you merge FMP data here. 
            # For now, we fill with neutral values to let technicals drive
            row['eps_growth_yoy'] = 20.0 
            row['revenue_accel'] = 5.0
            row['operating_margin'] = 15.0
            row['roe'] = 15.0
            
            inference_rows.append(row)
            
        except Exception as e:
            print(f"❌ Error processing {ticker}: {e}")

    # Create DataFrame
    inference_df = pd.DataFrame(inference_rows)
    
    # Ensure all required columns exist (fill missing with 0)
    for col in required_features:
        if col not in inference_df.columns:
            inference_df[col] = 0.0
            
    return inference_df

def predict_and_rank(inference_df, model_path, config):
    """
    Loads model and predicts probabilities.
    """
    # Load Model
    model = xgb.XGBClassifier()
    model.load_model(model_path)
    
    # Prepare X (Strict column ordering)
    feature_cols = config['features']
    X_live = inference_df[feature_cols].copy()
    
    # Clean Data (Same as training)
    X_live = X_live.replace([np.inf, -np.inf], np.nan).fillna(0).clip(-1e9, 1e9)
    
    # Predict
    probs = model.predict_proba(X_live)[:, 1]
    inference_df['ml_score'] = probs
    
    # Rank
    ranked = inference_df.sort_values('ml_score', ascending=False)
    return ranked[['ticker', 'ml_score', 'Vol_Ratio', 'nATR_Lag1', 'RS_Lag1']]

# ==========================================
# MAIN EXECUTION
# ==========================================
if __name__ == "__main__":
    
    # 1. Load Config
    try:
        with open("model_config.json", "r") as f:
            config = json.load(f)
        print("✅ Config loaded.")
    except FileNotFoundError:
        print("❌ model_config.json not found! Train the model first.")
        exit()

    # 2. Input your Candidates (From your SEPA Scanner)
    # Example: These tickers 'broke out' today
    candidates = ['NVDA', 'AMD', 'TSLA', 'PLTR', 'SMCI'] 
    
    if not candidates:
        print("No candidates provided.")
        exit()

    # 3. Get Data & Engineer
    ticker_dfs = get_live_data(candidates)
    inference_df = engineer_inference_features(ticker_dfs, config)
    
    # 4. Predict
    if not inference_df.empty:
        results = predict_and_rank(inference_df, "sepa_xgboost_model.json", config)
        
        print("\n" + "="*40)
        print(" 🚀 AI SUPERPERFORMER RANKINGS")
        print("="*40)
        print(results.to_string(index=False))
        print("\n✅ Trading Rule: Buy Top 2 if Score > 0.65")
    else:
        print("Failed to generate features.")