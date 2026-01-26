"""
TradeOps Dashboard - Streamlit Application
Visualize and manage quantitative scanner output.
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
import json
import sys
import sqlite3
from pathlib import Path

# Add src to path
sys.path.append(str(Path(__file__).parent))

import config
from src.database import DatabaseManager
from src.data_engine import DataRepository

# Page configuration
st.set_page_config(
    page_title="TradeOps Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize database and data repository (cached to avoid reconnecting)
@st.cache_resource
def get_db_manager():
    return DatabaseManager()

@st.cache_resource
def get_data_repo():
    return DataRepository()


# ==================== PAGE 1: SIGNAL REVIEW ====================

def refresh_ml_scores(db: DatabaseManager, data_repo: DataRepository):
    """Refresh ML scores for all tickers in buy_list using latest trading day data."""
    from src.features import FeatureEngineer
    from src.fundamental_merger import FundamentalMerger
    from src.ml_scorer import MLScorer
    from src.utils import get_latest_trading_day
    import json

    # Get active buy list
    buy_list_df = db.get_buy_list(active_only=True)

    if buy_list_df.empty:
        st.warning("No active signals to score")
        return

    tickers = buy_list_df['ticker'].tolist()

    # Create status container
    status = st.empty()
    progress_bar = st.progress(0)
    log_container = st.container()

    with log_container:
        st.markdown("### ML Scoring Progress")

        # Get latest trading day
        latest_trading_day = get_latest_trading_day()
        st.info(f"📅 Using data as of: **{latest_trading_day}**")

        # Load ML model
        st.write("🤖 Loading ML model...")
        try:
            ml_scorer = MLScorer(model_path=config.ML_PRODUCTION_MODEL, log_predictions=False)
            model_type_str = "Regression (Return %)" if ml_scorer.is_regressor else "Classification (Probability)"
            st.success(f"✅ Loaded model: {model_type_str} (version: {ml_scorer.model_version}, features: {len(ml_scorer.feature_names)})")
        except Exception as e:
            st.error(f"❌ Failed to load ML model: {e}")
            return

        # Load data
        st.write(f"📊 Loading price data for {len(tickers)} tickers...")
        min_date = (pd.Timestamp.now() - pd.DateOffset(years=2)).strftime('%Y-%m-%d')
        ticker_data = data_repo.get_batch_data(
            tickers,
            min_date=min_date,
            check_min_date=False,
            force_cache_only=True
        )

        if not ticker_data:
            st.error("❌ No price data available in cache")
            return

        st.success(f"✅ Loaded {len(ticker_data)} tickers from cache")

        # Load benchmark
        st.write("📈 Loading benchmark data (SPY)...")
        benchmark_data = data_repo.get_benchmark_data(
            check_min_date=False,
            force_cache_only=True
        )

        if benchmark_data is None:
            st.error("❌ Benchmark data not available")
            return

        st.success("✅ Loaded benchmark data")

        # Calculate features
        st.write("🔧 Calculating technical features...")
        feature_engine = FeatureEngineer(benchmark_data=benchmark_data)
        enriched_data = feature_engine.process_universe_batch(ticker_data)
        st.success(f"✅ Calculated features for {len(enriched_data)} tickers")

        # Prepare ML candidates
        st.write("🎯 Preparing ML candidates...")
        fund_merger = FundamentalMerger()
        ml_candidates = []

        for ticker in tickers:
            ticker_df = enriched_data.get(ticker)
            if ticker_df is None or len(ticker_df) == 0:
                continue

            # Get row at latest trading day or latest available
            scan_date_obj = pd.Timestamp(latest_trading_day)
            if scan_date_obj in ticker_df.index:
                row = ticker_df.loc[scan_date_obj]
            else:
                available_dates = ticker_df.index[ticker_df.index <= scan_date_obj]
                if len(available_dates) == 0:
                    continue
                row = ticker_df.loc[available_dates[-1]]

            # Get fundamental data
            single_date_df = pd.DataFrame({
                'Date': [row.name],
                'Close': [row.get('Close', np.nan)]
            }).set_index('Date')

            try:
                merged_df = fund_merger.merge_ticker_data(ticker, single_date_df)
                fund_cols = [c for c in merged_df.columns if c not in ['Date', 'Close', 'Open', 'High', 'Low', 'Volume', 'Adj Close']]
                fund_data = merged_df[fund_cols].iloc[0] if len(merged_df) > 0 else None
            except:
                fund_data = None

            candidate_features = {
                'ticker': ticker,
                'date': row.name,
                **row.to_dict(),
            }

            if fund_data is not None:
                candidate_features.update(fund_data.to_dict())

            ml_candidates.append(candidate_features)

        candidates_df = pd.DataFrame(ml_candidates)
        st.success(f"✅ Prepared {len(candidates_df)} candidates for scoring")

        # Score with ML
        st.write("🎲 Scoring with ML model...")
        try:
            probabilities, ranks = ml_scorer.score_batch(
                candidates_df,
                ticker_column='ticker',
                date_column='date'
            )
            # Determine output column based on model type
            score_col_name = 'ml_expected_return' if ml_scorer.is_regressor else 'ml_probability'
            candidates_df[score_col_name] = probabilities
            candidates_df['ml_rank'] = ranks

            st.success(f"✅ Scored {len(candidates_df)} tickers")
            if ml_scorer.is_regressor:
                st.write(f"   - Expected return range: [{probabilities.min():.2f}%, {probabilities.max():.2f}%]")
            else:
                st.write(f"   - Probability range: [{probabilities.min():.3f}, {probabilities.max():.3f}]")
            st.write(f"   - Mean: {probabilities.mean():.3f}, Median: {np.median(probabilities):.3f}")
        except Exception as e:
            st.error(f"❌ ML scoring failed: {e}")
            return

        # Update database
        st.write("💾 Updating database...")
        updates = []

        # Determine score column name
        score_col_name = 'ml_expected_return' if ml_scorer.is_regressor else 'ml_probability'

        for _, row in candidates_df.iterrows():
            ticker = row['ticker']
            ml_score_val = float(row[score_col_name])
            ml_rank_val = int(row['ml_rank'])

            # Get features dict
            candidate_row = candidates_df[candidates_df['ticker'] == ticker].iloc[0]
            features_dict = {}
            for feature_name in ml_scorer.feature_names:
                if feature_name in candidate_row.index:
                    value = candidate_row[feature_name]
                    if pd.isna(value):
                        features_dict[feature_name] = None
                    elif isinstance(value, (np.integer, np.floating)):
                        features_dict[feature_name] = float(value)
                    else:
                        features_dict[feature_name] = value

            # Set the appropriate score column based on model type
            if ml_scorer.is_regressor:
                updates.append({
                    'ticker': ticker,
                    'ml_probability': None,  # Clear probability for regression models
                    'ml_expected_return': ml_score_val,
                    'ml_model_type': 'regression',
                    'ml_rank': ml_rank_val,
                    'ml_model_version': ml_scorer.model_version,
                    'ml_score_date': datetime.now().strftime('%Y-%m-%d'),
                    'ml_features': json.dumps(features_dict)
                })
            else:
                updates.append({
                    'ticker': ticker,
                    'ml_probability': ml_score_val,
                    'ml_expected_return': None,  # Clear expected_return for classification models
                    'ml_model_type': 'classification',
                    'ml_rank': ml_rank_val,
                    'ml_model_version': ml_scorer.model_version,
                    'ml_score_date': datetime.now().strftime('%Y-%m-%d'),
                    'ml_features': json.dumps(features_dict)
                })

        try:
            update_count = db.batch_update_ml_scores(updates)
            st.success(f"✅ Updated {update_count}/{len(candidates_df)} tickers in database")
        except Exception as e:
            st.error(f"❌ Database update failed: {e}")
            return

        st.success("🎉 ML scoring refresh completed!")

def render_signal_review_page(db: DatabaseManager, data_repo: DataRepository):
    st.title("📊 Signal Review")

    # ML Scoring Refresh Button
    col_title, col_refresh = st.columns([3, 1])
    with col_refresh:
        if st.button("🔄 Refresh ML Scores", use_container_width=True, help="Re-score all buy_list tickers with ML model"):
            refresh_ml_scores(db, data_repo)
            st.rerun()

    # Feature Information Panel
    with st.expander("ℹ️ Dual-Model System (M01 + M01_3BAR_V2)", expanded=False):
        st.markdown("""
        **Two ML models work together to score SEPA setups:**

        ### M01 (Regressor) - 21 features
        - **Output:** Expected Return (%)
        - **Alpha Factors:** alpha009, alpha011, alpha013, alpha041, alpha060, alpha101
        - **Technical:** nATR, RS, VCP_Ratio, SMA_50_Slope, Price_vs_SMA_50/200
        - **Fundamental:** operating_margin, eps_growth_yoy, revenue_accel, pe_ratio

        ### M01_3BAR_V2 (Classifier) - 43 features
        - **Output:** Ignition Probability (0-1), SL/TP prices
        - **Uses Triple Barrier Labels:** k_sl=1.0, k_tp=4.0, min_tp=20%, max_time=30d
        - **SL Price:** Close - (1.0 × ATR)
        - **TP Price:** Close × (1 + MAX(20%, 4.0 × ATR%))

        **Ranking:** Each model generates independent ranks (lower = better).
        """)

    # Fetch active buy list
    buy_list_df = db.get_buy_list(active_only=True)

    if buy_list_df.empty:
        st.info("No active signals in the buy list.")
        return

    # Prepare display columns - dual-model support
    # Define all dual-model columns we want to display
    display_columns = [
        'ticker', 'signal_date',
        'm01_expected_return', 'm01_rank',      # M01 outputs
        'm01_3bar_prob', 'm01_3bar_rank',       # M01_3BAR outputs
        'm01_3bar_sl_price', 'm01_3bar_tp_price',
        'rs', 'volume_ratio', 'signal_price', 'current_price'
    ]
    
    # Filter to only columns that exist
    display_columns = [c for c in display_columns if c in buy_list_df.columns]

    # Calculate price change %
    buy_list_df['price_chg_%'] = (
        (buy_list_df['current_price'] - buy_list_df['signal_price']) /
        buy_list_df['signal_price'] * 100
    ).round(2)

    # Sort selector for dual-model ranks
    sort_options = {'M01 Rank (Expected Return)': 'm01_rank', 'M01_3BAR Rank (Ignition Prob)': 'm01_3bar_rank'}
    sort_by_label = st.selectbox("📊 Primary Sort By:", options=list(sort_options.keys()), index=0)
    sort_col = sort_options[sort_by_label]
    
    # Sort by selected rank
    if sort_col in buy_list_df.columns:
        buy_list_df = buy_list_df.sort_values(by=sort_col, ascending=True, na_position='last')
    
    # Prepare display DataFrame with renamed columns
    display_df = buy_list_df[display_columns + ['price_chg_%']].copy()
    
    # Rename columns for clearer display
    col_rename = {
        'm01_expected_return': 'M01_Exp%',
        'm01_rank': 'M01_#',
        'm01_3bar_prob': '3Bar_Prob',
        'm01_3bar_rank': '3Bar_#',
        'm01_3bar_sl_price': 'SL_Price',
        'm01_3bar_tp_price': 'TP_Price',
        'volume_ratio': 'Vol_Ratio'
    }
    display_df = display_df.rename(columns={k: v for k, v in col_rename.items() if k in display_df.columns})

    # Display sortable dataframe with row selection
    st.markdown("**Click a row to select ticker for Deep Dive:**")
    selection = st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row"
    )
    
    # Get selected ticker from table click
    selected_from_table = None
    if selection.selection and selection.selection.rows:
        selected_row_idx = selection.selection.rows[0]
        if selected_row_idx < len(buy_list_df):
            selected_from_table = buy_list_df.iloc[selected_row_idx]['ticker']

    # Ticker selection dropdown - based on PRICE CACHE, not buy_list
    st.markdown("---")
    st.markdown("#### Deep Dive Analysis")

    # Get all tickers from price cache
    cached_tickers = data_repo.get_cached_tickers()

    if not cached_tickers:
        st.warning("No tickers in price cache. Run scanner to populate cache.")
        return

    # Combine buy_list tickers (at top) + all cached tickers
    buy_list_tickers = buy_list_df['ticker'].tolist()
    other_tickers = [t for t in cached_tickers if t not in buy_list_tickers]
    all_tickers = buy_list_tickers + sorted(other_tickers)
    
    # Determine default ticker: from table click, or first in list
    if selected_from_table and selected_from_table in all_tickers:
        default_idx = all_tickers.index(selected_from_table)
    else:
        default_idx = 0 if len(all_tickers) > 0 else None

    col1, col2 = st.columns([3, 1])
    with col1:
        selected_ticker = st.selectbox(
            "Select a ticker for detailed analysis:",
            options=all_tickers,
            index=default_idx,
            help="Click a row in the table above or select from dropdown"
        )
    with col2:
        # Option to manually enter ticker
        manual_ticker = st.text_input("Or enter ticker:", placeholder="AAPL").upper()
        if manual_ticker:
            selected_ticker = manual_ticker

    if selected_ticker:
        render_deep_dive_panel(selected_ticker, buy_list_df, db, data_repo)


def render_deep_dive_panel(ticker: str, buy_list_df: pd.DataFrame,
                           db: DatabaseManager, data_repo: DataRepository):
    st.subheader(f"🔍 Deep Dive: {ticker}")

    # Check if ticker is in buy_list (might not be if selected from cache)
    ticker_data = buy_list_df[buy_list_df['ticker'] == ticker]
    is_in_buy_list = not ticker_data.empty

    if is_in_buy_list:
        ticker_row = ticker_data.iloc[0]
    else:
        # Ticker is in cache but not in active buy_list
        ticker_row = None

    # Layout: Chart (left) | Explainability (right)
    col1, col2 = st.columns([2, 1])

    with col1:
        st.markdown("#### Price Chart (6 Months)")
        # Pass entry price if ticker is in buy list
        entry_price = None
        signal_date = None
        if is_in_buy_list and ticker_row is not None:
            # Try entry_price first, fall back to signal_price
            entry_price = ticker_row.get('entry_price')
            if entry_price is None or (isinstance(entry_price, float) and pd.isna(entry_price)):
                entry_price = ticker_row.get('signal_price')
            signal_date = ticker_row.get('signal_date')
        chart = create_candlestick_chart(ticker, data_repo, entry_price=entry_price, signal_date=signal_date)
        if chart:
            st.plotly_chart(chart, use_container_width=True)
        else:
            st.warning(f"Price data not available for {ticker}")

    with col2:
        if is_in_buy_list:
            st.markdown("#### Model Explainability")
            render_ml_features(ticker_row)

            st.markdown("#### Actions")
            render_action_buttons(ticker, db)
        else:
            st.info(f"**{ticker}** is not in the active buy list.")
            st.markdown("This ticker is cached but has no active signal. You can:")
            st.markdown("- View the price chart on the left")
            st.markdown("- Add manually via 'Manual Override' page")


def create_candlestick_chart(ticker: str, data_repo: DataRepository, 
                              entry_price: float = None, signal_date: str = None):
    """Create 6-month candlestick chart with volume and moving averages.
    
    Features:
    - No weekend gaps (using rangebreaks)
    - SMA50 and SMA200 overlays
    - Optional entry price horizontal line
    """
    try:
        # Fetch price data (last 6 months)
        end_date = datetime.now()
        start_date = end_date - timedelta(days=180)

        df = data_repo.get_ticker_data(
            ticker,
            use_cache=True,
            force_cache_only=True
        )

        if df is None or df.empty:
            return None

        # Filter to last 6 months
        df = df[df.index >= start_date]

        if df.empty:
            return None

        # Calculate SMAs if not present
        if 'SMA_50' not in df.columns:
            df['SMA_50'] = df['Close'].rolling(window=50).mean()
        if 'SMA_200' not in df.columns:
            df['SMA_200'] = df['Close'].rolling(window=200).mean()

        # Create subplot with candlestick + volume
        fig = make_subplots(
            rows=2, cols=1,
            shared_xaxes=True,
            vertical_spacing=0.03,
            row_heights=[0.75, 0.25],
            subplot_titles=(f"{ticker}", "Volume")
        )

        # Candlestick
        fig.add_trace(
            go.Candlestick(
                x=df.index,
                open=df['Open'],
                high=df['High'],
                low=df['Low'],
                close=df['Close'],
                name='Price',
                increasing_line_color='#26a69a',
                decreasing_line_color='#ef5350'
            ),
            row=1, col=1
        )

        # SMA 50 (Blue)
        if 'SMA_50' in df.columns and df['SMA_50'].notna().any():
            fig.add_trace(
                go.Scatter(
                    x=df.index,
                    y=df['SMA_50'],
                    name='SMA 50',
                    line=dict(color='#2196F3', width=1.5),
                    hovertemplate='SMA50: %{y:.2f}<extra></extra>'
                ),
                row=1, col=1
            )

        # SMA 200 (Orange)
        if 'SMA_200' in df.columns and df['SMA_200'].notna().any():
            fig.add_trace(
                go.Scatter(
                    x=df.index,
                    y=df['SMA_200'],
                    name='SMA 200',
                    line=dict(color='#FF9800', width=1.5),
                    hovertemplate='SMA200: %{y:.2f}<extra></extra>'
                ),
                row=1, col=1
            )

        # Entry price line (if provided)
        if entry_price is not None:
            fig.add_hline(
                y=entry_price,
                line_dash="dash",
                line_color="green",
                annotation_text=f"Entry: ${entry_price:.2f}",
                annotation_position="right",
                row=1, col=1
            )

        # Volume bars - colored by day direction
        colors = ['#26a69a' if c >= o else '#ef5350' 
                  for c, o in zip(df['Close'], df['Open'])]
        
        fig.add_trace(
            go.Bar(
                x=df.index,
                y=df['Volume'],
                name='Volume',
                marker_color=colors,
                opacity=0.7
            ),
            row=2, col=1
        )

        # Layout with weekend gaps removed
        fig.update_layout(
            height=500,
            xaxis_rangeslider_visible=False,
            showlegend=True,
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1
            ),
            template='plotly_white',
            margin=dict(l=50, r=50, t=60, b=30)
        )

        # Remove weekend gaps
        fig.update_xaxes(
            rangebreaks=[
                dict(bounds=["sat", "mon"]),  # Hide weekends
            ]
        )

        # Format y-axis
        fig.update_yaxes(tickprefix="$", row=1, col=1)
        fig.update_yaxes(tickformat=".2s", row=2, col=1)  # Abbreviate volume (1M, 2M, etc.)

        return fig

    except Exception as e:
        st.error(f"Error loading chart: {e}")
        return None


def render_ml_features(ticker_row: pd.Series):
    """Parse and display ml_features JSON with key metrics."""
    ml_features = ticker_row.get('ml_features')

    if ml_features is None or (isinstance(ml_features, float) and pd.isna(ml_features)):
        st.info("No ML feature data available")
        return

    # Parse JSON if string (shouldn't be needed since get_buy_list already parses it)
    if isinstance(ml_features, str):
        try:
            ml_features = json.loads(ml_features)
        except json.JSONDecodeError:
            st.error("Invalid ML features JSON")
            return

    # Check if it's a dict
    if not isinstance(ml_features, dict):
        st.info("No ML feature data available")
        return

    # Check for manual entry
    if ml_features.get('manual_entry'):
        st.info("Manual Entry")
        notes = ml_features.get('notes', 'No notes provided')
        st.text(f"Notes: {notes}")
        return

    # Show all features in organized categories
    st.markdown("**ML Model Features (21 total):**")

    # Group features by category for M01 model
    categories = {
        "Alpha Factors (WorldQuant)": [
            "alpha009", "alpha011", "alpha013", "alpha041", "alpha060", "alpha101"
        ],
        "Technical Setup": [
            "nATR", "RS", "RS_Delta", "VCP_Ratio", "SMA_50_Slope",
            "Price_vs_SMA_50", "Price_vs_SMA_200",
            "Dry_Up_Volume", "Dist_From_20D_Low", "Dist_From_52W_High"
        ],
        "Fundamental": [
            "operating_margin", "eps_growth_yoy", "revenue_accel", "pe_ratio", "eps_accel"
        ]
    }

    for category, features in categories.items():
        with st.expander(f"📊 {category}", expanded=False):
            category_data = []
            for feature in features:
                value = ml_features.get(feature)
                if value is not None:
                    # Format value based on type
                    if isinstance(value, (int, float)):
                        if abs(value) < 0.01 and value != 0:
                            formatted_val = f"{value:.6f}"
                        elif abs(value) < 1:
                            formatted_val = f"{value:.4f}"
                        else:
                            formatted_val = f"{value:.3f}"
                    else:
                        formatted_val = str(value)
                    category_data.append({"Feature": feature, "Value": formatted_val})
                else:
                    category_data.append({"Feature": feature, "Value": "N/A"})

            if category_data:
                st.dataframe(
                    pd.DataFrame(category_data),
                    hide_index=True,
                    use_container_width=True,
                    height=min(200, len(category_data) * 35 + 38)
                )
            st.markdown("")  # Add spacing


def render_action_buttons(ticker: str, db: DatabaseManager):
    """Display action buttons for signal management."""
    col1, col2 = st.columns(2)

    with col1:
        if st.button("❌ Reject", key=f"reject_{ticker}", use_container_width=True):
            db.remove_from_buy_list(ticker, reason='UI_Reject')
            st.success(f"Removed {ticker} from buy list")
            st.rerun()

    with col2:
        if st.button("✅ Archive/Trade", key=f"archive_{ticker}", use_container_width=True):
            # Get ticker data from buy_list to capture all enriched features
            buy_list_df = db.get_buy_list(active_only=True)
            ticker_data = buy_list_df[buy_list_df['ticker'] == ticker]

            if not ticker_data.empty:
                row = ticker_data.iloc[0]

                # Log to activity with FULL enriched data
                db.log_buy_list_activity(
                    ticker=ticker,
                    action='TRADED',
                    action_date=datetime.now().strftime('%Y-%m-%d'),
                    reason='UI_Trade_Taken',
                    entry_price=row.get('entry_price') or row.get('signal_price'),
                    stop_price=row.get('stop_price'),
                    target_price=row.get('target_price'),
                    rs=row.get('rs'),
                    vol_ratio=row.get('volume_ratio')
                )

                # Create formal trade entry in trades table
                entry_price = row.get('entry_price') or row.get('signal_price')
                stop_price = row.get('stop_price')
                target_price = row.get('target_price')

                if entry_price and stop_price and target_price:
                    # Calculate position size (8% max loss per position)
                    risk_per_share = entry_price - stop_price
                    if risk_per_share > 0:
                        shares = int((config.INITIAL_CAPITAL * config.POSITION_SIZE_PCT) / entry_price)

                        db.log_trade(
                            ticker=ticker,
                            entry_date=datetime.now().strftime('%Y-%m-%d'),
                            entry_price=entry_price,
                            shares=shares,
                            stop_price=stop_price,
                            target_price=target_price
                        )

            # Remove from buy_list
            db.remove_from_buy_list(ticker, reason='traded')
            st.success(f"Marked {ticker} as traded and logged to trades table")
            st.rerun()


# ==================== PAGE 2: MANUAL OVERRIDE ====================

def render_manual_override_page(db: DatabaseManager, data_repo: DataRepository):
    st.title("✏️ Manual Override")
    st.markdown("Add a ticker that the scanner missed or for manual tracking.")

    with st.form("manual_add_form"):
        col1, col2 = st.columns(2)

        with col1:
            ticker = st.text_input("Ticker Symbol", placeholder="AAPL").upper()
            entry_price = st.number_input("Entry Price ($)", min_value=0.01, step=0.01, value=100.0)
            calculate_features = st.checkbox("Calculate enriched features (slower)", value=False)

        with col2:
            stop_price = st.number_input("Stop Price ($)", min_value=0.01, step=0.01, value=92.0)
            notes = st.text_area("Notes (optional)", placeholder="Manual entry reason...")

        submitted = st.form_submit_button("Add to Buy List", use_container_width=True)

        if submitted:
            if not ticker or entry_price <= 0:
                st.error("Please provide ticker and valid entry price")
            else:
                # Calculate basic fields
                signal_date = datetime.now().strftime('%Y-%m-%d')
                target_price = entry_price * (1 + config.PROFIT_TARGET_R * config.STOP_LOSS_PCT)

                # Initialize ml_features with notes
                ml_features_dict = {
                    'manual_entry': True,
                    'notes': notes if notes else 'Manual override entry',
                    'entry_date': signal_date
                }

                # Optionally calculate enriched features
                rs = None
                vol_ratio = None

                if calculate_features:
                    with st.spinner(f"Calculating enriched features for {ticker}..."):
                        try:
                            from src.features import FeatureEngineer

                            # Load price data
                            ticker_df = data_repo.get_ticker_data(
                                ticker,
                                use_cache=True,
                                force_cache_only=True
                            )

                            if ticker_df is not None and not ticker_df.empty:
                                # Load benchmark
                                benchmark_data = data_repo.get_benchmark_data(
                                    check_min_date=False,
                                    force_cache_only=True
                                )

                                if benchmark_data is not None:
                                    # Calculate features using proper method
                                    feature_engine = FeatureEngineer(benchmark_data=benchmark_data)

                                    # process_universe_batch expects a dict {ticker: df}
                                    ticker_data_dict = {ticker: ticker_df}
                                    enriched_data = feature_engine.process_universe_batch(ticker_data_dict)

                                    # Get the enriched dataframe for this ticker
                                    if ticker in enriched_data and not enriched_data[ticker].empty:
                                        enriched_df = enriched_data[ticker]
                                        latest = enriched_df.iloc[-1]

                                        rs = latest.get('RS')
                                        vol_ratio = latest.get('Vol_Ratio')

                                        # Store key features in ml_features
                                        ml_features_dict.update({
                                            'RS': float(rs) if pd.notna(rs) else None,
                                            'Vol_Ratio': float(vol_ratio) if pd.notna(vol_ratio) else None,
                                            'SMA_50': float(latest.get('SMA_50')) if pd.notna(latest.get('SMA_50')) else None,
                                            'SMA_200': float(latest.get('SMA_200')) if pd.notna(latest.get('SMA_200')) else None,
                                            'ATR': float(latest.get('ATR')) if pd.notna(latest.get('ATR')) else None,
                                        })

                                        st.success(f"✅ Calculated features: RS={rs:.2f}, Vol_Ratio={vol_ratio:.2f}")
                                    else:
                                        st.warning("Feature calculation returned no data")
                                else:
                                    st.warning("Benchmark data not available")
                            else:
                                st.warning(f"Price data not available for {ticker}")
                        except Exception as e:
                            st.error(f"Feature calculation failed: {e}")

                # Add to buy list
                db.add_to_buy_list(
                    ticker=ticker,
                    signal_date=signal_date,
                    signal_price=entry_price,
                    current_price=entry_price,
                    entry_price=entry_price,
                    stop_price=stop_price if stop_price > 0 else entry_price * (1 - config.STOP_LOSS_PCT),
                    target_price=target_price,
                    rs=rs,
                    vol_ratio=vol_ratio,
                    ml_probability=1.0,  # Max confidence for manual entries
                    ml_rank=None,
                    ml_features=ml_features_dict
                )

                # Log activity
                db.log_buy_list_activity(
                    ticker=ticker,
                    action='ADDED',
                    action_date=signal_date,
                    reason='manual_override',
                    entry_price=entry_price,
                    stop_price=stop_price,
                    rs=rs,
                    vol_ratio=vol_ratio
                )

                st.success(f"✅ Added {ticker} to buy list (manual entry)")


# ==================== PAGE 3: HISTORY/ANALYTICS ====================

def render_history_analytics_page(db: DatabaseManager):
    st.title("📈 History & Analytics")

    # Date filter
    col1, col2 = st.columns([1, 3])
    with col1:
        days_back = st.selectbox(
            "Time Range",
            options=[7, 14, 30, 60, 90],
            index=2,  # Default 30 days
            format_func=lambda x: f"Last {x} days"
        )

    cutoff_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')

    # Fetch activity data
    try:
        conn = sqlite3.connect(config.DB_PATH)
        activity_df = pd.read_sql_query(
            f"SELECT * FROM buy_list_activity WHERE action_date >= '{cutoff_date}' ORDER BY action_date DESC",
            conn
        )
        conn.close()
    except Exception as e:
        st.error(f"Error loading activity data: {e}")
        activity_df = pd.DataFrame()

    # Metric cards
    st.markdown("#### Summary Metrics")
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        signals_today = len(activity_df[
            (activity_df['action'] == 'ADDED') &
            (activity_df['action_date'] == datetime.now().strftime('%Y-%m-%d'))
        ]) if not activity_df.empty else 0
        st.metric("Signals Today", signals_today)

    with col2:
        rejected_today = len(activity_df[
            (activity_df['action'] == 'REMOVED') &
            (activity_df['action_date'] == datetime.now().strftime('%Y-%m-%d'))
        ]) if not activity_df.empty else 0
        st.metric("Rejected Today", rejected_today)

    with col3:
        buy_list = db.get_buy_list(active_only=True)
        # Use ml_expected_return for regression, ml_probability for classification
        if not buy_list.empty:
            if 'ml_expected_return' in buy_list.columns and buy_list['ml_expected_return'].notna().any():
                avg_ml_score = buy_list['ml_expected_return'].mean()
                score_label = "Avg Exp Return %"
            elif 'ml_probability' in buy_list.columns and buy_list['ml_probability'].notna().any():
                avg_ml_score = buy_list['ml_probability'].mean()
                score_label = "Avg ML Score"
            else:
                avg_ml_score = 0
                score_label = "Avg ML Score"
        else:
            avg_ml_score = 0
            score_label = "Avg ML Score"
        st.metric(score_label, f"{avg_ml_score:.2f}")

    with col4:
        total_active = len(buy_list) if not buy_list.empty else 0
        st.metric("Active Signals", total_active)

    # Activity timeline
    st.markdown("#### Recent Activity")
    if activity_df.empty:
        st.info(f"No activity in the last {days_back} days")
    else:
        # Format display
        display_cols = ['action_date', 'ticker', 'action', 'reason', 'entry_price', 'rs', 'vol_ratio']
        available_cols = [c for c in display_cols if c in activity_df.columns]
        st.dataframe(
            activity_df[available_cols],
            use_container_width=True,
            hide_index=True
        )

    # Activity chart
    if not activity_df.empty:
        st.markdown("#### Activity Timeline")

        # Group by date and action
        timeline = activity_df.groupby(['action_date', 'action']).size().unstack(fill_value=0)

        fig = go.Figure()

        if 'ADDED' in timeline.columns:
            fig.add_trace(go.Bar(
                x=timeline.index,
                y=timeline['ADDED'],
                name='Added',
                marker_color='green'
            ))

        if 'REMOVED' in timeline.columns:
            fig.add_trace(go.Bar(
                x=timeline.index,
                y=timeline['REMOVED'],
                name='Removed',
                marker_color='red'
            ))

        fig.update_layout(
            barmode='group',
            height=300,
            xaxis_title='Date',
            yaxis_title='Count',
            template='plotly_white'
        )

        st.plotly_chart(fig, use_container_width=True)


# ==================== MAIN APPLICATION ROUTER ====================

def main():
    # Initialize managers
    db = get_db_manager()
    data_repo = get_data_repo()

    # Sidebar navigation
    st.sidebar.title("🎯 TradeOps Dashboard")

    # Refresh button (fixes real-time data updates)
    if st.sidebar.button("🔄 Refresh Data", use_container_width=True):
        st.rerun()

    st.sidebar.markdown("---")

    page = st.sidebar.radio(
        "Navigation",
        options=["Signal Review", "Manual Override", "History/Analytics"],
        index=0
    )

    # Route to selected page
    if page == "Signal Review":
        render_signal_review_page(db, data_repo)
    elif page == "Manual Override":
        render_manual_override_page(db, data_repo)
    elif page == "History/Analytics":
        render_history_analytics_page(db)

    # Footer
    st.sidebar.markdown("---")
    st.sidebar.markdown(f"**Database:** `{config.DB_PATH}`")
    st.sidebar.markdown(f"**Last Updated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()
