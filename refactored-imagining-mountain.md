# Integration Plan: Dual-Model System (M01 + M01_3BAR_V2)

## Overview
Integrate both M01 (regression) and M01_3BAR_V2 (classification) models into daily_scanner.py and dashboard.py with:
- Dual-column storage for both model outputs
- Separate ML ranks for each model
- SL/TP price columns based on triple barrier parameters (k_sl=1.0, k_tp=4.0, min_tp=20%)

## Critical Files to Modify

### Database Schema
- **File**: `src/database.py`
- **Changes**: Add 6 new columns to buy_list table

### Scanner Integration
- **File**: `daily_scanner.py`
- **Changes**: Load both models, score with both, store dual outputs

### Dashboard Integration
- **File**: `dashboard.py`
- **Changes**: Display both model scores, add SL/TP columns, dual-rank sorting

## Implementation Steps

### Phase 1: Database Schema Extension

**File**: `src/database.py` (line 60-99, buy_list table definition)

Add new columns after existing `ml_features TEXT`:
```sql
-- M01 model outputs (regression)
m01_expected_return REAL,
m01_rank INTEGER,

-- M01_3BAR_V2 model outputs (classification + barriers)
m01_3bar_prob REAL,
m01_3bar_rank INTEGER,
m01_3bar_sl_price REAL,
m01_3bar_tp_price REAL
```

**Migration strategy**:
- Add migration method `_add_dual_model_columns()` to DatabaseManager
- Check if columns exist before adding (backward compatible)
- Call migration in `_init_database()` after table creation

---

### Phase 2: Dual Model Scoring in Scanner

**File**: `daily_scanner.py`

#### 2.1 Load Both Models (lines 43-61, `load_ml_scorer` function)

**Current**: Loads single model from `config.ML_PRODUCTION_MODEL`

**Change to**:
```python
def load_dual_ml_scorers() -> tuple[Optional[MLScorer], Optional[MLScorer]]:
    """Load both M01 and M01_3BAR_V2 models."""
    m01_scorer = None
    m01_3bar_scorer = None

    try:
        m01_scorer = MLScorer(model_path='models/model_m01.json', log_predictions=True)
        print(f"[M01] Loaded: Regressor, version {m01_scorer.model_version}")
    except Exception as e:
        print(f"[WARN] M01 loading failed: {e}")

    try:
        m01_3bar_scorer = MLScorer(model_path='models/model_m01_3bar_v2.json', log_predictions=True)
        print(f"[M01_3BAR_V2] Loaded: Classifier, version {m01_3bar_scorer.model_version}")
    except Exception as e:
        print(f"[WARN] M01_3BAR_V2 loading failed: {e}")

    return m01_scorer, m01_3bar_scorer
```

#### 2.2 Score with Both Models (lines 120-161, `score_with_ml` function)

**Current**: Returns single score dict `{ticker: {'probability': val, 'features': dict}}`

**Change to**:
```python
def score_with_dual_models(candidates_df, m01_scorer, m01_3bar_scorer, scan_date_str) -> dict:
    """Score with both models and return results."""
    results = {}

    # M01 scoring (regression)
    if m01_scorer:
        m01_probs, _ = m01_scorer.score_batch(candidates_df, ticker_column='ticker', date_column='date')
        for idx, ticker in enumerate(candidates_df['ticker']):
            if ticker not in results:
                results[ticker] = {}
            results[ticker]['m01_expected_return'] = float(m01_probs[idx]) if not np.isnan(m01_probs[idx]) else None
            results[ticker]['m01_features'] = extract_features(candidates_df.iloc[idx], m01_scorer.feature_names)

    # M01_3BAR_V2 scoring (classification)
    if m01_3bar_scorer:
        m01_3bar_probs, _ = m01_3bar_scorer.score_batch(candidates_df, ticker_column='ticker', date_column='date')
        for idx, ticker in enumerate(candidates_df['ticker']):
            if ticker not in results:
                results[ticker] = {}
            results[ticker]['m01_3bar_prob'] = float(m01_3bar_probs[idx]) if not np.isnan(m01_3bar_probs[idx]) else None
            results[ticker]['m01_3bar_features'] = extract_features(candidates_df.iloc[idx], m01_3bar_scorer.feature_names)

            # Calculate SL/TP prices
            row = candidates_df.iloc[idx]
            atr = row.get('ATR')
            close = row.get('Close')
            if atr and close and not np.isnan(atr) and not np.isnan(close):
                results[ticker]['m01_3bar_sl_price'] = calculate_sl_price(close, atr, k_sl=1.0)
                results[ticker]['m01_3bar_tp_price'] = calculate_tp_price(close, atr, k_tp=4.0, min_tp=0.2)

    return results
```

**New helper functions**:
```python
def calculate_sl_price(close: float, atr: float, k_sl: float = 1.0) -> float:
    """Calculate stop-loss price: Close - (k_sl × ATR)"""
    return close - (k_sl * atr)

def calculate_tp_price(close: float, atr: float, k_tp: float = 4.0, min_tp: float = 0.2) -> float:
    """Calculate take-profit price: Close × (1 + MAX(min_tp, k_tp × ATR%))"""
    atr_pct = atr / close
    tp_pct = max(min_tp, k_tp * atr_pct)
    return close * (1 + tp_pct)

def extract_features(row, feature_names) -> dict:
    """Extract feature dict from candidate row."""
    features_dict = {}
    for feature_name in feature_names:
        if feature_name in row.index:
            value = row[feature_name]
            if pd.isna(value):
                features_dict[feature_name] = None
            elif isinstance(value, (np.integer, np.floating)):
                features_dict[feature_name] = float(value)
            else:
                features_dict[feature_name] = value
    return features_dict
```

#### 2.3 Update Buy List with Dual Scores (lines 432-454, `db.add_to_buy_list()` calls)

**Current**: Passes `ml_probability` OR `ml_expected_return`

**Change to**: Pass all 6 new columns
```python
db.add_to_buy_list(
    ticker=ticker,
    signal_date=scan_date_str,
    signal_price=signal_price,
    current_price=signal_price,
    # ... existing fields ...

    # M01 outputs
    m01_expected_return=dual_scores.get(ticker, {}).get('m01_expected_return'),
    m01_rank=None,  # Calculated later

    # M01_3BAR_V2 outputs
    m01_3bar_prob=dual_scores.get(ticker, {}).get('m01_3bar_prob'),
    m01_3bar_rank=None,  # Calculated later
    m01_3bar_sl_price=dual_scores.get(ticker, {}).get('m01_3bar_sl_price'),
    m01_3bar_tp_price=dual_scores.get(ticker, {}).get('m01_3bar_tp_price'),

    # Backward compatibility (keep existing columns for legacy)
    ml_probability=dual_scores.get(ticker, {}).get('m01_3bar_prob'),  # Use 3bar as default
    ml_expected_return=dual_scores.get(ticker, {}).get('m01_expected_return'),
    ml_model_type='dual',
    ml_rank=None,
    ml_model_version=f"M01+M01_3BAR_V2",
    ml_score_date=scan_date_str,
    ml_features=json.dumps({
        'm01_features': dual_scores.get(ticker, {}).get('m01_features', {}),
        'm01_3bar_features': dual_scores.get(ticker, {}).get('m01_3bar_features', {})
    })
)
```

#### 2.4 Dual Ranking Function (new function after line 197)

```python
def update_dual_ml_ranks(db: DatabaseManager, scan_date_str: str):
    """Calculate separate ranks for M01 and M01_3BAR_V2."""
    buy_list_df = db.get_buy_list(active_only=True, as_of_date=scan_date_str)

    if buy_list_df.empty:
        return

    # Rank by M01 expected return (higher = better)
    if 'm01_expected_return' in buy_list_df.columns:
        m01_entries = buy_list_df[buy_list_df['m01_expected_return'].notna()].copy()
        if len(m01_entries) > 0:
            scores = m01_entries['m01_expected_return'].values
            sorted_indices = np.argsort(scores)[::-1]
            ranks = np.empty(len(scores), dtype=int)
            ranks[sorted_indices] = np.arange(1, len(scores) + 1)

            for ticker, rank in zip(m01_entries['ticker'], ranks):
                db.update_buy_list_column(ticker, 'm01_rank', int(rank))

            logger.info(f"Ranked {len(m01_entries)} tickers by M01 expected return")

    # Rank by M01_3BAR_V2 probability (higher = better)
    if 'm01_3bar_prob' in buy_list_df.columns:
        m01_3bar_entries = buy_list_df[buy_list_df['m01_3bar_prob'].notna()].copy()
        if len(m01_3bar_entries) > 0:
            scores = m01_3bar_entries['m01_3bar_prob'].values
            sorted_indices = np.argsort(scores)[::-1]
            ranks = np.empty(len(scores), dtype=int)
            ranks[sorted_indices] = np.arange(1, len(scores) + 1)

            for ticker, rank in zip(m01_3bar_entries['ticker'], ranks):
                db.update_buy_list_column(ticker, 'm01_3bar_rank', int(rank))

            logger.info(f"Ranked {len(m01_3bar_entries)} tickers by M01_3BAR_V2 ignition prob")
```

#### 2.5 Update Main Scanner Function (line 217, 549-550)

**Change**:
- Line 217: `m01_scorer, m01_3bar_scorer = load_dual_ml_scorers() if use_ml else (None, None)`
- Line 347: `dual_scores = score_with_dual_models(candidates_df, m01_scorer, m01_3bar_scorer, scan_date_str)`
- Line 549: `update_dual_ml_ranks(db, scan_date_str)`

---

### Phase 3: Database Manager Updates

**File**: `src/database.py`

#### 3.1 Update `add_to_buy_list()` signature (around line 150)

Add new parameters:
```python
def add_to_buy_list(
    self,
    ticker: str,
    signal_date: str,
    signal_price: float,
    current_price: float,
    # ... existing params ...

    # New dual-model params
    m01_expected_return: Optional[float] = None,
    m01_rank: Optional[int] = None,
    m01_3bar_prob: Optional[float] = None,
    m01_3bar_rank: Optional[int] = None,
    m01_3bar_sl_price: Optional[float] = None,
    m01_3bar_tp_price: Optional[float] = None,

    # Keep legacy params for backward compatibility
    ml_probability: Optional[float] = None,
    ml_expected_return: Optional[float] = None,
    ml_model_type: Optional[str] = None,
    ml_rank: Optional[int] = None,
    ml_model_version: Optional[str] = None,
    ml_score_date: Optional[str] = None,
    ml_features: Optional[dict] = None
):
```

Update INSERT query to include new columns.

#### 3.2 Add `update_buy_list_column()` method

```python
def update_buy_list_column(self, ticker: str, column: str, value):
    """Update a single column for a ticker in buy_list."""
    conn = sqlite3.connect(self.db_path)
    cursor = conn.cursor()
    cursor.execute(f"""
        UPDATE buy_list
        SET {column} = ?, last_updated = ?
        WHERE ticker = ?
    """, (value, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), ticker))
    conn.commit()
    conn.close()
```

---

### Phase 4: Dashboard Display Updates

**File**: `dashboard.py`

#### 4.1 Update Signal Review Table (lines 287-326)

**Current**: Shows either `ml_expected_return` OR `ml_probability`

**Change to**: Show both M01 and M01_3BAR_V2 columns
```python
# Display columns for dual-model system
display_columns = [
    'ticker',
    'signal_date',

    # M01 outputs
    'm01_expected_return',
    'm01_rank',

    # M01_3BAR_V2 outputs
    'm01_3bar_prob',
    'm01_3bar_rank',
    'm01_3bar_sl_price',
    'm01_3bar_tp_price',

    # Other metrics
    'rs',
    'volume_ratio',
    'signal_price',
    'current_price',
    'price_chg_%'
]

# Filter to existing columns
display_columns = [c for c in display_columns if c in buy_list_df.columns]

# Sort by primary rank (user configurable)
sort_by = st.selectbox(
    "Primary Sort:",
    options=['m01_3bar_rank', 'm01_rank'],
    format_func=lambda x: 'M01_3BAR Rank' if x == 'm01_3bar_rank' else 'M01 Rank'
)

buy_list_df = buy_list_df.sort_values(by=[sort_by], ascending=True)

# Rename columns for display
display_df = buy_list_df[display_columns].copy()
display_df = display_df.rename(columns={
    'm01_expected_return': 'M01_Exp_Ret_%',
    'm01_rank': 'M01_Rank',
    'm01_3bar_prob': 'Ignition_Prob',
    'm01_3bar_rank': '3Bar_Rank',
    'm01_3bar_sl_price': 'SL_Price',
    'm01_3bar_tp_price': 'TP_Price'
})
```

#### 4.2 Update ML Features Display (lines 577-651, `render_ml_features()`)

**Current**: Shows M01 features (21 total)

**Change to**: Show both model features in tabs

```python
def render_ml_features(ticker_row: pd.Series):
    """Parse and display ml_features JSON for both models."""
    ml_features = ticker_row.get('ml_features')

    if ml_features is None or (isinstance(ml_features, float) and pd.isna(ml_features)):
        st.info("No ML feature data available")
        return

    # Parse JSON if string
    if isinstance(ml_features, str):
        try:
            ml_features = json.loads(ml_features)
        except json.JSONDecodeError:
            st.error("Invalid ML features JSON")
            return

    # Check for manual entry
    if ml_features.get('manual_entry'):
        st.info("Manual Entry")
        notes = ml_features.get('notes', 'No notes provided')
        st.text(f"Notes: {notes}")
        return

    # Extract M01 and M01_3BAR features
    m01_features = ml_features.get('m01_features', {})
    m01_3bar_features = ml_features.get('m01_3bar_features', {})

    # Show features in tabs
    tab1, tab2 = st.tabs(["M01 (21 features)", "M01_3BAR_V2 (43 features)"])

    with tab1:
        st.markdown("**M01 Model: Expected Return Predictor**")
        render_feature_categories(m01_features, get_m01_categories())

    with tab2:
        st.markdown("**M01_3BAR_V2 Model: Ignition Engine (Velocity Enhanced)**")
        render_feature_categories(m01_3bar_features, get_m01_3bar_categories())

        # Show barrier params
        st.markdown("---")
        st.markdown("**Triple Barrier Parameters:**")
        col1, col2, col3 = st.columns(3)
        with col1:
            sl_price = ticker_row.get('m01_3bar_sl_price')
            st.metric("Stop Loss", f"${sl_price:.2f}" if sl_price else "N/A",
                     help="SL = Close - (1.0 × ATR)")
        with col2:
            tp_price = ticker_row.get('m01_3bar_tp_price')
            st.metric("Target", f"${tp_price:.2f}" if tp_price else "N/A",
                     help="TP = Close × (1 + MAX(20%, 4.0 × ATR%))")
        with col3:
            st.metric("Max Days", "30", help="Time barrier: 30 trading days")

def get_m01_categories():
    """M01 feature categories (21 features)."""
    return {
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

def get_m01_3bar_categories():
    """M01_3BAR_V2 feature categories (43 features)."""
    return {
        "Captains (Core 7)": [
            "RS", "alpha011", "Dist_From_20D_Low", "Price_vs_SMA_200",
            "alpha054", "Vol_Ratio", "VCP_Ratio"
        ],
        "Velocity Squad (8)": [
            "volume_acceleration", "rs_velocity", "RS_Delta",
            "price_momentum_curve", "breakout_momentum",
            "Dist_From_52W_High_Delta", "Dry_Up_Volume_Delta", "log_volume_velocity"
        ],
        "Alpha Factors (12)": [
            "alpha046", "alpha051", "alpha101", "alpha009", "alpha013",
            "alpha006", "alpha001", "alpha015", "alpha002", "alpha004", "alpha012"
        ],
        "Technical Setup (11)": [
            "Dist_From_52W_High", "consolidation_duration", "Breakout",
            "Consolidation_Width_Delta", "Dist_From_20D_High",
            "Dist_From_52W_Low", "RSI_14_Delta"
        ],
        "Lagged Features (5)": [
            "RS_Lag1", "VCP_Ratio_Lag1", "Dist_From_20D_Low_Lag1",
            "Price_vs_SMA_200_Lag1", "Dist_From_52W_High_Lag1"
        ]
    }

def render_feature_categories(features_dict, categories):
    """Render feature categories in expanders."""
    for category, feature_list in categories.items():
        with st.expander(f"📊 {category}", expanded=False):
            category_data = []
            for feature in feature_list:
                value = features_dict.get(feature)
                if value is not None:
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
```

#### 4.3 Update Refresh ML Scores (lines 44-244, `refresh_ml_scores()`)

**Current**: Loads single model

**Change to**: Load both models and score with both (similar changes to scanner)

#### 4.4 Update Feature Info Panel (lines 257-278)

**Change**: Add M01_3BAR_V2 info alongside M01 info

```markdown
**The dual-model system uses two complementary models:**

**1. M01 - Expected Return Predictor (21 features):**
- Type: XGBoost Regressor
- Output: Expected Return (%)
- Features: Alpha factors, technical setup, fundamentals
- Purpose: Predict magnitude of move

**2. M01_3BAR_V2 - Ignition Engine (43 features):**
- Type: XGBoost Classifier
- Output: Probability (0.0-1.0)
- Features: Velocity-enhanced captains, alpha factors, lagged features
- Purpose: Predict probability of hitting TP before SL
- Barrier Params:
  - SL = 1.0 × ATR
  - TP = MAX(20%, 4.0 × ATR%)
  - Max Time = 30 days
- Performance: 0.757 AUC, 0.02% edge (weak signal)

**Usage**: Use M01 for return magnitude, M01_3BAR for setup quality/risk.
```

---

### Phase 5: Config Updates

**File**: `config.py`

Add new config constants:
```python
# Dual-model configuration
ML_M01_MODEL = 'models/model_m01.json'
ML_M01_3BAR_MODEL = 'models/model_m01_3bar_v2.json'

# Triple barrier parameters (from M01_3BAR_V2 config)
BARRIER_K_SL = 1.0  # Stop loss multiplier
BARRIER_K_TP = 4.0  # Target multiplier
BARRIER_MIN_TP = 0.2  # Minimum profit target (20%)
BARRIER_MAX_TIME = 30  # Maximum days
```

---

## Verification Steps

### 1. Database Migration Test
```bash
# Run scanner with --use-ml to trigger migration
python daily_scanner.py --scan-date 2026-01-24 --use-ml
```

**Expected**:
- Database adds 6 new columns without errors
- Existing data preserved

### 2. Dual Scoring Test
```bash
# Run scanner and verify both models score
python daily_scanner.py --scan-date 2026-01-24 --use-ml
```

**Expected**:
- Console shows "[M01] Loaded: Regressor..."
- Console shows "[M01_3BAR_V2] Loaded: Classifier..."
- Buy list table shows populated m01_expected_return, m01_3bar_prob, SL/TP prices
- Both m01_rank and m01_3bar_rank calculated

### 3. Dashboard Display Test
```bash
# Launch dashboard
streamlit run dashboard.py
```

**Expected**:
- Signal Review table shows all 6 new columns
- Can sort by M01_Rank or 3Bar_Rank
- Deep Dive shows both models in tabs
- SL/TP prices displayed correctly
- Feature categories match config (21 M01, 43 M01_3BAR)

### 4. End-to-End Test
1. Run scanner: `python daily_scanner.py --use-ml`
2. Open dashboard: `streamlit run dashboard.py`
3. Click "Refresh ML Scores" button
4. Verify:
   - Both models re-score all tickers
   - Ranks recalculated for both models
   - SL/TP prices updated
   - No errors in console

### 5. Data Quality Checks

**SQL queries to verify**:
```sql
-- Check all new columns populated
SELECT ticker, m01_expected_return, m01_rank, m01_3bar_prob, m01_3bar_rank,
       m01_3bar_sl_price, m01_3bar_tp_price
FROM buy_list
WHERE m01_expected_return IS NOT NULL OR m01_3bar_prob IS NOT NULL;

-- Verify SL < current_price < TP
SELECT ticker, current_price, m01_3bar_sl_price, m01_3bar_tp_price,
       (m01_3bar_sl_price < current_price) as sl_ok,
       (current_price < m01_3bar_tp_price) as tp_ok
FROM buy_list
WHERE m01_3bar_sl_price IS NOT NULL;

-- Check rank integrity (no duplicates, sequential)
SELECT m01_rank, COUNT(*) as count
FROM buy_list
WHERE m01_rank IS NOT NULL
GROUP BY m01_rank
HAVING count > 1;
```

---

## Rollback Plan

If issues occur:

1. **Database rollback**:
   - SQLite doesn't support column drops easily
   - Restore from backup: `cp data/quantamental.db.backup data/quantamental.db`

2. **Code rollback**:
   - Revert daily_scanner.py and dashboard.py
   - System falls back to single-model mode using ml_probability/ml_expected_return

3. **Partial rollback**:
   - Keep dual columns but disable one model in scanner
   - Set `m01_3bar_scorer = None` to disable M01_3BAR_V2

---

## Performance Considerations

**Impact**: Minimal
- Dual scoring adds ~2x model inference time (still <1s for typical buy_list size)
- Database queries unchanged (no joins, same table)
- Dashboard rendering slightly slower (2 model tabs vs 1)

**Optimization opportunities**:
- Score models in parallel (use multiprocessing if needed)
- Cache feature calculations (already done in current implementation)
- Lazy-load M01_3BAR features in dashboard (only when tab clicked)

---

## Future Enhancements

1. **Ensemble scoring**: Add `ml_ensemble_score = 0.6×M01 + 0.4×M01_3BAR` column
2. **Conditional position sizing**: Scale positions by ignition_prob
3. **Backtest comparison**: Compare M01-only vs M01_3BAR-only vs ensemble
4. **Alert system**: Trigger alerts when ignition_prob > 0.8 AND expected_return > 5%
5. **Model versioning**: Track which model version generated each score
