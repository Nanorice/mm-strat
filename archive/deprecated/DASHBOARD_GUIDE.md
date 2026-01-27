# TradeOps Dashboard User Guide

## Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Launch Dashboard
```bash
streamlit run dashboard.py
```

The dashboard will open in your browser at `http://localhost:8501`

---

## Flexible ML Workflow

### Why ML Ranks are Empty

If you see empty `ml_rank` and `ml_probability` columns, it means:
1. The scanner was run **without** the `--use-ml` flag, OR
2. The ML model files are missing

### Two-Step Workflow (Recommended)

**Step 1: Run Scanner (Fast - No ML)**
```bash
# Daily scan without ML scoring (fast, low cost)
python daily_scanner.py
```

This populates the `buy_list` with SEPA signals based on technicals only.

**Step 2: Add ML Ranking (Low Cost)**
```bash
# Retroactively rank the buy_list with ML
python rank_buy_list.py
```

This scores existing buy_list entries with ML **without re-scanning**. All required data (price, features, fundamentals) is already cached.

**Benefits:**
- ✅ Fast daily scanning (no ML overhead)
- ✅ Add ML scores only when needed (low cost)
- ✅ Re-rank anytime without re-downloading data
- ✅ Test different models without rescanning

### Single-Step Workflow (All-in-One)

```bash
# Scan with ML scoring in one step
python daily_scanner.py --use-ml --model-path models/production_model.json
```

This does both scanning and ML scoring in a single run.

---

## Usage Guide

### rank_buy_list.py - Retroactive ML Ranking

#### Basic Usage
```bash
# Rank current buy list with default model
python rank_buy_list.py
```

#### Advanced Options
```bash
# Use specific model
python rank_buy_list.py --model-path models/custom_model.json

# Dry run (preview scores without saving)
python rank_buy_list.py --dry-run

# Score as of specific date
python rank_buy_list.py --as-of-date 2025-01-10
```

#### How It Works
1. Reads active tickers from `buy_list` table
2. Loads cached price data (from `data/price/`)
3. Loads cached fundamental data (from `data/fundamentals/`)
4. Calculates all ML features
5. Scores with ML model
6. Updates `buy_list` with `ml_probability`, `ml_rank`, `ml_features`

**No re-scanning required!** Uses existing cache.

---

## Dashboard Features

### Page 1: Signal Review

**High-Level Table**
- All active buy signals
- Sortable by any column
- Default sort: `ml_rank` → `ml_probability`

**Deep Dive Panel**
- Select ticker from dropdown
- **Price Chart:** 6-month candlestick with volume
- **Model Explainability:** Key ML features (nATR, Consolidation Width, RS, etc.)
- **Actions:**
  - ❌ **Reject:** Remove from buy_list (logs as `UI_Reject`)
  - ✅ **Archive/Trade:** Mark as traded (logs as `UI_Trade_Taken`)

### Page 2: Manual Override

Add tickers that the scanner missed:
- Enter ticker symbol
- Set entry price and stop price
- Add optional notes
- Stored with `ml_probability=1.0` (max confidence)
- Notes saved in `ml_features` JSON

### Page 3: History/Analytics

**Metric Cards**
- Signals Today
- Rejected Today
- Avg ML Score
- Active Signals

**Activity Timeline**
- View recent additions/removals
- Filter by time range (7, 14, 30, 60, 90 days)
- Chart showing ADDED vs REMOVED by date

---

## Typical Workflows

### Daily Morning Routine

**Option A: Two-Step (Recommended)**
```bash
# 1. Fast scan (30 seconds)
python daily_scanner.py

# 2. Add ML scores (10 seconds)
python rank_buy_list.py

# 3. Review in dashboard
streamlit run dashboard.py
```

**Option B: Single-Step**
```bash
# 1. Scan with ML (45 seconds)
python daily_scanner.py --use-ml

# 2. Review in dashboard
streamlit run dashboard.py
```

### Re-Ranking with Different Models

```bash
# Try model A
python rank_buy_list.py --model-path models/model_a.json --dry-run

# Try model B
python rank_buy_list.py --model-path models/model_b.json --dry-run

# Save best model
python rank_buy_list.py --model-path models/model_b.json
```

### Backfill ML Scores for Old Signals

If you have old signals in buy_list without ML scores:

```bash
# Rank as of historical date
python rank_buy_list.py --as-of-date 2025-01-10
```

---

## Data Flow

```
Scanner (daily_scanner.py)
  ↓
  Updates price cache (data/price/)
  Updates fundamentals cache (data/fundamentals/)
  Identifies SEPA signals
  ↓
  Populates buy_list (ticker, signal_date, rs, vol_ratio)
  (ml_probability, ml_rank = NULL)

ML Ranker (rank_buy_list.py) - OPTIONAL
  ↓
  Reads buy_list tickers
  Loads cached data (no API calls)
  Calculates ML features
  Scores with model
  ↓
  Updates buy_list (ml_probability, ml_rank, ml_features)

Dashboard (dashboard.py)
  ↓
  Reads buy_list
  Displays signals sorted by ml_rank
  Shows charts from cached price data
```

---

## Troubleshooting

### Empty ML Scores

**Symptom:** `ml_rank` and `ml_probability` are NULL/empty

**Solution:**
```bash
# Run ML ranking
python rank_buy_list.py
```

### Model Not Found

**Symptom:** `FileNotFoundError: Model not found: models/production_model.json`

**Solution:**
- Check if model file exists: `ls models/`
- Train a new model or specify correct path:
  ```bash
  python rank_buy_list.py --model-path models/YOUR_MODEL.json
  ```

### No Price Data

**Symptom:** Charts show "Price data not available"

**Solution:**
```bash
# Run scanner to update cache
python daily_scanner.py
```

### Empty Buy List

**Symptom:** "No active signals in the buy list"

**Solution:**
```bash
# Run scanner to populate signals
python daily_scanner.py

# Or add manual entry via dashboard (Page 2: Manual Override)
```

---

## Performance Notes

### Cache-Only Mode
- Dashboard uses `force_cache_only=True` for price data
- **No API calls** during dashboard use
- Fast chart rendering (< 100ms per ticker)

### ML Ranking Cost
- Uses cached data only (no API calls)
- ~10-20 seconds for 20-50 tickers
- Can run multiple times per day at no cost

### Scanner Cost
- API calls for price updates (~1-2 seconds per ticker)
- Run once daily or use cached data

---

## Database Schema

### buy_list Table
- `ticker` - Stock symbol (PRIMARY KEY)
- `signal_date` - Date signal triggered
- `signal_price` - Price at trigger
- `rs` - Relative strength
- `volume_ratio` - Volume spike ratio
- `ml_probability` - ML success probability (0.0-1.0)
- `ml_rank` - Rank (1=best, 2=second, etc.)
- `ml_features` - JSON blob with feature values
- `status` - 'active' or 'removed'

### buy_list_activity Table
- `ticker` - Stock symbol
- `action` - 'ADDED' or 'REMOVED' or 'TRADED'
- `action_date` - Date of action
- `reason` - Reason (e.g., 'new_trigger', 'UI_Reject', 'traded')

---

## Tips & Best Practices

1. **Run scanner once daily** (morning before market open)
2. **Use two-step workflow** for flexibility (scan first, rank later)
3. **Test models with --dry-run** before committing
4. **Review signals in dashboard** before market open
5. **Use Manual Override** for discretionary picks
6. **Check History/Analytics** to track signal quality over time

---

## Future Enhancements

- Real-time price updates during market hours
- Trade execution integration (IB API)
- Custom alerts (email/SMS)
- Portfolio P&L tracking
- Backtesting visualizer
- Multi-user authentication
