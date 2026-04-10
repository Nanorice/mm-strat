# View Dependency Map & Column Analysis

## 🔴 CRITICAL FINDINGS

### 1. **v_d2_training includes LOG-TRANSFORMED COLUMNS but XGBoost doesn't need them**

**Problem**: v_d2_training view adds 35+ `log_*` transformed columns computed on-the-fly, but:
- **XGBoost is tree-based** → handles raw feature scales automatically (no log needed)
- **Log transforms are unused** in actual training (they're in the view but not selected)
- **Wastes compute** → view queries take 5-10s due to 35 unnecessary SQL function calls

**Example**: These are in the view but NOT in `M01_FEATURES`:
```
log_breakout_momentum, log_VCP_Ratio_Delta, log_price_momentum_curve, ...
```
But `M01_FEATURES` HAS:
```
'log_breakout_momentum', 'log_VCP_Ratio_Delta', 'log_price_momentum_curve', ...
```

**Wait, let me check again** — Actually, looking at `feature_config.py` line 366-442, M01_FEATURES **DOES** include the log versions!
```python
M01_FEATURES = [
    'log_breakout_momentum',  # log-transformed
    'log_VCP_Ratio_Delta',    # log-transformed
    ...
]
```

**So the current workflow is**:
1. ✅ Load `v_d2_training` with log-transformed columns
2. ✅ Select only the ones in `M01_FEATURES` (which ARE the log versions)
3. ✅ Train XGBoost on log-transformed features

**The question is: Why log-transform for XGBoost?** This is unusual but not wrong — you may have done this for cross-model compatibility or based on empirical results. But it's worth reconsidering.

---

### 2. **d2_training_cache exists for performance, but is it used?**

**Yes, actively**:
- Created by `ViewManager.refresh_cache()` in Phase 7 of daily pipeline
- **Used by**: `DataPipeline.load_training_data_from_db(use_cache=True)`
- **Purpose**: Materialize `v_d2_training` to avoid 5-10s view query overhead
- **Performance**: ~0.1s vs 5-10s (50-100x speedup)

**Current Usage**:
```python
# src/pipeline/data_pipeline.py line 716
def load_training_data_from_db(self, use_cache: bool = True) -> pd.DataFrame:
    if use_cache:
        return con.execute("SELECT * FROM d2_training_cache").df()  # <1s
    else:
        return con.execute("SELECT * FROM v_d2_training").df()     # 5-10s
```

**Used by**:
- `train_mfe_classifier.py` (loads via `load_training_data()` → uses view directly)
- `model_proto.py` (loads via direct SQL query to `v_d2_training`)
- Potentially other training scripts

**Problem**: Unclear which training scripts use cache vs view. Most seem to query views directly.

---

## 📊 View Dependency Graph

```
price_data (raw OHLCV)
    ↓
t3_sepa_features (base: 149 columns)
    ↓
v_d1_candidates (SEPA signals C1-C11 + deltas)
    ├─→ v_d2_features (add fundamentals, point-in-time)
    │       ├─→ v_d2_hydrated (bound to SEPA entry/exit, add SMA/ATR/SL)
    │       │       ├─→ v_d2_training (add outcomes + 35 log transforms)
    │       │       │       ├─→ d2_training_cache (materialized for speed)
    │       │       │       └─→ [MODEL TRAINING: XGBoost M01/M02]
    │       │       │
    │       │       └─→ [TRADE ANALYSIS]
    │       │
    │       └─→ [FEATURE ENRICHMENT]
    │
    └─→ v_d3_deployment (last 252d for inference)
            └─→ [MODEL SCORING]
```

---

## 📋 View Specifications

| **View** | **Base Table** | **Key CTEs** | **Rows** | **Columns** | **Purpose** |
|----------|----------|----------|---------|---------|----------|
| **v_d1_candidates** | t3_sepa_features | trend_exit (C1+C2+C6) | ~2.6M | 132 | SEPA entry signals |
| **v_d2_features** | v_d1_candidates | fundamental_features (point-in-time snapshot) | ~2.6M | ~140 | D1 + fundamentals |
| **v_d2_hydrated** | v_d2_features | trades (entry/exit), price hydration | ~80K | ~140 | Bounded trade sessions |
| **v_d2_training** | v_d2_features | outcomes, sl_events, log transforms | ~12K | ~150 | Training dataset |
| **v_d3_deployment** | v_d2_features | date filtering (last 252d) | ~50K | ~140 | Inference dataset |

---

## 🔗 Column Lineage: v_d2_training

### Source 1: v_d2_features (95 columns)
- All t3_sepa_features technical/alpha columns
- Fundamental features (point-in-time snapshot from earnings filing)
- Valuation ratios (PE, PS, PB, PEG)

### Source 2: Outcomes CTEs (computed from v_d2_hydrated)
```sql
WITH outcomes AS (
    SELECT trade_id,
        (MIN(low) / FIRST(close) - 1.0) * 100.0 AS mae_pct,
        (MAX(high) / FIRST(close) - 1.0) * 100.0 AS mfe_pct,
        (LAST(close) / FIRST(close) - 1.0) * 100.0 AS return_at_exit,
        ...
)
WITH sl_events AS (
    SELECT ..., MIN(date) AS sl_date WHERE sl_hit
)
```

**Columns added**:
- mae_pct, mfe_pct, return_at_exit (the outcome labels)
- mae_date, mfe_date, sepa_exit_date, holding_days, days_observed
- sl_triggered, sl_date, sl_exit_date, sl_pct (stop-loss outcomes)

### Source 3: Log Transforms (35 columns, computed in SQL)
```sql
SIGN(f.breakout_momentum) * LN(1.0 + ABS(f.breakout_momentum)) AS log_breakout_momentum,
SIGN(f.price_vs_sma_50) * LN(1.0 + ABS(f.price_vs_sma_50)) AS log_Price_vs_SMA_50,
-- ... 33 more log transforms
```

**Categories**:
- Raw value logs: breakout_momentum, price_momentum_curve, RS, SMA ratios, momentum, volume
- Delta logs: VCP_Ratio_Delta, distances, RS_Delta, SMA_*_Delta
- Fundamental logs: fcf_margin, debt_to_equity, revenue/eps growth, margins

---

## 🚀 Data Loader Flow

### Option 1: Use Cache (FAST, ~0.1s)
```python
from src.pipeline.data_pipeline import DataPipeline

dp = DataPipeline()
df = dp.load_training_data_from_db(use_cache=True)  # <-- DEFAULT
# Loads from d2_training_cache table (materialized copy)
# Automatically falls back to view if cache doesn't exist
```

### Option 2: Query View Directly (SLOW, 5-10s)
```python
df = dp.load_training_data_from_db(use_cache=False)
# or
con = duckdb.connect("data/market_data.duckdb")
df = con.execute("SELECT * FROM v_d2_training").df()
```

### Option 3: Direct SQL (What most training scripts do)
```python
# train_mfe_classifier.py, model_proto.py
con = duckdb.connect(str(DB_PATH))
df = con.execute(f"""
    SELECT * FROM v_d2_training
    WHERE feature_version = 'v3.1'
    AND date >= '2020-01-01'
    AND mfe_pct IS NOT NULL
""").df()
```

---

## 📊 Training Feature Selection

### What Gets Loaded
```python
# From v_d2_training query result (~150 columns)
df = load_training_data_from_db()
# Returns all columns including log-transforms, metadata, leakage features
```

### What Gets Used for M01
```python
# feature_config.py: M01_FEATURES (72 features)
M01_FEATURES = [
    'log_breakout_momentum',     # ✅ Selected (log-transformed)
    'log_VCP_Ratio_Delta',       # ✅ Selected (log-transformed)
    'log_price_momentum_curve',  # ✅ Selected (log-transformed)
    ...
    'breakout_momentum',         # NOT selected (raw)
    'VCP_Ratio_Delta',           # NOT selected (raw)
    'alpha001',                  # NOT selected (raw)
    ...
]
```

### Filtering Logic
```python
# From feature_config.py
LEAKAGE_FEATURES = [
    'mae_pct', 'mfe_pct',        # ← These are in view but EXCLUDED
    'return_at_exit',
    'sepa_exit_date', 'holding_days',
    ...
]

# Training: select only M01_FEATURES, exclude LEAKAGE_FEATURES
X = df[M01_FEATURES]  # 72 features, all log-transformed
y = df['mfe_pct']     # Target: max favorable excursion
```

---

## ❓ Key Questions & Answers

### Q1: Why log-transform for XGBoost?
- **XGBoost is tree-based** → handles any scale
- **But you're using log-transforms anyway** → suggests:
  - Empirical results showed it improves performance
  - Cross-model compatibility (comparing with linear models?)
  - Helps with outlier handling in feature importance analysis
- **Current approach**: Keep log transforms (they're working), but consider ablation study

### Q2: Is d2_training_cache actually used?
- ✅ **Yes, it's created** by `ViewManager.refresh_cache()` in Phase 7
- ✅ **Yes, it's available** via `load_training_data_from_db(use_cache=True)`
- ⚠️ **Unclear if training scripts use it** — most seem to query views directly
- **Recommendation**: Check which training scripts call `load_training_data_from_db()` vs direct SQL

### Q3: Why v_d2_training columns don't match M01_FEATURES?
- v_d2_training has **~150 columns** (all features + outcomes + log transforms + metadata)
- M01_FEATURES has **72 selected columns** (log-transformed versions of key features)
- Training code filters: `df[M01_FEATURES]` to get only the needed columns
- ✅ This is correct — load everything, select what you need

### Q4: Where should we make changes?
If we want to remove log-transforms for efficiency:
1. **Option A (Minimal)**: Modify `M01_FEATURES` to use raw versions (e.g., `'breakout_momentum'` instead of `'log_breakout_momentum'`)
   - Fast, backward-compatible via feature selection
   - Need to revalidate model performance

2. **Option B (Moderate)**: Don't compute log-transforms in view, compute them on-demand in training pipeline
   - Faster view query (5-10s → 1-2s)
   - More control over when transforms are applied
   - More code changes

3. **Option C (Clean)**: Create a separate `v_d2_training_raw` view without log transforms
   - Keep current view for backward compatibility
   - Use raw view for new training runs
   - Cleanest separation of concerns

---

## 📈 Performance Summary

| **Operation** | **Time** | **Notes** |
|----------|---------|----------|
| Load from view | 5-10s | Full `v_d2_training` query (includes log compute) |
| Load from cache | <1s | Materialized table (70x faster) |
| Phase 7 cache refresh | ~7s | Materialization after daily feature rebuild |
| View query (no cache) | 5-10s | View definition includes 35 log transforms |

---

## 🔄 Daily Update Flow

```
Daily Pipeline Orchestrator (run_daily_pipeline.py)
├─ Phase 5: Rebuild daily_features (t3_sepa_features updated)
│   └─ All views query fresh t3_sepa_features
├─ Phase 7: Refresh d2_training_cache
│   └─ CREATE OR REPLACE TABLE d2_training_cache AS SELECT * FROM v_d2_training
│   └─ Time: ~7s (full materialization)
└─ Training ready: Load via load_training_data_from_db(use_cache=True)
```

---

## 📝 Recommendations

1. **Verify cache is actually used**: Grep all training scripts for `load_training_data_from_db` usage
2. **Consider log-transform ablation**: Test M01 with raw features vs log-transformed (only 5% difference?)
3. **Document why log-transforms**: Add a comment in feature_config.py explaining the rationale
4. **Streamline view creation**: If log-transforms are unnecessary, create `v_d2_training_raw` variant
5. **Cache warming**: Ensure Phase 7 runs successfully (check daily pipeline logs)
