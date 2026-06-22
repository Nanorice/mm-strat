"""
M03 Market Regime Calculator
Factor-based risk scoring using Trend, Liquidity, and Risk Appetite pillars.
"""

import json
import logging
import numpy as np
import pandas as pd
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

import sys
sys.path.append(str(Path(__file__).parent.parent.parent))
import config
from src.macro_engine import MacroEngine
from src.data_engine import DataRepository, CacheMode

logging.basicConfig(level=getattr(logging, config.LOG_LEVEL))
logger = logging.getLogger(__name__)


class M03RegimeCalculator:
    """
    Market Regime Risk Score Calculator (0-100 scale).

    Three-pillar architecture:
    1. Trend (40%): SPY price vs SMA_200
    2. Liquidity (30%): Fed Net Liquidity 20-day slope
    3. Risk Appetite (30%): VIX level + HY credit spread

    Output:
    - score: 0-100 (higher = more bullish)
    - category: 'strong_bull', 'bull', 'neutral', 'bear', 'strong_bear'

    PUBLICATION LAG HANDLING:
    =========================
    FRED data is indexed by observation date but released with a lag:
    - WALCL/WTREGEN: Wednesday observation → Thursday 4:30 PM release (T+1)
    - RRPONTSYD: Same-day release after market close (T+0, but after close)
    - HY Spread: T+1 lag
    - VIX: Real-time (T+0)

    To avoid lookahead bias, we apply a T+1 shift when joining macro data to
    trading dates. This means "Wednesday's Fed data" is available for
    "Thursday's trading row" (after the 4:30 PM release).

    Holiday handling: ffill() naturally handles holidays. If Thursday is a
    holiday, the data carries forward to Friday's row (effective T+2 for
    that week), which is conservative and correct.
    """

    # Publication lag in trading days for each data source
    # Applied when joining macro data to trading dates to avoid lookahead bias
    PUBLICATION_LAGS = {
        'WALCL': 1,       # Wed observation → Thu 4:30 PM release
        'WTREGEN': 1,     # Wed observation → Thu 4:30 PM release
        'RRPONTSYD': 1,   # Same-day but after market close, so treat as T+1
        'BAMLH0A0HYM2': 1,  # T+1 lag
        'VIX': 0,         # Real-time intraday
    }
    DEFAULT_MACRO_LAG = 1  # Default lag for macro data (conservative)

    DEFAULT_CONFIG = {
        'model_name': 'M03',
        'model_type': 'factor_calculator',
        'version': '1.1.0',  # Bumped for lag handling change
        'pillars': {
            'trend': {
                'weight': 0.40,
                'sma_period': 200,
            },
            'liquidity': {
                'weight': 0.30,
                'slope_lookback': 20,
            },
            'risk_appetite': {
                'weight': 0.30,
                'vix_bull_threshold': 20,
                'vix_bear_threshold': 25,
                'vix_extreme_threshold': 40,
                'spread_bull_threshold': 4.0,
                'spread_bear_threshold': 6.0,
                'spread_extreme_threshold': 8.0,
            }
        },
        'thresholds': {
            'strong_bull': 80,
            'bull': 60,
            'neutral': 40,
            'bear': 20,
        },
        'gating_rules': {
            'long_allow_min': 30,
            'long_reduced_min': 50,
        }
    }

    def __init__(self, config_path: str = None):
        """
        Initialize M03 Regime Calculator.

        Args:
            config_path: Path to config JSON file (optional)
        """
        self.config_path = config_path or 'models/m03_config.json'
        self.config = self._load_config()
        self.macro_engine = MacroEngine()
        self.data_repo = DataRepository(enable_validation=False)

    def _load_config(self) -> Dict:
        """Load config from file or use defaults."""
        config_file = Path(self.config_path)
        if config_file.exists():
            try:
                with open(config_file) as f:
                    loaded = json.load(f)
                logger.debug(f"Loaded M03 config from {config_file}")
                return loaded
            except Exception as e:
                logger.warning(f"Failed to load config: {e}, using defaults")
        return self.DEFAULT_CONFIG.copy()

    def save_config(self, path: str = None) -> None:
        """Save current config to file."""
        save_path = Path(path or self.config_path)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        with open(save_path, 'w') as f:
            json.dump(self.config, f, indent=2)
        logger.info(f"Saved M03 config to {save_path}")

    def _load_spy_close(self) -> pd.DataFrame:
        """SPY daily close from DuckDB price_data — the single source of truth.

        Returns a DatetimeIndex frame with a 'Close' column. Replaces the parquet
        CACHE_ONLY read, which read data/price/SPY.parquet — a cache the daily
        pipeline does not maintain for benchmark tickers, and which is empty after
        the ITX port. price_data has SPY fresh; the 5-factor risk calc already
        reads it the same way.
        """
        from src import db
        conn = db.connect(self.data_repo.db_path, read_only=True)
        try:
            spy_df = conn.execute(
                'SELECT date, close AS "Close" FROM price_data '
                "WHERE ticker = 'SPY' ORDER BY date"
            ).fetchdf()
        finally:
            conn.close()
        if not spy_df.empty:
            spy_df['date'] = pd.to_datetime(spy_df['date'])
            spy_df = spy_df.set_index('date')
        return spy_df

    def _get_spy_data(self, lookback_days: int = 300) -> pd.DataFrame:
        """Get SPY price data from DuckDB price_data."""
        spy_df = self._load_spy_close()
        if spy_df is None or spy_df.empty:
            raise ValueError("SPY data not available in price_data")

        spy_df = spy_df.tail(lookback_days)
        return spy_df

    def _score_trend(self, as_of_date: str = None) -> Dict:
        """
        Calculate trend pillar score (0-100).

        Logic:
        - SPY above 200 SMA = bullish (score > 50)
        - SPY below 200 SMA = bearish (score < 50)
        - Score scaled using tanh for smooth transitions

        Returns:
            Dict with 'score', 'spy_close', 'sma_200', 'pct_above_sma'
        """
        sma_period = self.config['pillars']['trend']['sma_period']

        spy_df = self._get_spy_data(lookback_days=sma_period + 50)
        # Column name is 'Close' (capitalized from FMP)
        spy_df['sma_200'] = spy_df['Close'].rolling(sma_period).mean()

        # Filter to as_of_date if specified
        if as_of_date:
            as_of = pd.to_datetime(as_of_date)
            spy_df = spy_df[spy_df.index <= as_of]

        if spy_df.empty or spy_df['sma_200'].isna().all():
            logger.warning("Insufficient SPY data for trend calculation")
            return {'score': 50.0, 'spy_close': None, 'sma_200': None, 'pct_above_sma': 0}

        latest = spy_df.iloc[-1]
        spy_close = latest['Close']
        sma_200 = latest['sma_200']

        if pd.isna(sma_200):
            return {'score': 50.0, 'spy_close': spy_close, 'sma_200': None, 'pct_above_sma': 0}

        # Percentage above/below SMA
        pct_above = (spy_close - sma_200) / sma_200

        # Score: 50 + 50 * tanh(pct_above * 10)
        # Range: ~0 (10% below SMA) to ~100 (10% above SMA)
        score = 50 + 50 * np.tanh(pct_above * 10)
        score = np.clip(score, 0, 100)

        return {
            'score': round(score, 1),
            'spy_close': round(spy_close, 2),
            'sma_200': round(sma_200, 2),
            'pct_above_sma': round(pct_above * 100, 2)
        }

    def _score_liquidity(self, as_of_date: str = None) -> Dict:
        """
        Calculate liquidity pillar score (0-100).

        Logic:
        - Net Liquidity = Fed Assets - TGA - RRP
        - Rising liquidity (positive 20d slope) = bullish
        - Falling liquidity (negative 20d slope) = bearish

        Returns:
            Dict with 'score', 'net_liquidity', 'slope_20d', 'slope_pct'
        """
        lookback = self.config['pillars']['liquidity']['slope_lookback']

        net_liq_df = self.macro_engine.get_net_liquidity(as_of_date)

        if net_liq_df.empty or len(net_liq_df) < lookback:
            logger.warning("Insufficient liquidity data")
            return {'score': 50.0, 'net_liquidity': None, 'slope_20d': None, 'slope_pct': 0}

        # Get last N days
        recent = net_liq_df['net_liquidity'].tail(lookback)
        current_liq = recent.iloc[-1]

        # Calculate slope (linear regression)
        x = np.arange(len(recent))
        y = recent.values
        slope, _ = np.polyfit(x, y, 1)

        # Normalize slope as % of current liquidity per day
        slope_pct = (slope / current_liq) * 100 if current_liq != 0 else 0

        # Score: 50 + 50 * tanh(slope_pct * 50)
        # Typical daily change is ~0.1%, so scale by 50
        score = 50 + 50 * np.tanh(slope_pct * 50)
        score = np.clip(score, 0, 100)

        return {
            'score': round(score, 1),
            'net_liquidity': round(current_liq, 1),
            'slope_20d': round(slope, 2),
            'slope_pct': round(slope_pct, 4)
        }

    def _score_risk_appetite(self, as_of_date: str = None) -> Dict:
        """
        Calculate risk appetite pillar score (0-100).

        Logic:
        - VIX < 20 AND HY spread < 4% = bullish (high score)
        - VIX > 25 OR HY spread > 6% = bearish (low score)
        - Each component contributes 50 points max

        Returns:
            Dict with 'score', 'vix', 'hy_spread', 'vix_score', 'spread_score'
        """
        cfg = self.config['pillars']['risk_appetite']
        vix_bull = cfg['vix_bull_threshold']
        vix_bear = cfg['vix_bear_threshold']
        vix_extreme = cfg['vix_extreme_threshold']
        spread_bull = cfg['spread_bull_threshold']
        spread_bear = cfg['spread_bear_threshold']
        spread_extreme = cfg['spread_extreme_threshold']

        # Get VIX
        vix_df = self.macro_engine.get_series('VIX')
        if as_of_date:
            as_of = pd.to_datetime(as_of_date)
            vix_df = vix_df[vix_df.index <= as_of]

        vix = vix_df['VIX'].iloc[-1] if not vix_df.empty else None

        # Get HY spread
        hy_df = self.macro_engine.get_series('BAMLH0A0HYM2')
        if as_of_date:
            as_of = pd.to_datetime(as_of_date)
            hy_df = hy_df[hy_df.index <= as_of]

        hy_spread = hy_df['BAMLH0A0HYM2'].iloc[-1] if not hy_df.empty else None

        # Score VIX (0-50): Low VIX = high score
        if vix is not None:
            # Linear interpolation: VIX=10 → 50, VIX=40 → 0
            vix_score = 50 * (1 - np.clip((vix - 10) / (vix_extreme - 10), 0, 1))
        else:
            vix_score = 25  # Neutral if missing

        # Score HY Spread (0-50): Low spread = high score
        if hy_spread is not None:
            # Linear interpolation: spread=2 → 50, spread=8 → 0
            spread_score = 50 * (1 - np.clip((hy_spread - 2) / (spread_extreme - 2), 0, 1))
        else:
            spread_score = 25  # Neutral if missing

        total_score = np.clip(vix_score + spread_score, 0, 100)

        return {
            'score': round(total_score, 1),
            'vix': round(vix, 2) if vix is not None else None,
            'hy_spread': round(hy_spread, 2) if hy_spread is not None else None,
            'vix_score': round(vix_score, 1),
            'spread_score': round(spread_score, 1)
        }

    def get_regime_category(self, score: float) -> str:
        """
        Map numeric score to regime category.

        Args:
            score: 0-100 regime score

        Returns:
            One of: 'strong_bull', 'bull', 'neutral', 'bear', 'strong_bear'
        """
        thresholds = self.config['thresholds']

        if score >= thresholds['strong_bull']:
            return 'strong_bull'
        elif score >= thresholds['bull']:
            return 'bull'
        elif score >= thresholds['neutral']:
            return 'neutral'
        elif score >= thresholds['bear']:
            return 'bear'
        else:
            return 'strong_bear'

    def calculate(self, as_of_date: str = None) -> Dict:
        """
        Calculate composite regime score.

        Args:
            as_of_date: Calculate as of this date (default: latest available)

        Returns:
            Dict with:
            - date: str
            - score: float (0-100)
            - category: str
            - pillars: Dict with detailed breakdown
        """
        if as_of_date is None:
            as_of_date = datetime.now().strftime('%Y-%m-%d')

        logger.info(f"Calculating M03 regime score as of {as_of_date}")

        # Calculate each pillar
        trend = self._score_trend(as_of_date)
        liquidity = self._score_liquidity(as_of_date)
        risk_appetite = self._score_risk_appetite(as_of_date)

        # Get weights
        weights = {
            'trend': self.config['pillars']['trend']['weight'],
            'liquidity': self.config['pillars']['liquidity']['weight'],
            'risk_appetite': self.config['pillars']['risk_appetite']['weight'],
        }

        # Weighted average
        composite_score = (
            trend['score'] * weights['trend'] +
            liquidity['score'] * weights['liquidity'] +
            risk_appetite['score'] * weights['risk_appetite']
        )
        composite_score = round(np.clip(composite_score, 0, 100), 1)

        category = self.get_regime_category(composite_score)

        result = {
            'date': as_of_date,
            'score': composite_score,
            'category': category,
            'pillars': {
                'trend': {**trend, 'weight': weights['trend']},
                'liquidity': {**liquidity, 'weight': weights['liquidity']},
                'risk_appetite': {**risk_appetite, 'weight': weights['risk_appetite']},
            }
        }

        logger.info(f"M03 Regime: {category.upper()} (score={composite_score})")
        return result

    def should_gate_signal(self, score: float = None, as_of_date: str = None) -> Dict:
        """
        Check if signals should be gated based on regime.

        Args:
            score: Pre-calculated regime score (optional)
            as_of_date: Calculate score as of this date

        Returns:
            Dict with:
            - allow_longs: bool
            - reduced_sizing: bool
            - score: float
            - category: str
        """
        if score is None:
            result = self.calculate(as_of_date)
            score = result['score']
            category = result['category']
        else:
            category = self.get_regime_category(score)

        gating = self.config['gating_rules']
        allow_longs = score >= gating['long_allow_min']
        reduced_sizing = score < gating['long_reduced_min']

        return {
            'allow_longs': allow_longs,
            'reduced_sizing': reduced_sizing,
            'score': score,
            'category': category
        }

    def calculate_history_vectorized(
        self,
        start_date: str,
        end_date: str,
        freq: str = 'D',
    ) -> pd.DataFrame:
        """
        Calculate regime scores over a date range using vectorized operations.

        This is much faster than looping through dates individually.
        Loads all data once and computes scores for entire time series.

        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            freq: Output frequency - 'D' (daily), 'W-FRI' (weekly), 'M' (monthly)

        Returns:
            DataFrame with all pillar scores and raw input values

        Note:
            Macro data is shifted by T+1 to account for publication lag.
            "Wednesday's FRED data" appears on "Thursday's trading row".
        """
        logger.info(f"Calculating M03 regime history (vectorized, T+1 lag) from {start_date} to {end_date}")

        sma_period = self.config['pillars']['trend']['sma_period']
        slope_lookback = self.config['pillars']['liquidity']['slope_lookback']
        weights = {
            'trend': self.config['pillars']['trend']['weight'],
            'liquidity': self.config['pillars']['liquidity']['weight'],
            'risk_appetite': self.config['pillars']['risk_appetite']['weight'],
        }
        risk_cfg = self.config['pillars']['risk_appetite']

        # Load all data ONCE (SPY from DuckDB price_data — see _load_spy_close)
        spy_df = self._load_spy_close()
        macro_df = self.macro_engine.get_all_macro_data()

        if spy_df is None or spy_df.empty:
            raise ValueError("SPY data not available")
        if macro_df.empty:
            raise ValueError("Macro data not available")

        # Apply T+1 publication lag to macro data
        # This shifts the index forward by 1 day: "Wed observation" → "Thu row"
        # ffill() handles holidays gracefully (data carries to next trading day)
        macro_df = macro_df.shift(freq='1D')

        # Build unified daily index
        all_dates = pd.date_range(start=start_date, end=end_date, freq='D')
        df = pd.DataFrame(index=all_dates)
        df.index.name = 'date'

        # === TREND PILLAR (SPY vs SMA-200) ===
        spy_daily = spy_df[['Close']].reindex(all_dates).ffill()
        spy_daily['sma_200'] = spy_daily['Close'].rolling(sma_period, min_periods=sma_period).mean()
        spy_daily['pct_above_sma'] = (spy_daily['Close'] - spy_daily['sma_200']) / spy_daily['sma_200']
        spy_daily['trend_score'] = 50 + 50 * np.tanh(spy_daily['pct_above_sma'] * 10)
        spy_daily['trend_score'] = spy_daily['trend_score'].clip(0, 100)

        df['spy_close'] = spy_daily['Close']
        df['sma_200'] = spy_daily['sma_200']
        df['pct_above_sma'] = spy_daily['pct_above_sma'] * 100
        df['trend_score'] = spy_daily['trend_score']

        # === LIQUIDITY PILLAR (Net Liquidity 20-day slope) ===
        macro_daily = macro_df.reindex(all_dates).ffill()
        df['fed_assets'] = macro_daily['fed_assets']
        df['tga'] = macro_daily['tga']
        df['rrp'] = macro_daily['rrp']
        df['net_liquidity'] = macro_daily['net_liquidity']

        # Rolling slope calculation (vectorized)
        def rolling_slope(series, window):
            """Calculate rolling linear regression slope."""
            x = np.arange(window)
            x_mean = x.mean()
            x_var = ((x - x_mean) ** 2).sum()

            def slope_func(y):
                if len(y) < window or np.isnan(y).any():
                    return np.nan
                y_mean = y.mean()
                return ((x - x_mean) * (y - y_mean)).sum() / x_var

            return series.rolling(window).apply(slope_func, raw=True)

        df['liq_slope_20d'] = rolling_slope(df['net_liquidity'], slope_lookback)
        df['liq_slope_pct'] = (df['liq_slope_20d'] / df['net_liquidity']) * 100
        df['liquidity_score'] = 50 + 50 * np.tanh(df['liq_slope_pct'] * 50)
        df['liquidity_score'] = df['liquidity_score'].clip(0, 100)

        # === RISK APPETITE PILLAR (VIX + HY Spread) ===
        df['vix'] = macro_daily['vix'] if 'vix' in macro_daily.columns else np.nan
        df['hy_spread'] = macro_daily['hy_spread'] if 'hy_spread' in macro_daily.columns else np.nan

        # VIX score (0-50): Low VIX = high score
        vix_extreme = risk_cfg['vix_extreme_threshold']
        df['vix_score'] = 50 * (1 - ((df['vix'] - 10) / (vix_extreme - 10)).clip(0, 1))
        df['vix_score'] = df['vix_score'].fillna(25)

        # HY Spread score (0-50): Low spread = high score
        spread_extreme = risk_cfg['spread_extreme_threshold']
        df['spread_score'] = 50 * (1 - ((df['hy_spread'] - 2) / (spread_extreme - 2)).clip(0, 1))
        df['spread_score'] = df['spread_score'].fillna(25)

        df['risk_appetite_score'] = (df['vix_score'] + df['spread_score']).clip(0, 100)

        # === COMPOSITE SCORE ===
        df['score'] = (
            df['trend_score'] * weights['trend'] +
            df['liquidity_score'] * weights['liquidity'] +
            df['risk_appetite_score'] * weights['risk_appetite']
        ).clip(0, 100).round(1)

        # === CATEGORY ===
        thresholds = self.config['thresholds']
        df['category'] = pd.cut(
            df['score'],
            bins=[-np.inf, thresholds['bear'], thresholds['neutral'],
                  thresholds['bull'], thresholds['strong_bull'], np.inf],
            labels=['strong_bear', 'bear', 'neutral', 'bull', 'strong_bull']
        )

        # Drop rows with insufficient data (NaN scores)
        df = df.dropna(subset=['score'])

        # Resample to requested frequency
        if freq != 'D':
            df = df.resample(freq).last().dropna(subset=['score'])

        logger.info(f"Calculated {len(df)} regime observations")
        return df

    def calculate_history(
        self,
        start_date: str,
        end_date: str,
        freq: str = 'W-FRI',
    ) -> pd.DataFrame:
        """
        Calculate regime scores over a date range.

        Uses vectorized implementation for efficiency.

        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            freq: Pandas frequency string (default: weekly on Friday)
                  Options: 'D' (daily), 'W-FRI' (weekly), 'M' (monthly)

        Returns:
            DataFrame with columns: date, score, category, trend_score,
            liquidity_score, risk_appetite_score, plus raw input values

        Note:
            Macro data is shifted by T+1 to account for FRED publication lag.
        """
        return self.calculate_history_vectorized(start_date, end_date, freq)

    def save_history(
        self,
        df: pd.DataFrame,
        path: str = 'models/m03_history.parquet',
        format: str = None
    ) -> str:
        """
        Save regime history to file.

        Args:
            df: DataFrame with regime history
            path: Output file path
            format: 'parquet', 'csv', or None (auto-detect from extension)

        Returns:
            Path to saved file
        """
        save_path = Path(path)
        save_path.parent.mkdir(parents=True, exist_ok=True)

        # Auto-detect format from extension
        if format is None:
            format = 'parquet' if save_path.suffix == '.parquet' else 'csv'

        if format == 'parquet':
            # Convert category to string for parquet compatibility
            df_out = df.copy()
            if 'category' in df_out.columns:
                df_out['category'] = df_out['category'].astype(str)
            df_out.to_parquet(save_path)
        else:
            df.to_csv(save_path)

        logger.info(f"Saved M03 history ({format}) to {save_path}")
        return str(save_path)

    @staticmethod
    def load(config_path: str) -> 'M03RegimeCalculator':
        """Load calculator from config file."""
        return M03RegimeCalculator(config_path=config_path)

    # =========================================================================
    # M01 FEATURE ENGINEERING
    # =========================================================================

    # Expected feature columns for M01 integration
    M01_FEATURE_COLUMNS = [
        'm03_score',       # Normalized score (0.0-1.0)
        'm03_regime_cat',  # Ordinal category (0-4)
        'm03_delta_5d',    # 5-day velocity (-1.0 to 1.0)
        'm03_delta_20d',   # 20-day velocity (-1.0 to 1.0)
        'm03_regime_vol',  # Regime volatility (0.0-1.0, clipped)
        'm03_pillar_trend',  # Trend pillar (0.0-1.0)
        'm03_pillar_liq',    # Liquidity pillar (0.0-1.0)
        'm03_pillar_risk',   # Risk pillar (0.0-1.0)
    ]

    # Category to ordinal mapping
    CATEGORY_ORDINAL = {
        'strong_bear': 0,
        'bear': 1,
        'neutral': 2,
        'bull': 3,
        'strong_bull': 4,
    }

    def generate_m01_features(
        self,
        start_date: str,
        end_date: str,
        freq: str = 'D',
    ) -> pd.DataFrame:
        """
        Generate normalized M03 features for M01 training.

        Returns DataFrame with 8 columns, all normalized:
        - m03_score: Raw score / 100 (0.0-1.0)
        - m03_regime_cat: Ordinal 0-4 (strong_bear to strong_bull)
        - m03_delta_5d: 5-day velocity (score diff / 100, range -1 to 1)
        - m03_delta_20d: 20-day velocity (score diff / 100, range -1 to 1)
        - m03_regime_vol: 10-day rolling std / 100 (clipped to 1.0 max)
        - m03_pillar_trend: Trend pillar / 100 (0.0-1.0)
        - m03_pillar_liq: Liquidity pillar / 100 (0.0-1.0)
        - m03_pillar_risk: Risk appetite pillar / 100 (0.0-1.0)

        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            freq: Output frequency ('D', 'W-FRI', 'M')

        Returns:
            DataFrame indexed by date with M01 feature columns
        """
        logger.info(f"Generating M01 features from {start_date} to {end_date}")

        # Get raw history (includes T+1 lag handling)
        raw_df = self.calculate_history_vectorized(start_date, end_date, freq)

        # Create output DataFrame
        features = pd.DataFrame(index=raw_df.index)

        # === 1. Normalized Score (0.0-1.0) ===
        features['m03_score'] = raw_df['score'] / 100.0

        # === 2. Ordinal Category (0-4) ===
        features['m03_regime_cat'] = raw_df['category'].astype(str).map(self.CATEGORY_ORDINAL)

        # === 3. Velocity Features (absolute delta / 100) ===
        # Using absolute delta, not percentage change, to avoid explosion at low scores
        features['m03_delta_5d'] = (raw_df['score'].diff(5) / 100.0).fillna(0)
        features['m03_delta_20d'] = (raw_df['score'].diff(20) / 100.0).fillna(0)

        # === 4. Regime Volatility (10-day rolling std, clipped) ===
        # Measures "choppiness" - high vol = uncertain regime
        regime_std = raw_df['score'].rolling(10, min_periods=1).std()
        features['m03_regime_vol'] = (regime_std / 100.0).clip(upper=1.0).fillna(0)

        # === 5. Pillar Features (normalized 0.0-1.0) ===
        features['m03_pillar_trend'] = raw_df['trend_score'] / 100.0
        features['m03_pillar_liq'] = raw_df['liquidity_score'] / 100.0
        features['m03_pillar_risk'] = raw_df['risk_appetite_score'] / 100.0

        logger.info(f"Generated {len(features)} rows with {len(self.M01_FEATURE_COLUMNS)} M01 features")
        return features


def verify_m03_features(
    df: pd.DataFrame,
    raise_on_error: bool = True,
    feature_columns: list = None,
) -> dict:
    """
    Verify M03 features integrity before M01 training.

    Performs 3 critical checks:
    1. Existence: All expected feature columns are present
    2. Nulls: Reports NaN count per column
    3. Range: Values are within expected normalized bounds

    Args:
        df: DataFrame with M03 features
        raise_on_error: If True, raises ValueError on critical errors
        feature_columns: List of expected columns (default: M01_FEATURE_COLUMNS)

    Returns:
        Dict with check results:
        - passed: bool (all checks passed)
        - existence: dict with missing columns
        - nulls: dict with NaN counts per column
        - range: dict with out-of-range info
    """
    if feature_columns is None:
        feature_columns = M03RegimeCalculator.M01_FEATURE_COLUMNS

    results = {
        'passed': True,
        'existence': {'missing': [], 'passed': True},
        'nulls': {'counts': {}, 'total': 0, 'passed': True},
        'range': {'violations': {}, 'passed': True},
    }

    # === CHECK 1: Existence ===
    missing = [col for col in feature_columns if col not in df.columns]
    if missing:
        results['existence']['missing'] = missing
        results['existence']['passed'] = False
        results['passed'] = False
        logger.error(f"M03 Feature Existence Check FAILED: Missing columns: {missing}")
        if raise_on_error:
            raise ValueError(f"Missing M03 feature columns: {missing}")

    # Get columns that exist for further checks
    existing_cols = [col for col in feature_columns if col in df.columns]

    # === CHECK 2: Nulls ===
    null_counts = {}
    for col in existing_cols:
        null_count = df[col].isna().sum()
        if null_count > 0:
            null_counts[col] = int(null_count)

    if null_counts:
        total_nulls = sum(null_counts.values())
        results['nulls']['counts'] = null_counts
        results['nulls']['total'] = total_nulls
        results['nulls']['passed'] = False
        # Nulls are warnings, not critical errors (may be expected for early dates)
        logger.warning(f"M03 Feature Null Check: {total_nulls} total NaNs across columns: {null_counts}")

    # === CHECK 3: Range ===
    range_specs = {
        'm03_score': (0.0, 1.0),
        'm03_regime_cat': (0, 4),
        'm03_delta_5d': (-1.0, 1.0),
        'm03_delta_20d': (-1.0, 1.0),
        'm03_regime_vol': (0.0, 1.0),
        'm03_pillar_trend': (0.0, 1.0),
        'm03_pillar_liq': (0.0, 1.0),
        'm03_pillar_risk': (0.0, 1.0),
    }

    violations = {}
    for col in existing_cols:
        if col not in range_specs:
            continue

        min_val, max_val = range_specs[col]
        col_data = df[col].dropna()

        if len(col_data) == 0:
            continue

        actual_min = col_data.min()
        actual_max = col_data.max()

        if actual_min < min_val or actual_max > max_val:
            violations[col] = {
                'expected': (min_val, max_val),
                'actual': (float(actual_min), float(actual_max)),
            }

    if violations:
        results['range']['violations'] = violations
        results['range']['passed'] = False
        results['passed'] = False
        logger.error(f"M03 Feature Range Check FAILED: {violations}")
        if raise_on_error:
            raise ValueError(f"M03 features out of expected range: {violations}")

    if results['passed']:
        logger.info("M03 Feature Verification PASSED: All checks OK")

    return results
