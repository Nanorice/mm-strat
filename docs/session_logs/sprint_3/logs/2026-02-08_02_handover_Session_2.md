# Session Handover: 2026-02-08

## Goal
Enhance the EDA pipeline to fix categorical feature handling (industry_id/sector_id), exclude leakage features, and add a Candidate Profile analysis to the D1 Analysis dashboard page.

## Accomplished
- Fixed critical bug: `industry_id` was being treated as linear numeric feature when it's actually categorical (IDs have no ordinal meaning)
- Added `LEAKAGE_FEATURES` list to exclude MFE, MAE, y_max, regret, return_pct, exit_reason from feature screening
- Added `CATEGORICAL_FEATURES` list for sector_id and industry_id
- Implemented target encoding for categorical features with Bayesian smoothing
- Created unified EDA output pipeline generating both `eda_report.md` and `eda_dashboard.json` from single computation
- Added "EDA Screening" page to dashboard with 4 tabs: Feature Leaderboard, KS Distributions, Decile Plots, IC Stability
- Added "Candidate Profile Analysis" to D1 Analysis page with:
  - Filter Sensitivity Plot (RS threshold yield curve)
  - Sector/Industry Efficiency scatter plots
  - Fundamental Sanity Check (price/mktCap/beta distributions)

## Files Changed
- `src/feature_config.py`: Added LEAKAGE_FEATURES, CATEGORICAL_FEATURES, updated FEATURE_EXCLUSION_LIST
- `src/evaluation/feature_screener.py`: Added target_encode_categorical(), encode_categorical_features(), _compute_candidate_profile(), export_dashboard_json(), generate_all_outputs()
- `src/dashboard_reports.py`: Added render_eda_feature_screening(), _render_filter_sensitivity(), _render_sector_efficiency(), _render_fundamental_sanity(), load_eda_dashboard()
- `dashboard.py`: Added EDA Screening page to navigation
- `src/pipeline/m01_trainer.py`: Removed duplicate candidate profile code (moved to feature_screener)
- `src/pipeline/m01_workflow.py`: Updated to use generate_all_outputs()

## Work in Progress (CRITICAL)
- None - all changes are complete and tested for import errors
- The candidate profile data will only appear after running: `python model_runner.py workflow --start 2020-01-01 --end 2023-12-31 --steps load eda select`

## Next Steps
1. Run the EDA workflow to regenerate `eda_dashboard.json` with the new candidate profile data
2. Verify dashboard visualizations render correctly in browser
3. Consider adding MFE (Maximum Favorable Excursion) per sector if MFE data becomes available in the EDA dataset

## Context/Memory
- **Target Encoding Formula**: `encoded = (n * category_mean + m * global_mean) / (n + m)` where n=samples in category, m=smoothing factor
- **Data Flow**: The Candidate Profile is now part of the EDA pipeline (not M01 training), so it uses the same CLI: `workflow --steps eda`
- **Dashboard loads from JSON**: All visualizations read from pre-computed `models/eda_dashboard.json` - no live computation
- **rs_rating scale**: The rs_rating field is 0-1 (not 0-100), so threshold comparisons divide by 100
