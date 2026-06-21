# EDA Pipeline Module Passport

**Module**: EDA Pipeline (Feature Evaluation & Screening)
**Owner**: model_runner.py → M01Workflow
**Last Updated**: 2026-02-08

---

## Table of Contents: Text vs Dashboard Mapping

| Section | Text Report (eda_report.md) | Dashboard (eda_dashboard.json) | Status |
|---------|----------------------------|--------------------------------|--------|
| **0. Dataset Overview** | | | |
| - Target distribution (mean, median, skewness) | Section 0 | `dataset_stats` | ✅ Both |
| - Return distribution histogram | Section 0 (text buckets) | ❌ Missing | ⚠️ Text only |
| - Holding period stats | Section 0 | ❌ Missing | ⚠️ Text only |
| - Temporal coverage (yearly samples) | Section 0 | `dataset_stats.date_range` | ⚠️ Partial |
| - Sector/Industry breakdown | Section 0 | `sector_efficiency`, `industry_efficiency` | ✅ Both |
| **1. Feature Leaderboard** | | | |
| - Top 30 features ranked by composite | Section 1 | `feature_scores` | ✅ Both |
| - Signal type classification | Section 1 | `feature_scores[].signal_type` | ✅ Both |
| **2. Monotonicity Deep Dive** | | | |
| - Decile mean returns (bar chart) | Section 2 (ASCII art) | `decile_stats` | ✅ Both |
| - **Box plot with variance** | ❌ Missing | ❌ Missing | 🆕 **TO ADD** |
| - **Per-industry box plots** | ❌ Missing | ❌ Missing | 🆕 **TO ADD** |
| **3. Stability Analysis** | | | |
| - Per-year IC table | Section 3 | `ic_time_series` | ✅ Both |
| - Regime-conditional flags | Section 3 | `ic_time_series[].is_regime_conditional` | ✅ Both |
| **4. Correlation Clusters** | | | |
| - Cluster members | Section 4 | `correlation_clusters` | ✅ Both |
| - Keep/Drop recommendations | Section 4 | `correlation_clusters` | ✅ Both |
| **5. Distributional Warnings** | | | |
| - High kurtosis alerts | Section 5 | ❌ Missing | ⚠️ Text only |
| **6. Transformation Summary** | | | |
| - Log-transformed features | Section 6 | `transform_summary.log` | ✅ Both |
| - Winsorized features | Section 6 | `transform_summary.winsorized` | ✅ Both |
| - TAR values | Section 6 | `transform_summary.tail_alpha_ratios` | ✅ Both |
| **7. Candidate Profile (D1)** | | | |
| - Filter sensitivity (RS threshold) | ❌ Missing | `filter_sensitivity` | ⚠️ Dashboard only |
| - Sector/Industry efficiency | ❌ Missing | `sector_efficiency`, `industry_efficiency` | ⚠️ Dashboard only |
| - Fundamental sanity (price, mktCap) | ❌ Missing | `fundamental_sanity` | ⚠️ Dashboard only |
| **8. Super-Performer Analysis** | | | |
| - **Return histogram by RS decile** | ❌ Missing | ❌ Missing | 🆕 **TO ADD** |
| - **Fat-tail yield (>100% winners)** | ❌ Missing | ❌ Missing | 🆕 **TO ADD** |

---

## Dashboard Page Structure (Current)

```
📊 Dashboard Navigation
├── 🏠 Overview
├── 📊 D1 Analysis
│   ├── Trade Physics (MAE/MFE, E-Ratio)
│   └── Candidate Profile (Filter Sensitivity, Sector Efficiency, Fundamental Sanity)
├── 📈 M01 Report
├── 🎯 M02 Report
├── 🔀 Dual-Model
├── 📊 Backtest
└── 📊 EDA Screening
    ├── Tab 1: Feature Leaderboard
    ├── Tab 2: KS Distributions
    ├── Tab 3: Decile Plots (mean bar charts)
    └── Tab 4: IC Stability
```

## Dashboard Page Structure (Proposed)

```
📊 Dashboard Navigation
├── 🏠 Overview
├── 📊 EDA Summary (NEW - unified EDA page)
│   ├── Tab 1: D1 Trade Physics (from D1 Analysis)
│   ├── Tab 2: SEPA Criteria Analysis
│   │   ├── rs_rating box plots (NEW)
│   │   ├── Super-Performer histogram (NEW)
│   │   └── Industry box plots (NEW - replace monotonicity)
│   ├── Tab 3: D2 Feature Analysis (from EDA Screening)
│   │   ├── Feature Leaderboard
│   │   ├── KS Distributions
│   │   ├── Decile Plots
│   │   └── IC Stability
│   └── Tab 4: Candidate Profile (from D1 Analysis)
│       ├── Filter Sensitivity
│       ├── Sector/Industry Efficiency
│       └── Fundamental Sanity
├── 📈 M01 Report
├── 🎯 M02 Report
├── 🔀 Dual-Model
└── 📊 Backtest
```

---

## Phase 1 Enhancements (This Session)

### 1. Monotonicity Box Plots (Replace Mean Bar Charts)
**Current**: `decile_stats` only stores mean per decile
**Required**: Add percentiles (min, Q1, median, Q3, max) per decile

**Data Structure Change** in `eda_dashboard.json`:
```json
"decile_stats": {
  "rs_rating": {
    "decile_returns": [0.83, 0.84, 1.03, ...],  // Keep for backward compat
    "decile_box": [
      {"decile": 1, "min": -50.2, "q1": -8.5, "median": -3.1, "q3": 2.1, "max": 45.2, "count": 2055},
      {"decile": 2, "min": -48.1, "q1": -7.2, ...},
      ...
    ]
  }
}
```

### 2. Per-Industry Box Plots (Replace Monotonicity for Categoricals)
**Current**: `industry_id_encoded` treated as linear (meaningless)
**Required**: Box plot of `return_pct` per industry (top 15 by frequency)

**New Data Structure**:
```json
"industry_performance": [
  {"industry": "Banks - Regional", "count": 1167, "median": -2.1, "q1": -6.5, "q3": 3.2, "min": -45, "max": 120},
  {"industry": "Biotechnology", "count": 841, ...},
  ...
]
```

### 3. Super-Performer Histogram
**Purpose**: Show fat-tail distribution in high-RS stocks
**Data Structure**:
```json
"super_performer_analysis": {
  "rs_decile_10": {
    "return_bins": ["<0", "0-20", "20-50", "50-100", ">100"],
    "counts": [450, 320, 180, 95, 42],
    "pct_home_runs": 4.1  // % with >100% return
  },
  "rs_decile_5": {
    "return_bins": [...],
    "counts": [620, 280, 80, 15, 2],
    "pct_home_runs": 0.2
  }
}
```

---

## Data Pipeline

```
┌─────────────────────────────────────────────────────────────┐
│                    model_runner.py workflow                 │
│                     --steps eda                             │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                   M01Workflow._run_eda()                    │
│                   (src/pipeline/m01_workflow.py)            │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│             FeatureScreener.run_quant_pipeline()            │
│             (src/evaluation/feature_screener.py)            │
│                                                             │
│  Steps:                                                     │
│  1. Pre-filter (remove exclusions)                          │
│  2. Target-encode categoricals                              │
│  3. Fat-tail transforms                                     │
│  4. 4-Pillar Analysis (IC, stability, KS, correlation)      │
│  5. Composite scoring                                       │
│  6. Correlation pruning                                     │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│           FeatureScreener.generate_all_outputs()            │
│                                                             │
│  Outputs:                                                   │
│  - models/eda_report.md (text report)                       │
│  - models/eda_dashboard.json (dashboard data)               │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                  Dashboard (Streamlit)                      │
│                  (src/dashboard_reports.py)                 │
│                                                             │
│  Loads: models/eda_dashboard.json                           │
│  Renders: render_eda_feature_screening()                    │
└─────────────────────────────────────────────────────────────┘
```

---

## Files Modified (Phase 1)

| File | Change |
|------|--------|
| `src/evaluation/feature_screener.py` | Add box plot stats, industry performance, super-performer analysis |
| `src/dashboard_reports.py` | Add box plot visualization, industry box plots, super-performer histogram |
| `models/eda_dashboard.json` | Extended schema (backward compatible) |

---

## Testing

```bash
# Regenerate EDA with new stats (short period for speed)
python model_runner.py workflow --start 2023-01-01 --end 2023-12-31 --steps load eda

# Verify JSON output
python -c "import json; d=json.load(open('models/eda_dashboard.json')); print(d.keys())"

# Check dashboard renders
streamlit run dashboard.py
```

---

## Implementation Status (2026-02-08)

### Completed
- [x] Table of Contents mapping created
- [x] `decile_box_stats` - Box plot statistics per RS decile (min/Q1/median/Q3/max)
- [x] `industry_performance` - Per-industry box plots (top 20)
- [x] `super_performer_analysis` - Fat-tail histogram by RS decile
- [x] Dashboard rendering updated with 6 tabs

### JSON Schema (New Keys)

```json
{
  "decile_box_stats": {
    "rs_rating": [
      {"decile": 1, "count": 2055, "min": -50.2, "q1": -8.5, "median": -3.1, "mean": 0.8, "q3": 2.1, "max": 45.2, "std": 12.3},
      ...
    ],
    "RS_Universe_Rank": [...],
    "Price_vs_SMA_200": [...],
    "alpha011": [...]
  },
  "industry_performance": [
    {"industry": "Banks - Regional", "count": 1167, "median": -2.04, "mean": 1.5, "q1": -6.5, "q3": 3.2, "win_rate": 35.2, "pct_gt_50": 2.1},
    ...
  ],
  "super_performer_analysis": {
    "decile_1": {"return_bins": ["<0%", "0-20%", ...], "counts": [450, 320, ...], "pct_home_runs": 0.0},
    "decile_5": {"return_bins": [...], "counts": [...], "pct_home_runs": 0.1},
    "decile_10": {"return_bins": [...], "counts": [...], "pct_home_runs": 1.4}
  }
}
```

### Dashboard Tab Structure (Updated)

```
EDA Screening Page
├── Tab 1: Feature Leaderboard (unchanged)
├── Tab 2: KS Distributions (unchanged)
├── Tab 3: Decile Box Plots (NEW - replaces bar charts)
├── Tab 4: Industry Analysis (NEW - categorical box plots)
├── Tab 5: Super-Performers (NEW - home run histogram)
└── Tab 6: IC Stability (moved from Tab 4)
```

### Key Findings from Initial Run
- D10 (highest RS) has 1.4% home runs (>100% return)
- D1 (lowest RS) has 0% home runs
- This validates: **Relative Strength is the gateway to Super-Performers**
