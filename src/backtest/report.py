"""
Backtest Report Generator
=========================
Generates comprehensive markdown reports with performance metrics,
trade analysis, forensic logs, and regime breakdowns.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


# ============================================================================
# ROLLING METRICS HELPERS
# ============================================================================

def calculate_rolling_sharpe(
    equity_curve: pd.DataFrame,
    window_months: int = 6,
    risk_free_rate: float = 0.0,
) -> pd.Series:
    """
    Calculate rolling Sharpe ratio over specified window.

    Args:
        equity_curve: DataFrame with 'value' column and datetime index
        window_months: Rolling window in months (default 6)
        risk_free_rate: Annual risk-free rate (default 0)

    Returns:
        Series of rolling Sharpe ratios
    """
    if equity_curve is None or len(equity_curve) < 21:
        return pd.Series(dtype=float)

    # Calculate daily returns
    returns = equity_curve['value'].pct_change().dropna()

    # Approximate window in trading days (21 days/month)
    window_days = window_months * 21

    if len(returns) < window_days:
        return pd.Series(dtype=float)

    # Daily risk-free rate
    daily_rf = risk_free_rate / 252

    # Rolling Sharpe (annualized)
    rolling_mean = returns.rolling(window=window_days).mean()
    rolling_std = returns.rolling(window=window_days).std()

    rolling_sharpe = ((rolling_mean - daily_rf) / rolling_std) * np.sqrt(252)

    return rolling_sharpe.dropna()


def _generate_rolling_metrics_section(
    equity_curve: pd.DataFrame,
    window_months: int = 6,
) -> List[str]:
    """Generate rolling metrics section for report."""
    lines = []
    lines.append("\n## Rolling Metrics")
    lines.append("")

    if equity_curve is None or len(equity_curve) < 130:  # ~6 months
        lines.append(f"*Insufficient data for {window_months}-month rolling metrics (need ~{window_months * 21} trading days)*")
        return lines

    rolling_sharpe = calculate_rolling_sharpe(equity_curve, window_months)

    if len(rolling_sharpe) == 0:
        lines.append("*Could not calculate rolling Sharpe*")
        return lines

    lines.append(f"### Rolling {window_months}-Month Sharpe")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Current | {rolling_sharpe.iloc[-1]:.2f} |")
    lines.append(f"| Average | {rolling_sharpe.mean():.2f} |")
    lines.append(f"| Min | {rolling_sharpe.min():.2f} |")
    lines.append(f"| Max | {rolling_sharpe.max():.2f} |")

    # Periods with negative Sharpe
    negative_periods = (rolling_sharpe < 0).sum()
    total_periods = len(rolling_sharpe)
    negative_pct = negative_periods / total_periods * 100 if total_periods > 0 else 0

    lines.append("")
    lines.append(f"**Consistency:** {negative_pct:.1f}% of rolling periods had negative Sharpe")

    return lines


def _generate_signal_rejection_section(metrics: Dict[str, Any]) -> List[str]:
    """Generate signal rejection analysis section."""
    lines = []
    lines.append("\n## Signal Rejection Analysis")
    lines.append("")

    rejection_stats = metrics.get('rejection_stats', {})
    if not rejection_stats or rejection_stats.get('total_rejections', 0) == 0:
        lines.append("*No signal rejections recorded*")
        return lines

    total = rejection_stats['total_rejections']
    by_reason = rejection_stats.get('by_reason', {})

    lines.append(f"**Total Signals Rejected:** {total:,}")
    lines.append("")
    lines.append("### Rejection Reasons")
    lines.append("")
    lines.append("| Reason | Count | % of Total |")
    lines.append("|--------|-------|------------|")

    for reason, count in sorted(by_reason.items(), key=lambda x: -x[1]):
        pct = count / total * 100
        reason_display = {
            'no_slots': 'No Available Slots',
            'cooldown': 'In Cooldown Period',
            'already_holding': 'Already Holding',
            'low_liquidity': 'Low Liquidity',
            'low_price': 'Price Below Min',
            'no_data': 'No Price Data',
        }.get(reason, reason)
        lines.append(f"| {reason_display} | {count:,} | {pct:.1f}% |")

    # Interpretation
    lines.append("")
    no_slots_pct = by_reason.get('no_slots', 0) / total * 100 if total > 0 else 0
    if no_slots_pct > 50:
        lines.append(f"**Capacity Constraint:** {no_slots_pct:.1f}% rejections due to position limits. "
                    "Consider increasing `regime_max_pos` or tightening entry filters.")
    cooldown_pct = by_reason.get('cooldown', 0) / total * 100 if total > 0 else 0
    if cooldown_pct > 20:
        lines.append(f"**High Cooldown:** {cooldown_pct:.1f}% rejections due to cooldown. "
                    "Consider reducing `cooldown_days` or improving stop placement.")

    return lines


# ============================================================================
# FORENSIC ANALYSIS HELPERS
# ============================================================================

def _generate_worst_trades_section(trade_df: pd.DataFrame, n: int = 5) -> List[str]:
    """Generate top N worst trades for debugging -27% type losses."""
    lines = []
    lines.append("\n### Worst Trades (Forensic Log)")
    lines.append("")
    lines.append("**Investigate any loss exceeding 10% (hard stop should cap at ~10%)**")
    lines.append("")

    worst = trade_df.nsmallest(n, 'pnl_percent')
    lines.append("| Ticker | Entry Date | Exit Date | Entry $ | Exit $ | PnL % | Reason | Regime |")
    lines.append("|--------|------------|-----------|---------|--------|-------|--------|--------|")

    for _, row in worst.iterrows():
        entry_dt = row['entry_date'].strftime('%Y-%m-%d') if pd.notna(row['entry_date']) else 'N/A'
        exit_dt = row['exit_date'].strftime('%Y-%m-%d') if pd.notna(row['exit_date']) else 'N/A'
        lines.append(
            f"| {row['ticker']} | {entry_dt} | {exit_dt} | "
            f"${row['entry_price']:.2f} | ${row['exit_price']:.2f} | "
            f"**{row['pnl_percent']:.2f}%** | {row['exit_reason']} | {row['entry_regime']} |"
        )

    # Flag any violation of the 10% hard stop
    violations = trade_df[trade_df['pnl_percent'] < -12]  # Allow 2% slippage buffer
    if len(violations) > 0:
        lines.append("")
        lines.append(f"**WARNING:** {len(violations)} trades exceeded -12% loss (possible causes: gap down, regime liquidation, bug)")

    return lines


def _generate_best_trades_section(trade_df: pd.DataFrame, n: int = 5) -> List[str]:
    """Generate top N best trades."""
    lines = []
    lines.append("\n### Best Trades")
    lines.append("")

    best = trade_df.nlargest(n, 'pnl_percent')
    lines.append("| Ticker | Entry Date | Exit Date | Entry $ | Exit $ | PnL % | Reason | Regime |")
    lines.append("|--------|------------|-----------|---------|--------|-------|--------|--------|")

    for _, row in best.iterrows():
        entry_dt = row['entry_date'].strftime('%Y-%m-%d') if pd.notna(row['entry_date']) else 'N/A'
        exit_dt = row['exit_date'].strftime('%Y-%m-%d') if pd.notna(row['exit_date']) else 'N/A'
        lines.append(
            f"| {row['ticker']} | {entry_dt} | {exit_dt} | "
            f"${row['entry_price']:.2f} | ${row['exit_price']:.2f} | "
            f"**+{row['pnl_percent']:.2f}%** | {row['exit_reason']} | {row['entry_regime']} |"
        )

    return lines


def _generate_exposure_section(metrics: Dict[str, Any]) -> List[str]:
    """Generate exposure and capital efficiency metrics."""
    lines = []
    lines.append("\n## Exposure & Efficiency")
    lines.append("")

    exposure_stats = metrics.get('exposure_stats', {})
    if not exposure_stats:
        lines.append("*Exposure data not available (requires equity curve tracking)*")
        return lines

    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Avg Exposure | {exposure_stats.get('avg_exposure', 0):.1f}% |")
    lines.append(f"| Max Exposure | {exposure_stats.get('max_exposure', 0):.1f}% |")
    lines.append(f"| Time Invested | {exposure_stats.get('time_invested', 0):.1f}% |")
    lines.append(f"| Avg Position Count | {exposure_stats.get('avg_positions', 0):.1f} |")

    # Cash drag commentary
    avg_exp = exposure_stats.get('avg_exposure', 0)
    if avg_exp < 30:
        lines.append(f"\n**Cash Drag Warning:** Only {avg_exp:.1f}% average exposure. "
                    "Consider relaxing entry filters or increasing position sizes.")
    elif avg_exp > 90:
        lines.append(f"\n**High Exposure:** {avg_exp:.1f}% average exposure. "
                    "Monitor for liquidity constraints.")

    return lines


def _generate_fee_section(metrics: Dict[str, Any], trade_df: pd.DataFrame) -> List[str]:
    """Generate transaction cost summary."""
    lines = []
    lines.append("\n### Transaction Costs")
    lines.append("")

    commission_total = metrics.get('commission_total', 0)
    slippage_total = metrics.get('slippage_total', 0)
    gross_profit = metrics.get('gross_profit', 0)
    net_profit = metrics.get('net_profit', 0)

    # Estimate if not directly available
    if commission_total == 0 and len(trade_df) > 0:
        # Rough estimate: $0.005/share * avg_size * 2 (entry + exit) * trades
        avg_size = trade_df['initial_size'].mean() if 'initial_size' in trade_df.columns else 100
        commission_total = 0.005 * avg_size * 2 * len(trade_df)

    lines.append(f"- **Estimated Commission:** ${commission_total:,.2f}")
    lines.append(f"- **Gross Profit:** ${gross_profit:,.2f}")
    lines.append(f"- **Net Profit:** ${net_profit:,.2f}")

    if gross_profit > 0:
        fee_drag = (gross_profit - net_profit) / gross_profit * 100
        lines.append(f"- **Fee Drag:** {fee_drag:.1f}% of gross profit")

    return lines


def generate_report(
    metrics: Dict[str, Any],
    trade_df: Optional[pd.DataFrame] = None,
    equity_curve: Optional[pd.DataFrame] = None,
    output_path: Optional[str] = None,
    start_date: str = None,
    end_date: str = None,
    initial_cash: float = 100_000,
    strategy_params: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Generate a comprehensive backtest report.

    Args:
        metrics: Dict from runner.run() with backtest metrics
        trade_df: DataFrame of closed trades from TradeLogger
        equity_curve: DataFrame with daily portfolio values (for rolling metrics)
        output_path: Where to save the markdown report
        start_date: Backtest start date
        end_date: Backtest end date
        initial_cash: Starting capital
        strategy_params: Strategy parameters (min_score, min_percentile, etc.)

    Returns:
        Markdown report string
    """
    if strategy_params is None:
        strategy_params = {}
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    report = []
    report.append("# SEPA Hybrid V1 Backtest Report")
    report.append(f"\nGenerated: {timestamp}")

    # === OVERVIEW ===
    report.append("\n## Overview")
    report.append("")
    report.append(f"| Parameter | Value |")
    report.append(f"|-----------|-------|")
    report.append(f"| Period | {start_date or 'N/A'} to {end_date or 'N/A'} |")
    report.append(f"| Starting Capital | ${initial_cash:,.0f} |")
    report.append(f"| Final Value | ${metrics.get('ending_value', 0):,.2f} |")
    report.append(f"| Total Return | {metrics.get('total_return', 0):+.2f}% |")

    # === PERFORMANCE METRICS ===
    report.append("\n## Performance Metrics")
    report.append("")
    report.append("| Metric | Value |")
    report.append("|--------|-------|")
    report.append(f"| Sharpe Ratio | {_fmt(metrics.get('sharpe_ratio'))} |")
    report.append(f"| SQN | {_fmt(metrics.get('sqn'))} |")
    report.append(f"| Max Drawdown | {metrics.get('max_drawdown', 0):.2f}% |")
    report.append(f"| Max DD Duration | {metrics.get('max_drawdown_len', 0)} bars |")

    # === TRADE STATISTICS ===
    report.append("\n## Trade Statistics")
    report.append("")
    report.append("| Metric | Value |")
    report.append("|--------|-------|")
    report.append(f"| Total Trades | {metrics.get('total_trades', 0)} |")
    report.append(f"| Win Rate | {metrics.get('win_rate', 0):.1f}% |")
    report.append(f"| Won | {metrics.get('won_trades', 0)} |")
    report.append(f"| Lost | {metrics.get('lost_trades', 0)} |")
    report.append(f"| Net Profit | ${metrics.get('net_profit', 0):,.2f} |")

    # === TRADE ANALYSIS (if trade_df provided) ===
    if trade_df is not None and len(trade_df) > 0:
        report.append("\n## Trade Analysis")

        # Exit reason breakdown
        report.append("\n### Exit Reasons")
        report.append("")
        exit_counts = trade_df['exit_reason'].value_counts()
        report.append("| Reason | Count | % |")
        report.append("|--------|-------|---|")
        for reason, count in exit_counts.items():
            pct = count / len(trade_df) * 100
            report.append(f"| {reason} | {count} | {pct:.1f}% |")

        # Regime breakdown
        if 'entry_regime' in trade_df.columns:
            report.append("\n### Performance by Entry Regime")
            report.append("")

            regime_names = {
                0: 'Strong Bear',
                1: 'Bear',
                2: 'Neutral',
                3: 'Bull',
                4: 'Strong Bull',
            }

            regime_stats = trade_df.groupby('entry_regime').agg({
                'ticker': 'count',
                'pnl_percent': ['mean', 'sum'],
            }).round(2)

            report.append("| Regime | Trades | Avg PnL % | Total PnL % |")
            report.append("|--------|--------|-----------|-------------|")

            for regime in sorted(trade_df['entry_regime'].unique()):
                name = regime_names.get(regime, f'Regime {regime}')
                trades = len(trade_df[trade_df['entry_regime'] == regime])
                subset = trade_df[trade_df['entry_regime'] == regime]
                avg_pnl = subset['pnl_percent'].mean()
                total_pnl = subset['pnl_percent'].sum()
                report.append(f"| {name} | {trades} | {avg_pnl:.2f}% | {total_pnl:.2f}% |")

        # Holding period analysis
        if 'holding_days' in trade_df.columns:
            report.append("\n### Holding Period")
            report.append("")
            report.append(f"- Average: {trade_df['holding_days'].mean():.1f} days")
            report.append(f"- Median: {trade_df['holding_days'].median():.1f} days")
            report.append(f"- Max: {trade_df['holding_days'].max()} days")
            report.append(f"- Min: {trade_df['holding_days'].min()} days")

        # Win/Loss analysis
        winners = trade_df[trade_df['pnl_percent'] > 0]
        losers = trade_df[trade_df['pnl_percent'] <= 0]

        if len(winners) > 0 and len(losers) > 0:
            report.append("\n### Win/Loss Analysis")
            report.append("")
            report.append("| Metric | Winners | Losers |")
            report.append("|--------|---------|--------|")
            report.append(f"| Count | {len(winners)} | {len(losers)} |")
            report.append(f"| Avg PnL % | {winners['pnl_percent'].mean():.2f}% | {losers['pnl_percent'].mean():.2f}% |")
            report.append(f"| Max | {winners['pnl_percent'].max():.2f}% | {losers['pnl_percent'].min():.2f}% |")

            # Profit factor
            gross_profit_pct = winners['pnl_percent'].sum()
            gross_loss_pct = abs(losers['pnl_percent'].sum())
            if gross_loss_pct > 0:
                profit_factor = gross_profit_pct / gross_loss_pct
                report.append(f"\n**Profit Factor:** {profit_factor:.2f}")

        # === FORENSIC LOGS ===
        report.extend(_generate_worst_trades_section(trade_df, n=5))
        report.extend(_generate_best_trades_section(trade_df, n=5))
        report.extend(_generate_fee_section(metrics, trade_df))

    # === EXPOSURE METRICS ===
    report.extend(_generate_exposure_section(metrics))

    # === ROLLING METRICS ===
    report.extend(_generate_rolling_metrics_section(equity_curve))

    # === SIGNAL REJECTION ANALYSIS ===
    report.extend(_generate_signal_rejection_section(metrics))

    # === TRACKER STATS ===
    tracker_stats = metrics.get('tracker_stats', {})
    if tracker_stats:
        report.append("\n## Position Tracker Stats")
        report.append("")
        for key, value in tracker_stats.items():
            if isinstance(value, float):
                report.append(f"- {key}: {value:.2f}")
            elif isinstance(value, dict):
                report.append(f"- {key}:")
                for k, v in value.items():
                    report.append(f"  - {k}: {v}")
            else:
                report.append(f"- {key}: {value}")

    # === METHODOLOGY ===
    report.append("\n## Methodology")
    report.append("")
    report.append("### Strategy Components")
    min_score = strategy_params.get('min_score', 30)
    min_pct = strategy_params.get('min_percentile', 0.95)
    top_pct = int((1 - min_pct) * 100)  # 0.95 -> top 5%
    report.append(f"- **M01 (Selection):** Normalized score >= {min_score} AND top {top_pct}% daily")
    report.append("- **M03 (Regime):** Regime-based position sizing and gating")
    report.append("- **Exit Logic:** 3-tranche scale-out with trailing stops")
    report.append("")
    report.append("### Regime Sizing")
    report.append("| Regime | Position Size | Max Positions |")
    report.append("|--------|---------------|---------------|")
    report.append("| Strong Bear (0) | 0% (No entries) | 0 |")
    report.append("| Bear (1) | 2.5% | 4 |")
    report.append("| Neutral (2) | 5.0% | 8 |")
    report.append("| Bull (3) | 7.5% | 10 |")
    report.append("| Strong Bull (4) | 10.0% | 12 |")

    # Join report
    report_str = '\n'.join(report)

    # Save if path provided
    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w') as f:
            f.write(report_str)
        logger.info(f"Saved report to {output_path}")

    return report_str


def _fmt(value: Any, decimals: int = 2) -> str:
    """Format a value for display."""
    if value is None:
        return 'N/A'
    if isinstance(value, float):
        return f"{value:.{decimals}f}"
    return str(value)


def generate_monthly_returns(
    equity_curve: pd.Series,
) -> pd.DataFrame:
    """
    Generate monthly returns table.

    Args:
        equity_curve: Series with datetime index and portfolio values

    Returns:
        DataFrame with monthly returns (rows=years, cols=months)
    """
    # Calculate daily returns
    returns = equity_curve.pct_change()

    # Resample to monthly
    monthly = (1 + returns).resample('M').prod() - 1

    # Pivot to year x month format
    monthly_df = pd.DataFrame(monthly)
    monthly_df.columns = ['return']
    monthly_df['year'] = monthly_df.index.year
    monthly_df['month'] = monthly_df.index.month

    pivot = monthly_df.pivot(index='year', columns='month', values='return')
    pivot.columns = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                     'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

    # Add yearly totals
    pivot['Year'] = pivot.sum(axis=1)

    return pivot * 100  # Convert to percentage


if __name__ == '__main__':
    # Test report generation
    test_metrics = {
        'starting_value': 100000,
        'ending_value': 125000,
        'total_return': 25.0,
        'sharpe_ratio': 1.5,
        'sqn': 2.1,
        'max_drawdown': 15.0,
        'max_drawdown_len': 45,
        'total_trades': 150,
        'won_trades': 90,
        'lost_trades': 60,
        'win_rate': 60.0,
        'net_profit': 25000,
    }

    report = generate_report(
        metrics=test_metrics,
        start_date='2020-01-01',
        end_date='2025-01-01',
    )
    print(report)
