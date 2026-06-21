"""
Universe Scorer - Optimized Batch M01 Scoring for Backtesting
==============================================================
Pre-computes M01 calibrated scores using D2 dataset (pre-computed features).

Key Optimization: D2 contains 19,484 trade candidates with all features already
computed. Instead of iterating through each ticker and recomputing features,
we perform vectorized scoring on the entire dataset in one pass.

Output:
- Calibrated M01 score per (date, ticker)
- Normalized score: percentile rank within each ticker's signal history
- Daily percentile rank (for top 5% filtering)
"""

import json
import logging
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

import duckdb
from src import db

import config
from src.utils import get_model_features

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = config.DATA_DIR / 'market_data.duckdb'


class UniverseScorer:
    """
    Vectorized scorer using D2 dataset.

    D2 contains SEPA trade candidates with pre-computed features.
    This is orders of magnitude faster than per-ticker feature computation.
    """

    def __init__(
        self,
        m01_path: str = 'models/m01.json',
        calibration_path: Optional[str] = 'models/m01_calibration.json',
    ):
        self.m01_path = Path(m01_path)
        self.calibration_path = Path(calibration_path) if calibration_path else None
        self.m01_model = None
        self.calibration_bins = None
        self.calibration_values = None
        self._m01_features: list[str] = []
        self._is_classifier = False
        self._is_binary = False
        self._num_classes = 0
        # Isotonic calibrator (separate from the legacy decile calibration_path).
        # Looked up at load_model() time as <m01_path.parent>/calibrator.joblib
        # — co-located with the model so signal-gen finds it automatically.
        self._iso_calibrator = None

    def load_model(self):
        """Load M01 model and calibration table."""
        import xgboost as xgb

        if not self.m01_path.exists():
            raise FileNotFoundError(f"M01 model not found: {self.m01_path}")

        # Detect model type from booster config
        booster = xgb.Booster()
        booster.load_model(str(self.m01_path))
        model_config = json.loads(booster.save_config())
        objective = model_config.get('learner', {}).get('objective', {}).get('name', '')
        num_class = model_config.get('learner', {}).get('learner_model_param', {}).get('num_class', '0')

        if 'softprob' in objective or 'softmax' in objective:
            self.m01_model = xgb.XGBClassifier()
            self._is_classifier = True
            self._num_classes = int(num_class)
            logger.info(f"M01 is a {self._num_classes}-class classifier (objective={objective})")
        elif 'binary' in objective:
            # binary:logistic returns 1-D P(class=1); we treat it as a 2-class
            # classifier with the positive class as the production class.
            self.m01_model = xgb.XGBClassifier()
            self._is_classifier = True
            self._num_classes = 2
            self._is_binary = True
            logger.info(f"M01 is a binary classifier (objective={objective})")
        else:
            self.m01_model = xgb.XGBRegressor()
            self._is_classifier = False
            self._num_classes = 0

        self.m01_model.load_model(str(self.m01_path))
        logger.info(f"Loaded M01 from {self.m01_path}")

        # Look for an isotonic calibrator co-located with the model (created by
        # the trainer when --with-calibration is set).
        iso_path = self.m01_path.parent / "calibrator.joblib"
        if iso_path.exists():
            try:
                from src.evaluation.calibrator import IsotonicCalibrator
                self._iso_calibrator = IsotonicCalibrator.load(iso_path)
                logger.info(f"Loaded isotonic calibrator from {iso_path}")
            except Exception as e:
                logger.warning(f"Failed to load isotonic calibrator: {e}")

        if self.calibration_path and self.calibration_path.exists():
            with open(self.calibration_path) as f:
                cal_data = json.load(f)
            deciles = cal_data.get('deciles', [])
            if deciles:
                # Build bins for pd.cut: [-inf, pred_max_1, pred_max_2, ..., inf]
                bins = [-np.inf]
                values = []
                for d in deciles:
                    bins.append(d['pred_max'])
                    values.append(d['calibrated_mean'])
                self.calibration_bins = bins
                self.calibration_values = values
                logger.info(f"Loaded calibration table with {len(deciles)} deciles")
        else:
            logger.warning(f"No calibration table at {self.calibration_path}")

        # Load features from model metadata (source of truth)
        # Try metadata.json first, then config.json, then feature_config fallback
        metadata_path = self.m01_path.with_name('metadata.json')
        m01_config_path = self.m01_path.with_name('config.json')
        m01_config_flat = self.m01_path.with_name('m01_config.json')

        if metadata_path.exists():
            with open(metadata_path) as f:
                metadata = json.load(f)
            self._m01_features = metadata.get('valid_features', [])
            logger.info(f"M01 uses {len(self._m01_features)} features (from metadata.json)")
        elif m01_config_path.exists():
            with open(m01_config_path) as f:
                m01_config = json.load(f)
            self._m01_features = m01_config.get('feature_columns', [])
            logger.info(f"M01 uses {len(self._m01_features)} features (from config.json)")
        elif m01_config_flat.exists():
            with open(m01_config_flat) as f:
                m01_config = json.load(f)
            self._m01_features = m01_config.get('feature_columns', [])
            logger.info(f"M01 uses {len(self._m01_features)} features (from m01_config.json)")
        else:
            self._m01_features = get_model_features('M01', db_path=str(DEFAULT_DB_PATH))
            logger.info(f"M01 uses {len(self._m01_features)} features (from model_feature_sets)")

    def _compute_trailing_percentile(
        self,
        df: pd.DataFrame,
        window: int = 10,
        score_col: str = 'calibrated_score',
    ) -> pd.Series:
        """
        Compute trailing N-day cohort percentile for each row.

        For each (date, ticker), returns what percentile this score occupies
        relative to ALL scores from the past N trading days (inclusive).

        Vectorized O(N log N) implementation using searchsorted — replaces the
        original O(N²) nested loop.
        """
        # Work on a clean copy with original index preserved
        work = df[['date', score_col]].copy()
        unique_dates = sorted(work['date'].unique())
        n_dates = len(unique_dates)

        # Build a mapping date → integer position
        date_pos = {d: i for i, d in enumerate(unique_dates)}
        work['_dpos'] = work['date'].map(date_pos)

        # Sort all scores globally so we can use searchsorted per window
        # Group by date position to get boundary indices in sorted order
        # Strategy: for each target date d, collect scores from the window
        # [d-window+1 .. d] in O(window) date lookups, then searchsorted.
        #
        # We pre-sort scores by date so that slicing a date range is O(1).
        sorted_by_date = work.sort_values('_dpos')
        scores_arr = sorted_by_date[score_col].values           # all scores sorted by date
        dpos_arr   = sorted_by_date['_dpos'].values             # corresponding date positions

        # Boundary index for each date position (first occurrence in sorted array)
        # date_start[i] = index of first row with _dpos == i in sorted_by_date
        date_start = np.searchsorted(dpos_arr, np.arange(n_dates), side='left')
        date_end   = np.searchsorted(dpos_arr, np.arange(n_dates), side='right')

        result = np.empty(len(work), dtype=float)

        for i, d in enumerate(unique_dates):
            win_start_pos = max(0, i - window + 1)
            # Slice the sorted array to get window scores
            lo = date_start[win_start_pos]
            hi = date_end[i]                  # exclusive end
            win_scores = scores_arr[lo:hi]
            win_sorted = np.sort(win_scores)
            n_win = len(win_sorted)

            # Rows belonging to date d in the *original* work frame
            mask = work['_dpos'] == i
            row_scores = work.loc[mask, score_col].values
            # searchsorted gives # of window scores strictly less than each score
            pcts = (np.searchsorted(win_sorted, row_scores, side='right')) / n_win
            result[mask.values] = pcts

        return pd.Series(result, index=work.index)

    def _filter_equities_only(self, df: pd.DataFrame, db_path: Path) -> pd.DataFrame:
        """
        Exclude ETF/INDEX rows from scoring. They have no fundamentals
        (pe_ratio, ps_ratio, eps_growth_yoy, etc.) and the model would
        impute medians across a structurally different population.

        Uses the `ticker_type` column from v_t3_training if present;
        otherwise queries company_profiles directly.
        """
        if 'ticker_type' in df.columns:
            mask = df['ticker_type'] == 'EQUITY'
        else:
            with db.connect(str(db_path), read_only=True) as con:
                non_eq = {r[0] for r in con.execute("""
                    SELECT ticker FROM company_profiles
                    WHERE ticker_type IN ('ETF', 'INDEX', 'UNKNOWN')
                """).fetchall()}
            mask = ~df['ticker'].isin(non_eq)

        n_excluded = (~mask).sum()
        if n_excluded > 0:
            logger.info(f"Excluded {n_excluded} non-equity rows (ETF/INDEX) from scoring")
        return df[mask].copy()

    def _calibrate_vectorized(self, raw_scores: np.ndarray) -> np.ndarray:
        """Vectorized calibration using pd.cut."""
        if self.calibration_bins is None:
            return raw_scores

        # Use pd.cut to bin scores and map to calibrated values
        binned = pd.cut(
            raw_scores,
            bins=self.calibration_bins,
            labels=self.calibration_values,
            include_lowest=True,
        )
        # pd.cut returns Categorical; convert to float array
        return pd.Series(binned).astype(float).values

    def score_from_duckdb(
        self,
        start_date: str,
        end_date: str,
        db_path: Optional[Path] = None,
    ) -> pd.DataFrame:
        """
        Score SEPA candidates directly from d2_training_cache in DuckDB.

        Returns DataFrame with columns: date, ticker, calibrated_score,
        normalized_score, daily_pct_rank, trailing_10d_pct.
        """
        db_path = db_path or DEFAULT_DB_PATH

        if self.m01_model is None:
            self.load_model()

        con = db.connect(str(db_path), read_only=True)
        try:
            df = con.execute("""
                SELECT * FROM d2_training_cache
                WHERE date >= ? AND date <= ?
                ORDER BY date, ticker
            """, [start_date, end_date]).fetchdf()
        finally:
            con.close()

        logger.info(f"Loaded {len(df)} rows from d2_training_cache ({start_date} to {end_date})")

        if df.empty:
            raise ValueError(f"No data in d2_training_cache for {start_date} to {end_date}")

        df = self._filter_equities_only(df, db_path)

        # Generate missing log_* features inline
        missing_features = [f for f in self._m01_features if f not in df.columns]
        log_missing = [f for f in missing_features if f.startswith('log_')]
        if log_missing:
            for log_feat in log_missing:
                base_feat = log_feat[4:]
                if base_feat in df.columns:
                    df[log_feat] = np.sign(df[base_feat]) * np.log1p(np.abs(df[base_feat]))
            missing_features = [f for f in self._m01_features if f not in df.columns]

        if missing_features:
            logger.warning(f"Missing features: {missing_features}")
            for f in missing_features:
                df[f] = np.nan

        X = df[self._m01_features].copy()

        # Handle categoricals (sector/industry are VARCHAR in DuckDB)
        # Ensure categorical features have exactly the same categories as the training set
        for col in ['industry', 'sector']:
            if col in X.columns:
                cats = None
                
                # First try to load from the model's categorical_mapping.json
                if hasattr(self, 'm01_path') and self.m01_path:
                    cat_map_path = self.m01_path.parent / 'categorical_mapping.json'
                    if cat_map_path.exists():
                        import json
                        with open(cat_map_path, 'r') as f:
                            cat_map = json.load(f)
                            if col in cat_map:
                                cats = cat_map[col]
                                
                if cats is None:
                    # Fallback: query from company_profiles
                    con_tmp = db.connect(str(db_path), read_only=True)
                    try:
                        cats = con_tmp.execute(f"SELECT DISTINCT {col} FROM company_profiles WHERE {col} IS NOT NULL ORDER BY {col}").df()[col].astype(str).tolist()
                    finally:
                        con_tmp.close()
                        
                X[col] = X[col].astype(str).replace({'nan': np.nan, 'None': np.nan})
                X[col] = pd.Categorical(X[col], categories=cats)

        for col in ['industry_id', 'sector_id']:
            if col in X.columns:
                X[col] = X[col].astype('category')

        # Fill NaNs with median (numeric only)
        numeric_cols = X.select_dtypes(include=[np.number]).columns
        X[numeric_cols] = X[numeric_cols].fillna(X[numeric_cols].median())

        # Predict — classifier uses expected MFE, regressor uses raw score
        prob_elite = None
        if self._is_classifier:
            import xgboost as xgb
            dtest = xgb.DMatrix(X, enable_categorical=True)
            proba = np.asarray(self.m01_model.get_booster().predict(dtest))
            if self._is_binary:
                p_pos = proba if proba.ndim == 1 else proba[:, -1]
                prob_elite = self._iso_calibrator.transform(p_pos) if self._iso_calibrator else p_pos
                calibrated_scores = (1.0 - prob_elite) * 3.0 + prob_elite * 70.0
            else:
                midpoints = np.array([1.0, 6.0, 20.0, 40.0])[:self._num_classes]
                calibrated_scores = (proba * midpoints).sum(axis=1)
                if proba.shape[1] >= 4:
                    prob_elite = proba[:, 3]
                elif proba.shape[1] == 2:
                    prob_elite = proba[:, 1]
                else:
                    prob_elite = proba[:, -1]
            logger.info(f"Expected MFE range: {calibrated_scores.min():.2f} to {calibrated_scores.max():.2f}")
        else:
            import xgboost as xgb
            dtest = xgb.DMatrix(X, enable_categorical=True)
            raw_scores = self.m01_model.get_booster().predict(dtest)
            calibrated_scores = self._calibrate_vectorized(raw_scores)

        result = df.copy()
        result['calibrated_score'] = calibrated_scores
        if prob_elite is not None:
            result['prob_elite'] = prob_elite
        result = result.dropna(subset=['calibrated_score'])

        # Daily percentile rank
        result['daily_pct_rank'] = result.groupby('date')['calibrated_score'].transform(
            lambda x: x.rank(pct=True)
        )

        # Normalized score (0-100)
        cal_min = result['calibrated_score'].min()
        cal_max = result['calibrated_score'].max()
        if cal_max > cal_min:
            result['normalized_score'] = (
                (result['calibrated_score'] - cal_min) / (cal_max - cal_min) * 100
            )
        else:
            result['normalized_score'] = 50.0

        result = result.sort_values(['date', 'daily_pct_rank'], ascending=[True, False])
        logger.info(f"Scored {len(result)} rows, {result['ticker'].nunique()} tickers, "
                    f"{result['date'].nunique()} dates")
        return result

    @staticmethod
    def create_view(db_path: Optional[Path] = None) -> None:
        """
        Create (or replace) the v_t3_training view in DuckDB.

        This view pre-joins t3_sepa_features with company_profiles,
        shares_history, and fundamental_features using ASOF JOINs —
        DuckDB's native "latest record as-of this date" join that is
        memory-efficient and avoids correlated subqueries.

        Call this once after the feature pipeline runs, or whenever
        the underlying tables are refreshed.
        """
        db_path = db_path or DEFAULT_DB_PATH
        con = db.connect(str(db_path), read_only=False)
        try:
            has_shares = con.execute("""
                SELECT COUNT(*) FROM information_schema.tables
                WHERE table_name = 'shares_history'
            """).fetchone()[0] > 0

            if has_shares:
                shares_select = "sh.shares_outstanding"
                shares_join = """
                ASOF LEFT JOIN shares_history sh
                    ON t3.ticker = sh.ticker AND t3.date >= sh.date"""
            else:
                shares_select = "cp.shares_outstanding"
                shares_join = ""

            con.execute(f"""
                CREATE OR REPLACE VIEW v_t3_training AS
                SELECT
                    t3.*,
                    cp.sector,
                    cp.industry,
                    COALESCE(cp.ticker_type, 'EQUITY')                       AS ticker_type,
                    {shares_select}                                          AS shares_outstanding,
                    ff.revenue, ff.net_income, ff.eps_diluted,
                    ff.total_assets, ff.total_equity,
                    ff.revenue_growth_yoy, ff.eps_growth_yoy,
                    ff.net_income_growth_yoy, ff.revenue_cagr_3y,
                    ff.eps_accel, ff.revenue_accel,
                    ff.eps_stability_score, ff.earnings_quality_score,
                    ff.debt_to_equity, ff.current_ratio, ff.quick_ratio,
                    ff.gross_margin, ff.operating_margin, ff.net_margin,
                    ff.gross_margin_trend, ff.roe, ff.roa, ff.fcf_margin,
                    ff.inventory_growth_yoy, ff.inventory_vs_sales_spread,
                    CAST(datediff('day', ff.filing_date, t3.date) AS INTEGER) AS days_since_report,
                    CASE WHEN ABS(ff.eps_diluted) > 0.01
                        THEN t3.close / ff.eps_diluted END               AS pe_ratio,
                    CASE WHEN ff.revenue > 0 AND {shares_select} > 0
                        THEN (t3.close * {shares_select}) / ff.revenue END  AS ps_ratio,
                    CASE WHEN ff.total_equity > 0 AND {shares_select} > 0
                        THEN (t3.close * {shares_select}) / ff.total_equity END AS pb_ratio,
                    CASE WHEN ff.eps_growth_yoy > 0 AND ABS(ff.eps_diluted) > 0.01
                        THEN (t3.close / ff.eps_diluted) / ff.eps_growth_yoy END AS peg_adjusted
                FROM t3_sepa_features t3
                LEFT JOIN company_profiles cp ON t3.ticker = cp.ticker
                {shares_join}
                ASOF LEFT JOIN fundamental_features ff
                    ON t3.ticker = ff.ticker AND t3.date >= ff.filing_date
                WHERE t3.feature_version = 'v3.1'
            """)
            logger.info("Created view v_t3_training")
        finally:
            con.close()

    def score_from_t3(
        self,
        start_date: str,
        end_date: str,
        db_path: Optional[Path] = None,
        ranking_lookback_days: int = 10,
    ) -> pd.DataFrame:
        """
        Score SEPA candidates daily from t3_sepa_features.

        Unlike score_from_duckdb() which only scores Day 0 breakout snapshots,
        this method scores every active SEPA candidate every day, enabling
        the strategy to catch setups whose conviction improves post-breakout.

        Joins company_profiles for sector/industry (T3 does not store them).

        Returns DataFrame with columns: date, ticker, calibrated_score,
        prob_elite, normalized_score, daily_pct_rank, trailing_pct.
        """
        db_path = db_path or DEFAULT_DB_PATH

        if self.m01_model is None:
            self.load_model()

        con = db.connect(str(db_path), read_only=True)
        try:
            # Check v_t3_training view exists — create it if not
            has_view = con.execute("""
                SELECT COUNT(*) FROM information_schema.views
                WHERE table_name = 'v_t3_training'
            """).fetchone()[0] > 0

            if not has_view:
                con.close()
                logger.info("v_t3_training not found — creating it now...")
                UniverseScorer.create_view(db_path)
                con = db.connect(str(db_path), read_only=True)

            df = con.execute("""
                SELECT * FROM v_t3_training
                WHERE date >= ? AND date <= ?
                ORDER BY date, ticker
            """, [start_date, end_date]).fetchdf()
        finally:
            con.close()

        logger.info(f"Loaded {len(df)} rows from t3_sepa_features ({start_date} to {end_date})")

        if df.empty:
            raise ValueError(f"No data in t3_sepa_features for {start_date} to {end_date}")

        df = self._filter_equities_only(df, db_path)

        # Derive *_delta features from existing *_pct_chg columns (pct_chg / 100 = delta ratio)
        for col in list(df.columns):
            if col.endswith('_pct_chg'):
                delta_col = col[:-len('_pct_chg')] + '_delta'
                if delta_col not in df.columns:
                    df[delta_col] = df[col] / 100.0

        # Cross-sectional rank features: DuckDB stores TitleCase, M01 expects lowercase
        case_map = {
            'RS_Sector_Rank': 'rs_sector_rank',
            'RS_Industry_Rank': 'rs_industry_rank',
            'RS_vs_Sector': 'rs_vs_sector',
            'RS_vs_Industry': 'rs_vs_industry',
            'Sector_Momentum': 'sector_momentum',
            'Industry_Momentum': 'industry_momentum',
            'RS_Universe_Rank': 'rs_universe_rank',
        }
        for src, dst in case_map.items():
            if src in df.columns and dst not in df.columns:
                df[dst] = df[src]

        # Generate missing log_* features inline
        missing_features = [f for f in self._m01_features if f not in df.columns]
        log_missing = [f for f in missing_features if f.startswith('log_')]
        if log_missing:
            for log_feat in log_missing:
                base_feat = log_feat[4:]
                if base_feat in df.columns:
                    df[log_feat] = np.sign(df[base_feat]) * np.log1p(np.abs(df[base_feat]))
            missing_features = [f for f in self._m01_features if f not in df.columns]

        if missing_features:
            logger.warning(f"Missing features: {missing_features}")
            for f in missing_features:
                df[f] = np.nan

        X = df[self._m01_features].copy()

        # Ensure categorical features have exactly the same categories as the training set
        for col in ['industry', 'sector']:
            if col in X.columns:
                cats = None
                
                # First try to load from the model's categorical_mapping.json
                if hasattr(self, 'm01_path') and self.m01_path:
                    cat_map_path = self.m01_path.parent / 'categorical_mapping.json'
                    if cat_map_path.exists():
                        import json
                        with open(cat_map_path, 'r') as f:
                            cat_map = json.load(f)
                            if col in cat_map:
                                cats = cat_map[col]
                                
                if cats is None:
                    # Fallback: query from company_profiles
                    con_tmp = db.connect(str(db_path), read_only=True)
                    try:
                        cats = con_tmp.execute(f"SELECT DISTINCT {col} FROM company_profiles WHERE {col} IS NOT NULL ORDER BY {col}").df()[col].astype(str).tolist()
                    finally:
                        con_tmp.close()
                        
                X[col] = X[col].astype(str).replace({'nan': np.nan, 'None': np.nan})
                X[col] = pd.Categorical(X[col], categories=cats)

        for col in ['industry_id', 'sector_id']:
            if col in X.columns:
                X[col] = X[col].astype('category')

        numeric_cols = X.select_dtypes(include=[np.number]).columns
        X[numeric_cols] = X[numeric_cols].fillna(X[numeric_cols].median())

        prob_elite = None
        if self._is_classifier:
            import xgboost as xgb
            dtest = xgb.DMatrix(X, enable_categorical=True)
            proba_raw = np.asarray(self.m01_model.get_booster().predict(dtest))
            if self._is_binary:
                # binary:logistic returns 1-D P(class=1). Midpoints reflect
                # average MFE in each bucket: ~3% for Not-Home-Run, ~70% for Home-Run.
                if proba_raw.ndim == 1:
                    p_pos = proba_raw
                else:
                    p_pos = proba_raw[:, -1]
                prob_elite = self._iso_calibrator.transform(p_pos) if self._iso_calibrator else p_pos
                # Expected-MFE score (used downstream for ranking / sizing).
                calibrated_scores = (1.0 - prob_elite) * 3.0 + prob_elite * 70.0
            else:
                midpoints = np.array([1.0, 6.0, 20.0, 40.0])[:self._num_classes]
                calibrated_scores = (proba_raw * midpoints).sum(axis=1)
                prob_elite = proba_raw[:, -1]
            logger.info(f"Expected MFE range: {calibrated_scores.min():.2f} to {calibrated_scores.max():.2f}")
        else:
            import xgboost as xgb
            dtest = xgb.DMatrix(X, enable_categorical=True)
            raw_scores = self.m01_model.get_booster().predict(dtest)
            calibrated_scores = self._calibrate_vectorized(raw_scores)

        result = df.copy()
        result['calibrated_score'] = calibrated_scores
        if prob_elite is not None:
            result['prob_elite'] = prob_elite
        result = result.dropna(subset=['calibrated_score'])

        result['daily_pct_rank'] = result.groupby('date')['calibrated_score'].transform(
            lambda x: x.rank(pct=True)
        )

        result = result.sort_values(['date', 'ticker'])
        result['trailing_pct'] = self._compute_trailing_percentile(
            result, window=ranking_lookback_days
        )

        cal_min = result['calibrated_score'].min()
        cal_max = result['calibrated_score'].max()
        if cal_max > cal_min:
            result['normalized_score'] = (
                (result['calibrated_score'] - cal_min) / (cal_max - cal_min) * 100
            )
        else:
            result['normalized_score'] = 50.0

        result = result.sort_values(['date', 'daily_pct_rank'], ascending=[True, False])
        logger.info(f"Scored {len(result)} rows from T3, {result['ticker'].nunique()} tickers, "
                    f"{result['date'].nunique()} dates (lookback={ranking_lookback_days}d)")
        return result

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    scorer = UniverseScorer(m01_path='models/m01_prototype/model.json')
    df = scorer.score_from_t3('2024-01-01', '2024-03-31')
    print(df.head(10))
