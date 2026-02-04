"""
M03 Grid Search - Archetype-Based Parameter Optimization
=========================================================

Tests 6 weight archetypes × 2 VIX curves = 12 configurations.

Strategy: "Fit, Then Cut"
- Phase 1: Find weights that maximize separation (AUC, Cohen's D)
- Phase 2: Auto-calculate thresholds from best configuration

Usage:
    python model_runner.py m03grid
    
    # Or programmatically:
    from src.evaluation.m03_grid_search import M03GridSearch
    searcher = M03GridSearch()
    results = searcher.run_grid_search()
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import pandas as pd

from src.evaluation.m03_evaluator import M03Evaluator

logger = logging.getLogger("M03GridSearch")


# ============================================
# ARCHETYPE DEFINITIONS
# ============================================

ARCHETYPES = {
    'baseline': {
        'description': 'Control Group (Current Config)',
        'hypothesis': 'Fails GFC lag. Baseline for comparison.',
        'weights': {'trend': 0.4, 'liquidity': 0.3, 'risk_appetite': 0.3},
        'slope_lookback': 20,
    },
    'paranoid': {
        'description': 'Risk Dominant',
        'hypothesis': 'Fixes Crash Lag via VIX/Spread dominance.',
        'weights': {'trend': 0.2, 'liquidity': 0.3, 'risk_appetite': 0.5},
        'slope_lookback': 20,
    },
    'fed_focus': {
        'description': 'Liquidity Dominant',
        'hypothesis': 'Fixes 2022 Bear via Fed liquidity dominance.',
        'weights': {'trend': 0.2, 'liquidity': 0.6, 'risk_appetite': 0.2},
        'slope_lookback': 20,
    },
    'aggressive': {
        'description': 'Balanced but Fast',
        'hypothesis': 'Low trend weight for speed, balanced risk/liq.',
        'weights': {'trend': 0.2, 'liquidity': 0.4, 'risk_appetite': 0.4},
        'slope_lookback': 20,
    },
    'trend_heavy': {
        'description': 'Trend Dominant',
        'hypothesis': 'Fixes Bull AUC (0.663) via trend dominance.',
        'weights': {'trend': 0.5, 'liquidity': 0.2, 'risk_appetite': 0.3},
        'slope_lookback': 20,
    },
    'fast_liq': {
        'description': 'Fast Liquidity Signal',
        'hypothesis': 'Faster Fed reaction with 10d lookback.',
        'weights': {'trend': 0.3, 'liquidity': 0.4, 'risk_appetite': 0.3},
        'slope_lookback': 10,
    },
}

VIX_CURVES = {
    'standard': {
        'description': 'Normal VIX sensitivity',
        'vix_bull_threshold': 20,
        'vix_bear_threshold': 25,
        'vix_extreme_threshold': 40,
    },
    'tight': {
        'description': 'Nervous VIX sensitivity (steeper curve)',
        'vix_bull_threshold': 15,
        'vix_bear_threshold': 20,
        'vix_extreme_threshold': 30,
    },
}


class M03GridSearch:
    """
    Grid search runner for M03 regime calculator optimization.
    
    Tests multiple weight archetypes × VIX curve combinations
    to find the configuration with best discrimination (AUC, Cohen's D).
    """
    
    def __init__(self, output_dir: Path = None):
        """
        Initialize grid search.
        
        Args:
            output_dir: Directory for config files and reports
        """
        self.output_dir = output_dir or Path('models/m03_configs')
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.results: List[Dict] = []
        
    def generate_configs(self) -> Dict[str, Path]:
        """
        Generate JSON config files for all grid combinations.
        
        Returns:
            Dict mapping config_name -> config_path
        """
        configs = {}
        
        for arch_name, arch in ARCHETYPES.items():
            for vix_name, vix in VIX_CURVES.items():
                config_name = f"{arch_name}_{vix_name}"
                
                config = {
                    'model_name': 'M03',
                    'model_type': 'factor_calculator',
                    'version': '1.1.0',
                    'archetype': arch_name,
                    'vix_curve': vix_name,
                    'description': f"{arch['description']} + {vix['description']}",
                    'hypothesis': arch['hypothesis'],
                    'pillars': {
                        'trend': {
                            'weight': arch['weights']['trend'],
                            'sma_period': 200,
                        },
                        'liquidity': {
                            'weight': arch['weights']['liquidity'],
                            'slope_lookback': arch['slope_lookback'],
                        },
                        'risk_appetite': {
                            'weight': arch['weights']['risk_appetite'],
                            'vix_bull_threshold': vix['vix_bull_threshold'],
                            'vix_bear_threshold': vix['vix_bear_threshold'],
                            'vix_extreme_threshold': vix['vix_extreme_threshold'],
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
                
                config_path = self.output_dir / f"{config_name}.json"
                with open(config_path, 'w') as f:
                    json.dump(config, f, indent=2)
                
                configs[config_name] = config_path
                logger.debug(f"Generated config: {config_name}")
        
        logger.info(f"Generated {len(configs)} config files in {self.output_dir}")
        return configs
    
    def run_grid_search(
        self,
        start_date: str = '2007-01-01',
        end_date: str = '2024-12-31',
    ) -> pd.DataFrame:
        """
        Run evaluation on all grid configurations.
        
        Args:
            start_date: Evaluation start date
            end_date: Evaluation end date
            
        Returns:
            DataFrame with results for all configurations
        """
        configs = self.generate_configs()
        self.results = []
        
        total = len(configs)
        for i, (config_name, config_path) in enumerate(configs.items(), 1):
            logger.info(f"[{i}/{total}] Evaluating: {config_name}")
            
            try:
                evaluator = M03Evaluator(
                    config_path=str(config_path),
                    output_dir=self.output_dir / 'reports'
                )
                result = evaluator.evaluate(start_date=start_date, end_date=end_date)
                
                # Extract key metrics
                disc = result['discrimination']
                cal = result['calibration']
                passed = result['passed']
                
                # Get lag details for critical crashes
                lag_details = cal['reaction_lag']
                gfc_lag = None
                covid_lag = None
                for crash in lag_details['critical_crash_lags']:
                    if '2007' in crash['start_date']:
                        gfc_lag = crash['lag_days']
                    elif '2020' in crash['start_date']:
                        covid_lag = crash['lag_days']
                
                row = {
                    'config_name': config_name,
                    'archetype': config_name.rsplit('_', 1)[0],
                    'vix_curve': config_name.rsplit('_', 1)[1],
                    # Phase 1: Discrimination
                    'auc_bear': disc['auc_bear'],
                    'auc_bull': disc['auc_bull'],
                    'cohens_d': disc['cohens_d'],
                    'ks_stat': disc['ks_statistic'],
                    'separation_pts': disc['separation_points'],
                    'fitness': result['fitness'],
                    # Phase 2: Calibration
                    'ccr': cal['crash_capture_rate']['rate'],
                    'far': cal['false_alarm_rate']['rate'],
                    'avg_lag': lag_details['avg_lag'],
                    'gfc_lag': gfc_lag,
                    'covid_lag': covid_lag,
                    # Pass/Fail
                    'phase1_pass': passed['phase1_discrimination'],
                    'phase2_pass': passed['phase2_calibration'],
                }
                self.results.append(row)
                
            except Exception as e:
                logger.error(f"Failed to evaluate {config_name}: {e}")
                self.results.append({
                    'config_name': config_name,
                    'error': str(e),
                })
        
        # Create DataFrame and sort by fitness
        df = pd.DataFrame(self.results)
        if 'fitness' in df.columns:
            df = df.sort_values('fitness', ascending=False).reset_index(drop=True)
        
        return df
    
    def generate_comparison_report(self, df: pd.DataFrame = None) -> str:
        """
        Generate markdown comparison report.
        
        Args:
            df: Results DataFrame (uses cached results if not provided)
            
        Returns:
            Markdown report string
        """
        if df is None:
            df = pd.DataFrame(self.results)
        
        if df.empty:
            return "No results to report."
        
        lines = [
            "# M03 Grid Search Results",
            "",
            f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            f"**Configurations Tested:** {len(df)}",
            "",
            "## Rankings by Fitness Score",
            "",
            "| Rank | Config | Fitness | AUC_Bear | AUC_Bull | Cohen_D | GFC_Lag | COVID_Lag |",
            "|------|--------|---------|----------|----------|---------|---------|-----------|",
        ]
        
        for i, row in df.head(12).iterrows():
            if 'error' in row and pd.notna(row.get('error')):
                lines.append(f"| {i+1} | {row['config_name']} | ERROR | - | - | - | - | - |")
            else:
                lines.append(
                    f"| {i+1} | {row['config_name']} | {row['fitness']:.4f} | "
                    f"{row['auc_bear']:.3f} | {row['auc_bull']:.3f} | {row['cohens_d']:.2f} | "
                    f"{row.get('gfc_lag', 'N/A')} | {row.get('covid_lag', 'N/A')} |"
                )
        
        # Best config summary
        if 'fitness' in df.columns and not df['fitness'].isna().all():
            best = df.iloc[0]
            lines.extend([
                "",
                "## Best Configuration",
                "",
                f"**Winner:** `{best['config_name']}`",
                "",
                f"- **Fitness:** {best['fitness']:.4f}",
                f"- **AUC Bear:** {best['auc_bear']:.3f} (target >= 0.90)",
                f"- **AUC Bull:** {best['auc_bull']:.3f} (target >= 0.90)",
                f"- **Cohen's D:** {best['cohens_d']:.2f} (target >= 2.0)",
                f"- **GFC Lag:** {best.get('gfc_lag', 'N/A')} days",
                f"- **COVID Lag:** {best.get('covid_lag', 'N/A')} days",
                "",
            ])
            
            # Check if phase 1 passed
            if best.get('phase1_pass'):
                lines.append("> [!TIP]")
                lines.append("> Phase 1 PASSED. Ready to proceed with threshold calibration.")
            else:
                lines.append("> [!WARNING]")
                lines.append("> Phase 1 FAILED. Consider exploring additional archetypes.")
            
            lines.append("")
        
        # Archetype comparison
        if 'archetype' in df.columns:
            lines.extend([
                "## Archetype Comparison (Best per Archetype)",
                "",
                "| Archetype | Best VIX | Fitness | AUC_Bear | Cohen_D |",
                "|-----------|----------|---------|----------|---------|",
            ])
            
            for arch in ARCHETYPES.keys():
                arch_df = df[df['archetype'] == arch]
                if not arch_df.empty and 'fitness' in arch_df.columns:
                    best_arch = arch_df.iloc[0]  # Already sorted by fitness
                    lines.append(
                        f"| {arch} | {best_arch['vix_curve']} | {best_arch['fitness']:.4f} | "
                        f"{best_arch['auc_bear']:.3f} | {best_arch['cohens_d']:.2f} |"
                    )
        
        lines.append("")
        
        report = "\n".join(lines)
        
        # Save report
        report_path = self.output_dir / f"grid_search_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        report_path.write_text(report, encoding='utf-8')
        logger.info(f"Saved grid search report to {report_path}")
        
        return report
    
    def get_best_config_path(self, df: pd.DataFrame = None) -> Optional[Path]:
        """
        Get path to the best configuration file.
        
        Args:
            df: Results DataFrame (uses cached results if not provided)
            
        Returns:
            Path to best config JSON, or None if no valid results
        """
        if df is None:
            df = pd.DataFrame(self.results)
        
        if df.empty or 'config_name' not in df.columns:
            return None
        
        best_config_name = df.iloc[0]['config_name']
        return self.output_dir / f"{best_config_name}.json"


def run_m03_grid_search(
    start_date: str = '2007-01-01',
    end_date: str = '2024-12-31',
    verbose: bool = True,
) -> pd.DataFrame:
    """
    Convenience function to run M03 grid search.
    
    Args:
        start_date: Evaluation start date
        end_date: Evaluation end date
        verbose: Whether to print progress
        
    Returns:
        DataFrame with results
    """
    if verbose:
        logging.basicConfig(level=logging.INFO)
    
    searcher = M03GridSearch()
    df = searcher.run_grid_search(start_date=start_date, end_date=end_date)
    report = searcher.generate_comparison_report(df)
    
    if verbose:
        print(report)
    
    return df
