"""
Production Scorer - Real-time M01+M02 Scoring Pipeline
=======================================================

Provides real-time scoring for trade candidates using the M01+M02 ensemble.

Usage:
    from src.pipeline import ProductionScorer

    scorer = ProductionScorer()
    scorer.load_models()

    # Score new candidates
    scores = scorer.score(df_candidates)

    # Get position sizes
    positions = scorer.get_position_sizes(scores, portfolio_value=100000)
"""

import logging
import json
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import numpy as np

logger = logging.getLogger("ProductionScorer")


class ProductionScorer:
    """
    Real-time scoring pipeline for M01+M02 ensemble.

    Combines:
    - M01: Expected return regression
    - Volatility adjustment: Reduce ATR correlation
    - M02: Triple barrier probability filtering
    - Position sizing: Score-based allocation
    """

    def __init__(
        self,
        m01_path: str = 'models/m01.json',
        m02_path: str = 'models/m02.json',
        calibration_path: str = 'models/m01_calibration.json',
        config_path: str = 'models/production_scoring_config.json'
    ):
        self.m01_path = Path(m01_path)
        self.m02_path = Path(m02_path)
        self.calibration_path = Path(calibration_path)
        self.config_path = Path(config_path)

        self.m01_model = None
        self.m02_model = None
        self.calibration_table: Optional[List[Dict]] = None
        self.config = None

        self._m01_features: List[str] = []
        self._m02_features: List[str] = []

    def load_models(self):
        """Load all models from disk."""
        import xgboost as xgb
        from src.feature_config import get_model_features

        # Load M01
        if self.m01_path.exists():
            self.m01_model = xgb.XGBRegressor()
            self.m01_model.load_model(str(self.m01_path))
            logger.info(f"Loaded M01 from {self.m01_path}")
        else:
            raise FileNotFoundError(f"M01 model not found: {self.m01_path}")

        # Load M02 (optional)
        if self.m02_path.exists():
            self.m02_model = xgb.XGBClassifier()
            self.m02_model.load_model(str(self.m02_path))
            logger.info(f"Loaded M02 from {self.m02_path}")
        else:
            logger.warning(f"M02 model not found: {self.m02_path}")

        # Load calibration table (optional)
        if self.calibration_path.exists():
            with open(self.calibration_path) as f:
                cal_data = json.load(f)
            self.calibration_table = cal_data.get('deciles', [])
            logger.info(f"Loaded calibration table from {self.calibration_path}")

        # Load config (optional)
        if self.config_path.exists():
            with open(self.config_path) as f:
                self.config = json.load(f)
            logger.info(f"Loaded config from {self.config_path}")
        else:
            self.config = self._default_config()

        # Load feature lists
        self._m01_features = get_model_features('M01')
        self._m02_features = get_model_features('M02')

    def _default_config(self) -> Dict:
        """Default scoring configuration."""
        return {
            'sizing_rules': {
                'high_conviction': {'score_threshold': 0.85, 'position_weight': 1.5},
                'standard': {'score_threshold': 0.70, 'position_weight': 1.0},
                'reduced': {'score_threshold': 0.50, 'position_weight': 0.5},
                'skip': {'score_threshold': 0.0, 'position_weight': 0.0}
            },
            'portfolio_rules': {
                'max_positions': 10,
                'max_single_position': 0.15,
                'max_sector_exposure': 0.30,
                'volatility_adjustment': True
            }
        }

    def _calibrate_score(self, raw_score: float) -> float:
        """Map raw M01 prediction to calibrated value using decile lookup."""
        if not self.calibration_table:
            return raw_score

        # Find which decile this score falls into
        for decile in self.calibration_table:
            if decile['pred_min'] <= raw_score <= decile['pred_max']:
                return decile['calibrated_mean']

        # Handle edge cases: below min or above max
        if raw_score < self.calibration_table[0]['pred_min']:
            return self.calibration_table[0]['calibrated_mean']
        return self.calibration_table[-1]['calibrated_mean']

    def score(
        self,
        candidates: pd.DataFrame,
        use_volatility_adjustment: bool = True,
        use_m02: bool = True,
        atr_column: str = 'nATR',
        penalty_weight: float = 0.5
    ) -> pd.DataFrame:
        """
        Score trade candidates with full M01+M02 pipeline.

        Args:
            candidates: DataFrame with features
            use_volatility_adjustment: Apply vol adjustment
            use_m02: Include M02 probability filtering
            atr_column: ATR column name
            penalty_weight: Vol adjustment weight

        Returns:
            DataFrame with scores: m01_score, m02_proba, adjusted_score, final_score
        """
        if self.m01_model is None:
            raise RuntimeError("Models not loaded. Call load_models() first.")

        df = candidates.copy()

        # Step 1: M01 predictions
        m01_cols = [c for c in self._m01_features if c in df.columns]
        if len(m01_cols) == 0:
            raise ValueError("No M01 features found in candidates")

        df['m01_score'] = self.m01_model.predict(df[m01_cols])

        # Step 2: Calibration (decile-based lookup)
        if self.calibration_table:
            df['m01_calibrated'] = df['m01_score'].apply(self._calibrate_score)
        else:
            df['m01_calibrated'] = df['m01_score']

        # Step 3: Volatility adjustment
        if use_volatility_adjustment and atr_column in df.columns:
            df['pred_rank'] = df['m01_calibrated'].rank(pct=True)
            df['atr_rank'] = df[atr_column].rank(pct=True)
            df['adjusted_score'] = df['pred_rank'] * (1 - penalty_weight * df['atr_rank'])
        else:
            df['adjusted_score'] = df['m01_calibrated'].rank(pct=True)

        # Step 4: M02 Loser Detector (INVERTED scoring)
        # M02 now predicts P(loser) - probability of hitting stop-loss
        # Formula: Final_Score = M01_Adj × (1 - P(loser))
        if use_m02 and self.m02_model is not None:
            m02_cols = [c for c in self._m02_features if c in df.columns]
            if len(m02_cols) > 0:
                # M02 outputs P(loser) = probability of hitting SL
                df['m02_loser_proba'] = self.m02_model.predict_proba(df[m02_cols])[:, 1]
                # PENALIZE high loser probability
                df['m02_survival'] = 1 - df['m02_loser_proba']
                df['final_score'] = df['adjusted_score'] * df['m02_survival']
            else:
                logger.warning("No M02 features found, skipping M02 integration")
                df['m02_loser_proba'] = 0.0
                df['m02_survival'] = 1.0
                df['final_score'] = df['adjusted_score']
        else:
            df['m02_loser_proba'] = 0.0
            df['m02_survival'] = 1.0
            df['final_score'] = df['adjusted_score']

        # Normalize final score to 0-1 range
        df['final_score_pct'] = df['final_score'].rank(pct=True)

        return df

    def get_position_sizes(
        self,
        scores: pd.DataFrame,
        portfolio_value: float,
        max_positions: int = None,
        score_threshold: float = None,
        score_column: str = 'final_score_pct',
        sizing_method: str = 'tiered'
    ) -> pd.DataFrame:
        """
        Calculate position sizes based on combined scores.

        Args:
            scores: DataFrame from score() with final_score_pct
            portfolio_value: Total portfolio value
            max_positions: Maximum positions (default from config)
            score_threshold: Minimum score to consider (default from config)
            score_column: Column to use for ranking
            sizing_method: 'equal', 'tiered', 'score_weighted', or 'risk_parity'

        Returns:
            DataFrame with position sizes
        """
        df = scores.copy()

        # Use config defaults if not specified
        if max_positions is None:
            max_positions = self.config['portfolio_rules']['max_positions']
        if score_threshold is None:
            score_threshold = self.config['sizing_rules']['reduced']['score_threshold']

        # Filter by threshold
        df = df[df[score_column] >= score_threshold].copy()

        if len(df) == 0:
            logger.warning(f"No candidates above threshold {score_threshold}")
            return pd.DataFrame()

        # Sort by score and take top N
        df = df.sort_values(score_column, ascending=False).head(max_positions)
        n_positions = len(df)

        if sizing_method == 'equal':
            df['position_weight'] = 1.0 / n_positions

        elif sizing_method == 'tiered':
            # Tiered sizing based on score thresholds
            def get_tier_weight(score):
                rules = self.config['sizing_rules']
                if score >= rules['high_conviction']['score_threshold']:
                    return rules['high_conviction']['position_weight']
                elif score >= rules['standard']['score_threshold']:
                    return rules['standard']['position_weight']
                elif score >= rules['reduced']['score_threshold']:
                    return rules['reduced']['position_weight']
                return 0

            df['raw_weight'] = df[score_column].apply(get_tier_weight)
            total_weight = df['raw_weight'].sum()
            df['position_weight'] = df['raw_weight'] / total_weight if total_weight > 0 else 0

        elif sizing_method == 'score_weighted':
            total_score = df[score_column].sum()
            df['position_weight'] = df[score_column] / total_score

        elif sizing_method == 'risk_parity':
            if 'nATR' in df.columns:
                inv_vol = 1 / df['nATR'].clip(lower=0.01)
                df['position_weight'] = inv_vol / inv_vol.sum()
            else:
                df['position_weight'] = 1.0 / n_positions
        else:
            df['position_weight'] = 1.0 / n_positions

        # Apply max single position constraint
        max_weight = self.config['portfolio_rules']['max_single_position']
        df['position_weight'] = df['position_weight'].clip(upper=max_weight)

        # Renormalize after clipping
        df['position_weight'] = df['position_weight'] / df['position_weight'].sum()

        # Calculate dollar amounts
        df['position_value'] = df['position_weight'] * portfolio_value

        # Add position info
        df['rank'] = range(1, len(df) + 1)

        # Select output columns
        output_cols = ['ticker', 'rank', score_column, 'm02_loser_proba', 'm02_survival', 'position_weight', 'position_value']
        available_cols = [c for c in output_cols if c in df.columns]

        return df[available_cols].reset_index(drop=True)

    def score_and_size(
        self,
        candidates: pd.DataFrame,
        portfolio_value: float,
        use_volatility_adjustment: bool = True,
        use_m02: bool = True,
        sizing_method: str = 'tiered'
    ) -> pd.DataFrame:
        """
        Convenience method: score candidates and get position sizes in one call.

        Args:
            candidates: DataFrame with features
            portfolio_value: Total portfolio value
            use_volatility_adjustment: Apply vol adjustment
            use_m02: Include M02 filtering
            sizing_method: Position sizing method

        Returns:
            DataFrame with positions ready for execution
        """
        scores = self.score(
            candidates,
            use_volatility_adjustment=use_volatility_adjustment,
            use_m02=use_m02
        )

        positions = self.get_position_sizes(
            scores,
            portfolio_value=portfolio_value,
            sizing_method=sizing_method
        )

        return positions

    def generate_trade_report(
        self,
        positions: pd.DataFrame,
        output_path: Optional[str] = None
    ) -> str:
        """
        Generate markdown trade report.

        Args:
            positions: DataFrame from get_position_sizes()
            output_path: Optional path to save report

        Returns:
            Markdown report string
        """
        from datetime import datetime

        lines = []
        lines.append("# Trade Recommendations")
        lines.append(f"\n**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"\n**Positions:** {len(positions)}")

        total_value = positions['position_value'].sum()
        lines.append(f"**Total Allocation:** ${total_value:,.0f}")
        lines.append("\n---\n")

        lines.append("## Recommended Trades\n")
        lines.append("| Rank | Ticker | Score | M02 Prob | Weight | Value |")
        lines.append("|------|--------|-------|----------|--------|-------|")

        for _, row in positions.iterrows():
            lines.append(
                f"| {row['rank']} | {row['ticker']} | "
                f"{row.get('final_score_pct', 0):.2f} | "
                f"{row['m02_proba']:.2f} | "
                f"{row['position_weight']:.1%} | "
                f"${row['position_value']:,.0f} |"
            )

        lines.append("\n---\n")
        lines.append("*Generated by ProductionScorer*")

        report = '\n'.join(lines)

        if output_path:
            with open(output_path, 'w') as f:
                f.write(report)
            logger.info(f"Saved trade report to {output_path}")

        return report
