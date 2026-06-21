# ============================================================================
# CELL 1 — Imports & Config
# ============================================================================
import sys
from pathlib import Path
import warnings

import duckdb
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from scipy import stats

warnings.filterwarnings('ignore', category=FutureWarning)
sns.set_theme(style='whitegrid', font_scale=1.1)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))

DB_PATH = PROJECT_ROOT / "data" / "market_data.duckdb"
MIN_DATE = '2020-01-01'
FEATURE_VERSION = 'v3.1'

CLASS_NAMES = {
    0: 'Class 0: Duds (<=2%)',
    1: 'Class 1: Noise (2-10%)',
    2: 'Class 2: Solid (10-30%)',
    3: 'Class 3: Elite (>30%)'
}
CLASS_COLORS = {0: '#d62728', 1: '#ff7f0e', 2: '#2ca02c', 3: '#1f77b4'}

print("Imports OK")


# ============================================================================
# CELL 2 — Load Data
# ============================================================================
con = duckdb.connect(str(DB_PATH))

df = con.execute(f"""
    SELECT *
    FROM v_d2_training
    WHERE feature_version = '{FEATURE_VERSION}'
      AND mfe_pct IS NOT NULL
    ORDER BY date, ticker
""").df()
con.close()

print(f"Loaded {len(df):,} rows | {df['ticker'].nunique()} tickers")
print(f"Date range: {df['date'].min()} to {df['date'].max()}")
print(f"Columns: {len(df.columns)}")


# ============================================================================
# CELL 3 — Feature Engineering: EMA Ratios
# ============================================================================
# Price-to-EMA ratios (how far price is from each EMA)
df['price_vs_ema_8'] = (df['close'] / df['ema_8'] - 1) * 100
df['price_vs_ema_21'] = (df['close'] / df['ema_21'] - 1) * 100
df['price_vs_ema_50'] = (df['close'] / df['ema_50'] - 1) * 100
df['price_vs_ema_100'] = (df['close'] / df['ema_100'] - 1) * 100
df['price_vs_ema_200'] = (df['close'] / df['ema_200'] - 1) * 100

# EMA stacking: short-over-long ratios (measures trend alignment)
df['ema_8_21_ratio'] = (df['ema_8'] / df['ema_21'] - 1) * 100
df['ema_21_50_ratio'] = (df['ema_21'] / df['ema_50'] - 1) * 100
df['ema_50_200_ratio'] = (df['ema_50'] / df['ema_200'] - 1) * 100

# EMA stack score: how many short EMAs are above long EMAs (0-4 scale)
df['ema_stack_score'] = (
    (df['ema_8'] > df['ema_21']).astype(int) +
    (df['ema_21'] > df['ema_50']).astype(int) +
    (df['ema_50'] > df['ema_100']).astype(int) +
    (df['ema_100'] > df['ema_200']).astype(int)
)

EMA_FEATURES = [
    'price_vs_ema_8', 'price_vs_ema_21', 'price_vs_ema_50',
    'price_vs_ema_100', 'price_vs_ema_200',
    'ema_8_21_ratio', 'ema_21_50_ratio', 'ema_50_200_ratio',
    'ema_stack_score'
]

print(f"Created {len(EMA_FEATURES)} EMA features")
print(df[EMA_FEATURES].describe().round(2).to_string())


# ============================================================================
# CELL 4 — Quality Check: Missing Data
# ============================================================================
# Group features by category for the null audit
FEATURE_GROUPS = {
    "Moving_Averages": [
        'close_above_sma200', 'price_vs_sma_50', 'price_vs_sma_150', 'price_vs_sma_200',
        'sma_50_slope', 'price_vs_sma_50_delta', 'price_vs_sma_150_delta', 'price_vs_sma_200_delta'
    ],
    "EMA_Ratios": EMA_FEATURES,
    "Momentum_RS": [
        'rs_line_uptrend', 'rs_line_delta', 'rs_line_lag_delta', 'rs_rating', 'rs', 'rs_ma',
        'rs_delta', 'rs_ma_delta', 'mom_21d', 'mom_63d', 'mom_126d', 'mom_189d', 'mom_252d',
        'rs_velocity', 'price_accel_10d', 'RS_Sector_Rank', 'RS_vs_Sector', 'Sector_Momentum',
        'RS_Industry_Rank', 'RS_vs_Industry', 'Industry_Momentum'
    ],
    "Core_Volume": [
        'vol_ratio', 'dry_up_volume', 'dry_up_volume_delta', 'turnover',
        'volume_acceleration', 'return_1d', 'return_5d'
    ],
    "Volatility_Ranges": [
        'natr', 'natr_delta', 'vcp_ratio', 'vcp_ratio_delta',
        'consolidation_width', 'consolidation_width_delta', 'consolidation_duration',
        'dist_from_52w_high', 'dist_from_52w_high_delta',
        'dist_from_52w_low', 'dist_from_52w_low_delta',
        'low_52w_delta', 'high_52w_delta',
        'dist_from_20d_high', 'dist_from_20d_high_delta', 'highest_high_20d_delta',
        'dist_from_20d_low', 'dist_from_20d_low_delta', 'lowest_low_20d_delta'
    ],
    "Technical_Oscillators": [
        'rsi_14', 'rsi_14_delta', 'is_green_day', 'green_days_ratio_20d', 'breakout',
        'breakout_momentum', 'immediate_thrust'
    ],
    "Fundamentals": [
        'eps_diluted', 'revenue_growth_yoy', 'eps_growth_yoy', 'net_income_growth_yoy',
        'eps_accel', 'revenue_accel', 'revenue_cagr_3y', 'eps_stability_score',
        'debt_to_equity', 'current_ratio', 'gross_margin', 'operating_margin', 'roe', 'roa',
        'fcf_margin', 'earnings_quality_score', 'gross_margin_trend', 'days_since_report',
        'pe_ratio', 'ps_ratio', 'pb_ratio'
    ],
    "Fast_Alphas": [
        'alpha001', 'alpha002', 'alpha004', 'alpha006', 'alpha009', 'alpha011', 'alpha012',
        'alpha013', 'alpha015', 'alpha041', 'alpha046', 'alpha049', 'alpha054', 'alpha060',
        'alpha101'
    ],
    "M03_Regime": [
        'm03_score', 'm03_pillar_trend', 'm03_pillar_liq', 'm03_pillar_risk',
        'm03_delta_5d', 'm03_delta_20d', 'm03_regime_vol'
    ]
}

# Null rate audit
print("=" * 70)
print("MISSING DATA AUDIT BY FEATURE GROUP")
print("=" * 70)

null_summary = []
for group_name, features in FEATURE_GROUPS.items():
    present = [f for f in features if f in df.columns]
    missing_cols = [f for f in features if f not in df.columns]
    if missing_cols:
        print(f"\n  [{group_name}] MISSING COLUMNS: {missing_cols}")
    if present:
        null_rates = df[present].isnull().mean()
        worst = null_rates[null_rates > 0].sort_values(ascending=False)
        null_summary.append({
            'group': group_name,
            'n_features': len(present),
            'avg_null_pct': null_rates.mean() * 100,
            'max_null_pct': null_rates.max() * 100,
            'worst_feature': worst.index[0] if len(worst) > 0 else '-'
        })

null_df = pd.DataFrame(null_summary)
print(null_df.to_string(index=False))

# Heatmap of null rates
fig, ax = plt.subplots(figsize=(16, 6))
all_features_flat = [f for feats in FEATURE_GROUPS.values() for f in feats if f in df.columns]
null_pcts = df[all_features_flat].isnull().mean().sort_values(ascending=False)
high_null = null_pcts[null_pcts > 0.01]

if len(high_null) > 0:
    high_null.plot.barh(ax=ax, color='coral')
    ax.set_xlabel('Null Rate')
    ax.set_title(f'Features with >1% Null Rate (n={len(high_null)})')
    plt.tight_layout()
    plt.show()
else:
    print("All features have <1% null rate")
    plt.close()


# ============================================================================
# CELL 5 — Target Construction & Distribution
# ============================================================================
conditions = [
    (df['mfe_pct'] <= 2.0),
    (df['mfe_pct'] > 2.0) & (df['mfe_pct'] <= 10.0),
    (df['mfe_pct'] > 10.0) & (df['mfe_pct'] <= 30.0),
    (df['mfe_pct'] > 30.0)
]
choices = [0, 1, 2, 3]
df['target_class'] = np.select(conditions, choices, default=0).astype(int)
df['target_label'] = df['target_class'].map(CLASS_NAMES)

# Class distribution table
class_counts = df['target_class'].value_counts().sort_index()
class_pcts = df['target_class'].value_counts(normalize=True).sort_index() * 100

print("=" * 50)
print("CLASS DISTRIBUTION")
print("=" * 50)
for cls in sorted(CLASS_NAMES.keys()):
    print(f"  {CLASS_NAMES[cls]}: {class_counts.get(cls, 0):>6,} ({class_pcts.get(cls, 0):.1f}%)")
print(f"  {'Total':<30s}: {len(df):>6,}")

# Visualizations
fig, axes = plt.subplots(1, 3, figsize=(20, 5))

# 5a. Raw MFE distribution (continuous)
axes[0].hist(df['mfe_pct'].clip(-10, 80), bins=80, color='steelblue', edgecolor='white', alpha=0.8)
for edge in [2, 10, 30]:
    axes[0].axvline(edge, color='red', linestyle='--', alpha=0.7, label=f'{edge}%')
axes[0].set_title('Raw MFE Distribution (clipped to [-10, 80])')
axes[0].set_xlabel('MFE %')
axes[0].legend()

# 5b. Class bar chart
bars = axes[1].bar(
    [CLASS_NAMES[c] for c in sorted(CLASS_NAMES)],
    [class_counts.get(c, 0) for c in sorted(CLASS_NAMES)],
    color=[CLASS_COLORS[c] for c in sorted(CLASS_NAMES)]
)
for bar, cls in zip(bars, sorted(CLASS_NAMES)):
    axes[1].text(bar.get_x() + bar.get_width()/2, bar.get_height() + 20,
                 f'{class_pcts.get(cls, 0):.1f}%', ha='center', fontsize=10)
axes[1].set_title('Class Distribution')
axes[1].set_ylabel('Count')
axes[1].tick_params(axis='x', rotation=25)

# 5c. Holding days density by class
for cls in sorted(CLASS_NAMES.keys()):
    subset = df[df['target_class'] == cls]
    if len(subset) > 0 and 'holding_days' in df.columns:
        sns.kdeplot(subset['holding_days'].clip(0, 500), ax=axes[2],
                    label=CLASS_NAMES[cls], color=CLASS_COLORS[cls],
                    fill=True, alpha=0.2, common_norm=False)
axes[2].set_title('Holding Days Density by MFE Class')
axes[2].set_xlabel('Holding Days')
axes[2].legend(fontsize=8)

plt.suptitle('Target Analysis', fontsize=14, y=1.02)
plt.tight_layout()
plt.show()


# ============================================================================
# CELL 6 — Warm-Up Clipping (Per-Ticker)
# ============================================================================
# Drop each ticker's leading rows where any sentinel is NULL.
# Global date clip (MIN_DATE) is applied first as a data-quality floor
# (C11 breakout_ok fix only backfilled to 2019).
# Per-ticker clip handles tickers that entered the universe later —
# a 2022 IPO still has 252-day RS warmup regardless of the global floor.

WARMUP_SENTINELS = ['rs', 'm03_score', 'dist_from_20d_high_delta']

df['date'] = pd.to_datetime(df['date'])

# Step 1: global data-quality floor
pre_clip = len(df)
df = df[df['date'] >= MIN_DATE].copy()
print(f"Global floor ({MIN_DATE}): {pre_clip:,} -> {len(df):,} rows")

# Step 2: per-ticker warmup clip — drop each ticker's leading NULL rows
df = df.sort_values(['ticker', 'date'])
sentinel_null = df[WARMUP_SENTINELS].isnull().any(axis=1)

# cumsum trick: within each ticker, rows before the first valid row have
# cumsum==0 on the inverted mask — drop those
is_valid = ~sentinel_null
df['_cumvalid'] = is_valid.groupby(df['ticker']).cumsum()
post_clip = len(df)
df = df[df['_cumvalid'] > 0].drop(columns='_cumvalid').copy()
print(f"Per-ticker warmup clip: {post_clip:,} -> {len(df):,} rows (removed {post_clip - len(df):,})")

# Verify residual null rate
residual = df[WARMUP_SENTINELS].isnull().mean()
print(f"\nResidual null rates after clip:")
for col, rate in residual.items():
    status = "✅" if rate < 0.001 else "⚠️"
    print(f"  {status} {col}: {rate:.4f}")
print(f"\nDate range: {df['date'].min().date()} to {df['date'].max().date()}")
print(f"Tickers retained: {df['ticker'].nunique()}")

# Year distribution
year_dist = df.groupby(df['date'].dt.year).agg(
    trades=('ticker', 'size'),
    tickers=('ticker', 'nunique'),
    avg_mfe=('mfe_pct', 'mean'),
    median_mfe=('mfe_pct', 'median')
).round(2)
print("\nTrades by Year:")
print(year_dist.to_string())


# ============================================================================
# CELL 7 — EDA: Spearman IC per Feature vs Target
# ============================================================================
all_features = [f for feats in FEATURE_GROUPS.values() for f in feats if f in df.columns]
print(f"Total candidate features: {len(all_features)}")

# Spearman rank correlation with target
ic_results = []
for feat in all_features:
    series = df[feat].replace([np.inf, -np.inf], np.nan).dropna()
    if len(series) < 100:
        continue
    aligned_target = df.loc[series.index, 'target_class']
    corr, pval = stats.spearmanr(series, aligned_target)
    ic_results.append({'feature': feat, 'spearman_ic': corr, 'pval': pval, 'abs_ic': abs(corr)})

ic_df = pd.DataFrame(ic_results).sort_values('abs_ic', ascending=False).reset_index(drop=True)

# Top 30 by absolute IC
print("\nTop 30 Features by |Spearman IC| vs target_class:")
print(ic_df.head(30).to_string(index=False))

# Bottom 10
print("\nBottom 10 (lowest IC, least predictive):")
print(ic_df.tail(10).to_string(index=False))

# IC bar chart — top 40
fig, ax = plt.subplots(figsize=(12, 10))
top40 = ic_df.head(40)
colors = ['#2ca02c' if x > 0 else '#d62728' for x in top40['spearman_ic']]
ax.barh(range(len(top40)), top40['spearman_ic'], color=colors)
ax.set_yticks(range(len(top40)))
ax.set_yticklabels(top40['feature'], fontsize=9)
ax.invert_yaxis()
ax.set_xlabel('Spearman IC')
ax.set_title('Top 40 Features: Spearman IC vs MFE Class')
ax.axvline(0, color='black', linewidth=0.5)
plt.tight_layout()
plt.show()


# ============================================================================
# CELL 8 — Multicollinearity: Correlation Heatmap + VIF Candidates
# ============================================================================
# Correlation among top features (top 40 by IC)
top_features = ic_df.head(40)['feature'].tolist()
corr_matrix = df[top_features].replace([np.inf, -np.inf], np.nan).corr(method='spearman')

fig, ax = plt.subplots(figsize=(16, 14))
mask = np.triu(np.ones_like(corr_matrix, dtype=bool))
sns.heatmap(
    corr_matrix, mask=mask, cmap='RdBu_r', center=0,
    vmin=-1, vmax=1, annot=False, ax=ax,
    xticklabels=True, yticklabels=True
)
ax.set_title('Spearman Correlation: Top 40 Features')
plt.xticks(fontsize=8, rotation=90)
plt.yticks(fontsize=8)
plt.tight_layout()
plt.show()

# Flag highly correlated pairs (|r| > 0.85)
HIGH_CORR_THRESHOLD = 0.85
pairs = []
for i in range(len(corr_matrix)):
    for j in range(i + 1, len(corr_matrix)):
        r = corr_matrix.iloc[i, j]
        if abs(r) > HIGH_CORR_THRESHOLD:
            pairs.append({
                'feat_a': corr_matrix.index[i],
                'feat_b': corr_matrix.columns[j],
                'corr': round(r, 3)
            })

pairs_df = pd.DataFrame(pairs).sort_values('corr', key=abs, ascending=False)
print(f"\nHighly Correlated Pairs (|r| > {HIGH_CORR_THRESHOLD}):")
print(pairs_df.to_string(index=False))
print(f"\nTotal pairs: {len(pairs_df)}")


# ============================================================================
# CELL 9 — Feature Selection: Build Final Feature Set
# ============================================================================
# Strategy: Start with all features, then drop:
# 1. Low IC features (|IC| < 0.02)
# 2. One from each highly-correlated pair (keep higher IC)

# Step 1: Filter by IC threshold
IC_THRESHOLD = 0.02
ic_pass = ic_df[ic_df['abs_ic'] >= IC_THRESHOLD]['feature'].tolist()
print(f"After IC filter (>= {IC_THRESHOLD}): {len(ic_pass)} features (dropped {len(all_features) - len(ic_pass)})")

# Step 2: Drop from correlated pairs (keep higher IC)
ic_lookup = ic_df.set_index('feature')['abs_ic'].to_dict()
to_drop = set()

for _, row in pairs_df.iterrows():
    a, b = row['feat_a'], row['feat_b']
    if a in ic_pass and b in ic_pass:
        # Drop the one with lower IC
        if ic_lookup.get(a, 0) >= ic_lookup.get(b, 0):
            to_drop.add(b)
        else:
            to_drop.add(a)

selected_features = [f for f in ic_pass if f not in to_drop]
print(f"After collinearity pruning: {len(selected_features)} features (dropped {len(to_drop)}: {sorted(to_drop)})")

# Categoricals (sector, industry) — add if present
CATEGORICAL_FEATURES = []
for cat in ['sector', 'industry']:
    if cat in df.columns and df[cat].nunique() > 1:
        df[cat] = df[cat].astype('category')
        CATEGORICAL_FEATURES.append(cat)
        selected_features.append(cat)

print(f"\nFinal feature set: {len(selected_features)} features")
print(f"  Categorical: {CATEGORICAL_FEATURES}")
print(f"  Numeric: {len(selected_features) - len(CATEGORICAL_FEATURES)}")


# ============================================================================
# CELL 10 — Walk-Forward Validation Setup
# ============================================================================
import xgboost as xgb
from sklearn.utils.class_weight import compute_class_weight
from sklearn.metrics import classification_report, confusion_matrix, f1_score, accuracy_score

df['year'] = df['date'].dt.year
years = sorted(df['year'].unique())
print(f"Available years: {years}")

TRAIN_WINDOW = 3  # years
TEST_WINDOW = 1   # year

folds = []
for i in range(len(years) - TRAIN_WINDOW):
    train_years = years[i:i + TRAIN_WINDOW]
    test_year = years[i + TRAIN_WINDOW]
    if test_year > years[-1]:
        break
    folds.append({'train_years': train_years, 'test_year': test_year})

print(f"\nWalk-Forward Folds ({len(folds)}):")
for fold in folds:
    train_n = df[df['year'].isin(fold['train_years'])].shape[0]
    test_n = df[df['year'] == fold['test_year']].shape[0]
    print(f"  Train {fold['train_years']} ({train_n:,}) -> Test [{fold['test_year']}] ({test_n:,})")


# ============================================================================
# CELL 11 — Model Training: Walk-Forward XGBoost
# ============================================================================
XGB_PARAMS = {
    'objective': 'multi:softprob',
    'num_class': 4,
    'max_depth': 4,
    'learning_rate': 0.05,
    'subsample': 0.8,
    'colsample_bytree': 0.8,
    'eval_metric': 'mlogloss',
    'tree_method': 'hist',
    'enable_categorical': True,
    'random_state': 42,
    'verbosity': 0
}
NUM_BOOST_ROUND = 300
EARLY_STOPPING = 30

numeric_features = [f for f in selected_features if f not in CATEGORICAL_FEATURES]

fold_results = []
fold_models = []
all_test_preds = []

for fold_idx, fold in enumerate(folds):
    print(f"\n{'='*60}")
    print(f"FOLD {fold_idx + 1}: Train {fold['train_years']} -> Test [{fold['test_year']}]")
    print(f"{'='*60}")

    train_mask = df['year'].isin(fold['train_years'])
    test_mask = df['year'] == fold['test_year']

    X_train = df.loc[train_mask, selected_features].copy()
    y_train = df.loc[train_mask, 'target_class'].values
    X_test = df.loc[test_mask, selected_features].copy()
    y_test = df.loc[test_mask, 'target_class'].values

    # Clean inf values (numeric only)
    X_train[numeric_features] = X_train[numeric_features].replace([np.inf, -np.inf], np.nan)
    X_test[numeric_features] = X_test[numeric_features].replace([np.inf, -np.inf], np.nan)

    # Class weights
    classes = np.unique(y_train)
    weights = compute_class_weight('balanced', classes=classes, y=y_train)
    weight_map = dict(zip(classes, weights))
    sample_weights = np.array([weight_map.get(y, 1.0) for y in y_train])

    # DMatrix
    dtrain = xgb.DMatrix(X_train, label=y_train, weight=sample_weights, enable_categorical=True)
    dtest = xgb.DMatrix(X_test, label=y_test, enable_categorical=True)

    # Train with early stopping (use 20% of train as eval)
    eval_split = int(len(X_train) * 0.8)
    dtrain_fit = xgb.DMatrix(
        X_train.iloc[:eval_split], label=y_train[:eval_split],
        weight=sample_weights[:eval_split], enable_categorical=True
    )
    deval = xgb.DMatrix(
        X_train.iloc[eval_split:], label=y_train[eval_split:], enable_categorical=True
    )

    model = xgb.train(
        params=XGB_PARAMS,
        dtrain=dtrain_fit,
        num_boost_round=NUM_BOOST_ROUND,
        evals=[(dtrain_fit, 'train'), (deval, 'eval')],
        early_stopping_rounds=EARLY_STOPPING,
        verbose_eval=False
    )

    # Predict
    y_pred_proba = model.predict(dtest)
    y_pred = np.argmax(y_pred_proba, axis=1)

    # Metrics
    acc = accuracy_score(y_test, y_pred)
    w_f1 = f1_score(y_test, y_pred, average='weighted', zero_division=0)
    m_f1 = f1_score(y_test, y_pred, average='macro', zero_division=0)
    per_class_f1 = f1_score(y_test, y_pred, average=None, zero_division=0)

    fold_result = {
        'fold': fold_idx + 1,
        'test_year': fold['test_year'],
        'n_train': len(X_train),
        'n_test': len(X_test),
        'best_iteration': model.best_iteration,
        'accuracy': acc,
        'weighted_f1': w_f1,
        'macro_f1': m_f1
    }
    for cls_idx, cls_name in CLASS_NAMES.items():
        if cls_idx < len(per_class_f1):
            fold_result[f'f1_class_{cls_idx}'] = per_class_f1[cls_idx]
    fold_results.append(fold_result)
    fold_models.append(model)

    # Store predictions for aggregate analysis
    test_df = df.loc[test_mask, ['ticker', 'date', 'mfe_pct', 'target_class']].copy()
    test_df['y_pred'] = y_pred
    test_df['fold'] = fold_idx + 1
    for c in range(4):
        test_df[f'prob_class_{c}'] = y_pred_proba[:, c]
    all_test_preds.append(test_df)

    print(f"  Acc={acc:.3f} | W-F1={w_f1:.3f} | M-F1={m_f1:.3f} | best_iter={model.best_iteration}")
    print(f"  Per-class F1: {[f'{x:.3f}' for x in per_class_f1]}")

results_df = pd.DataFrame(fold_results)
preds_df = pd.concat(all_test_preds, ignore_index=True)

print("\n" + "=" * 60)
print("WALK-FORWARD SUMMARY")
print("=" * 60)
print(results_df.to_string(index=False))
print(f"\nMean Accuracy:    {results_df['accuracy'].mean():.3f} +/- {results_df['accuracy'].std():.3f}")
print(f"Mean Weighted F1: {results_df['weighted_f1'].mean():.3f} +/- {results_df['weighted_f1'].std():.3f}")
print(f"Mean Macro F1:    {results_df['macro_f1'].mean():.3f} +/- {results_df['macro_f1'].std():.3f}")


# ============================================================================
# CELL 12 — Walk-Forward Stability Plot
# ============================================================================
fig, axes = plt.subplots(1, 2, figsize=(16, 5))

# 12a. Metrics across folds
axes[0].plot(results_df['test_year'], results_df['accuracy'], 'o-', label='Accuracy')
axes[0].plot(results_df['test_year'], results_df['weighted_f1'], 's-', label='Weighted F1')
axes[0].plot(results_df['test_year'], results_df['macro_f1'], '^-', label='Macro F1')
axes[0].set_xlabel('Test Year')
axes[0].set_ylabel('Score')
axes[0].set_title('Walk-Forward Stability')
axes[0].legend()
axes[0].set_ylim(0, 1)
axes[0].grid(True, alpha=0.3)

# 12b. Per-class F1 across folds
for cls_idx in sorted(CLASS_NAMES.keys()):
    col = f'f1_class_{cls_idx}'
    if col in results_df.columns:
        axes[1].plot(results_df['test_year'], results_df[col], 'o-',
                     label=CLASS_NAMES[cls_idx], color=CLASS_COLORS[cls_idx])
axes[1].set_xlabel('Test Year')
axes[1].set_ylabel('F1 Score')
axes[1].set_title('Per-Class F1 Across Folds')
axes[1].legend(fontsize=8)
axes[1].set_ylim(0, 1)
axes[1].grid(True, alpha=0.3)

plt.tight_layout()
plt.show()


# ============================================================================
# CELL 13 — Aggregate Confusion Matrix (all OOS folds)
# ============================================================================
cm = confusion_matrix(preds_df['target_class'], preds_df['y_pred'])
cm_pct = cm.astype(float) / cm.sum(axis=1, keepdims=True) * 100

fig, axes = plt.subplots(1, 2, figsize=(16, 6))

# Raw counts
sns.heatmap(cm, annot=True, fmt='d', cmap='Blues', ax=axes[0],
            xticklabels=[f'Pred {c}' for c in CLASS_NAMES.keys()],
            yticklabels=[CLASS_NAMES[c] for c in CLASS_NAMES.keys()])
axes[0].set_title('Confusion Matrix (Counts)')
axes[0].set_ylabel('Actual')

# Normalized (%)
sns.heatmap(cm_pct, annot=True, fmt='.1f', cmap='Blues', ax=axes[1],
            xticklabels=[f'Pred {c}' for c in CLASS_NAMES.keys()],
            yticklabels=[CLASS_NAMES[c] for c in CLASS_NAMES.keys()])
axes[1].set_title('Confusion Matrix (Row-Normalized %)')
axes[1].set_ylabel('Actual')

plt.tight_layout()
plt.show()

# Per-class precision/recall from aggregate predictions
print("\nAggregate OOS Classification Report:")
print(classification_report(
    preds_df['target_class'], preds_df['y_pred'],
    target_names=[CLASS_NAMES[c] for c in sorted(CLASS_NAMES.keys())],
    zero_division=0
))


# ============================================================================
# CELL 14 — Feature Importance (Last Fold)
# ============================================================================
last_model = fold_models[-1]
importance = last_model.get_score(importance_type='gain')

# Map feature indices to names
imp_data = []
for feat, gain in importance.items():
    if feat.startswith('f') and feat[1:].isdigit():
        idx = int(feat[1:])
        if idx < len(selected_features):
            imp_data.append({'feature': selected_features[idx], 'gain': gain})
    else:
        imp_data.append({'feature': feat, 'gain': gain})

imp_df = pd.DataFrame(imp_data).sort_values('gain', ascending=False).reset_index(drop=True)

fig, ax = plt.subplots(figsize=(12, 10))
top30 = imp_df.head(30)
ax.barh(range(len(top30)), top30['gain'], color='steelblue')
ax.set_yticks(range(len(top30)))
ax.set_yticklabels(top30['feature'], fontsize=9)
ax.invert_yaxis()
ax.set_xlabel('Gain')
ax.set_title('Top 30 Feature Importance (XGBoost Gain, Last Fold)')
plt.tight_layout()
plt.show()

# EMA feature importance
ema_imp = imp_df[imp_df['feature'].isin(EMA_FEATURES)]
print("\nEMA Feature Importance:")
print(ema_imp.to_string(index=False) if len(ema_imp) > 0 else "  No EMA features used by model")


# ============================================================================
# CELL 15 — Calibration: Predicted Probability vs Actual Outcome
# ============================================================================
fig, axes = plt.subplots(2, 2, figsize=(14, 10))

for cls_idx, ax in zip(sorted(CLASS_NAMES.keys()), axes.flatten()):
    prob_col = f'prob_class_{cls_idx}'
    actual_binary = (preds_df['target_class'] == cls_idx).astype(int)
    predicted_prob = preds_df[prob_col]

    # Bin predicted probabilities
    bins = np.linspace(0, 1, 11)
    bin_indices = np.digitize(predicted_prob, bins) - 1
    bin_indices = np.clip(bin_indices, 0, len(bins) - 2)

    bin_means = []
    bin_actuals = []
    bin_counts = []
    for b in range(len(bins) - 1):
        mask = bin_indices == b
        if mask.sum() > 0:
            bin_means.append(predicted_prob[mask].mean())
            bin_actuals.append(actual_binary[mask].mean())
            bin_counts.append(mask.sum())

    if len(bin_means) > 0:
        ax.plot(bin_means, bin_actuals, 'o-', color=CLASS_COLORS[cls_idx], label='Model')
        ax.plot([0, 1], [0, 1], '--', color='gray', alpha=0.5, label='Perfect')
        ax.set_xlabel('Predicted Probability')
        ax.set_ylabel('Actual Frequency')
        ax.set_title(f'{CLASS_NAMES[cls_idx]}')
        ax.legend(fontsize=8)
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)

plt.suptitle('Calibration Curves (All OOS Folds)', fontsize=13)
plt.tight_layout()
plt.show()


# ============================================================================
# CELL 16 — EMA Feature Deep Dive: Distribution by Class
# ============================================================================
ema_to_plot = [f for f in EMA_FEATURES if f in df.columns]

fig, axes = plt.subplots(3, 3, figsize=(18, 14))
axes = axes.flatten()

for i, feat in enumerate(ema_to_plot[:9]):
    ax = axes[i]
    for cls in sorted(CLASS_NAMES.keys()):
        subset = df[df['target_class'] == cls][feat].dropna()
        if len(subset) > 10:
            sns.kdeplot(subset.clip(subset.quantile(0.01), subset.quantile(0.99)),
                        ax=ax, label=CLASS_NAMES[cls], color=CLASS_COLORS[cls],
                        fill=True, alpha=0.15, common_norm=False)
    ax.set_title(feat, fontsize=10)
    ax.legend(fontsize=6)

plt.suptitle('EMA Feature Distributions by MFE Class', fontsize=13, y=1.01)
plt.tight_layout()
plt.show()


# ============================================================================
# CELL 17 — Summary & Next Steps
# ============================================================================
print("=" * 70)
print("PROTOTYPE SUMMARY")
print("=" * 70)
print(f"Dataset:          {len(df):,} rows, {df['ticker'].nunique()} tickers, {df['date'].min().date()} to {df['date'].max().date()}")
print(f"Features:         {len(selected_features)} ({len(CATEGORICAL_FEATURES)} categorical)")
print(f"  - EMA features: {len(EMA_FEATURES)} new")
print(f"Walk-Forward:     {len(folds)} folds ({TRAIN_WINDOW}yr train, {TEST_WINDOW}yr test)")
print(f"Mean Accuracy:    {results_df['accuracy'].mean():.3f}")
print(f"Mean Weighted F1: {results_df['weighted_f1'].mean():.3f}")
print(f"Mean Macro F1:    {results_df['macro_f1'].mean():.3f}")
print()
print("Per-Class F1 (mean across folds):")
for cls_idx in sorted(CLASS_NAMES.keys()):
    col = f'f1_class_{cls_idx}'
    if col in results_df.columns:
        print(f"  {CLASS_NAMES[cls_idx]}: {results_df[col].mean():.3f}")
print()
print("EMA Features in Top 30 Importance:")
if len(ema_imp) > 0:
    for _, row in ema_imp.iterrows():
        rank = imp_df[imp_df['feature'] == row['feature']].index[0] + 1
        print(f"  #{rank}: {row['feature']} (gain={row['gain']:.1f})")
else:
    print("  None (model didn't find EMA features useful)")
print()
print("Next Steps:")
print("  1. Check per-class F1 — is Class 3 (Elite) being recalled?")
print("  2. Try SMOTE / cost-sensitive weighting if class imbalance is severe")
print("  3. Tune bin edges if class 0 dominates")
print("  4. Add SHAP analysis for interpretability")
print("  5. Register best model via ModelRegistry if metrics improve")
