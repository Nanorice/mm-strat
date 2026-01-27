"""
Visualization Library for Dashboard Reports
===========================================

Reusable Plotly visualization functions for ML model analysis.

Usage:
    from src.viz_library import create_mae_mfe_scatter, create_decile_bar_chart

    fig = create_mae_mfe_scatter(data)
    st.plotly_chart(fig, use_container_width=True)
"""

import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple


# =============================================================================
# D1 ANALYSIS VISUALIZATIONS (Trade Physics)
# =============================================================================

def create_mae_mfe_scatter(data: List[Dict]) -> go.Figure:
    """
    MAE/MFE scatter plot with E-Ratio reference lines.

    Args:
        data: List of dicts with keys: MAE, MFE, is_survivor

    Returns:
        Plotly Figure
    """
    df = pd.DataFrame(data)

    # Separate survivors and crashes
    survivors = df[df['is_survivor'] == True]
    crashes = df[df['is_survivor'] == False]

    fig = go.Figure()

    # Add E-Ratio reference lines
    max_val = max(abs(df['MAE'].min()), df['MFE'].max())
    x_line = np.linspace(-max_val, 0, 100)

    for e_ratio, color, dash in [(1.0, 'gray', 'dash'), (2.0, 'orange', 'dot'), (3.0, 'green', 'solid')]:
        fig.add_trace(go.Scatter(
            x=x_line,
            y=-x_line * e_ratio,
            mode='lines',
            line=dict(color=color, dash=dash, width=1),
            name=f'E-Ratio {e_ratio}',
            hovertemplate=f'E-Ratio: {e_ratio}<extra></extra>',
            showlegend=True
        ))

    # Crashes (hit stop)
    if len(crashes) > 0:
        fig.add_trace(go.Scatter(
            x=crashes['MAE'],
            y=crashes['MFE'],
            mode='markers',
            marker=dict(color='red', size=6, opacity=0.6),
            name='Crashed',
            hovertemplate='<b>Crashed Trade</b><br>' +
                         'MAE: %{x:.1f}%<br>' +
                         'MFE: %{y:.1f}%<br>' +
                         'E-Ratio: %{customdata:.2f}<extra></extra>',
            customdata=crashes['MFE'] / abs(crashes['MAE'])
        ))

    # Survivors
    if len(survivors) > 0:
        fig.add_trace(go.Scatter(
            x=survivors['MAE'],
            y=survivors['MFE'],
            mode='markers',
            marker=dict(color='green', size=6, opacity=0.6),
            name='Survivor',
            hovertemplate='<b>Survivor Trade</b><br>' +
                         'MAE: %{x:.1f}%<br>' +
                         'MFE: %{y:.1f}%<br>' +
                         'E-Ratio: %{customdata:.2f}<extra></extra>',
            customdata=survivors['MFE'] / abs(survivors['MAE'])
        ))

    # Layout
    fig.update_layout(
        title='Maximum Adverse/Favorable Excursion Analysis',
        xaxis_title='MAE (Max Adverse Excursion %)',
        yaxis_title='MFE (Max Favorable Excursion %)',
        template='plotly_white',
        hovermode='closest',
        height=500,
        legend=dict(x=0.02, y=0.98, bgcolor='rgba(255,255,255,0.8)')
    )

    return fig


def create_e_ratio_histogram(data: List[float], benchmark: float = 3.0) -> go.Figure:
    """
    E-Ratio distribution histogram with benchmark line.

    Args:
        data: List of E-Ratio values
        benchmark: E-Ratio benchmark threshold (default: 3.0)

    Returns:
        Plotly Figure
    """
    df = pd.Series(data)

    # Calculate stats
    pct_above = (df >= benchmark).mean() * 100
    median_val = df.median()
    mean_val = df.mean()

    fig = go.Figure()

    # Histogram
    fig.add_trace(go.Histogram(
        x=df,
        nbinsx=30,
        marker_color='steelblue',
        opacity=0.7,
        name='E-Ratio Distribution',
        hovertemplate='E-Ratio: %{x:.2f}<br>Count: %{y}<extra></extra>'
    ))

    # Benchmark line
    fig.add_vline(
        x=benchmark,
        line_dash="solid",
        line_color="red",
        line_width=2,
        annotation_text=f"Benchmark: {benchmark}",
        annotation_position="top right"
    )

    # Median line
    fig.add_vline(
        x=median_val,
        line_dash="dash",
        line_color="green",
        line_width=1.5,
        annotation_text=f"Median: {median_val:.2f}",
        annotation_position="top left"
    )

    # Layout
    fig.update_layout(
        title=f'E-Ratio Distribution (MFE/|MAE|)<br><sub>{pct_above:.1f}% above benchmark</sub>',
        xaxis_title='E-Ratio',
        yaxis_title='Count',
        template='plotly_white',
        showlegend=False,
        height=400
    )

    return fig


def create_time_to_peak_histogram(data: List[int]) -> go.Figure:
    """
    Time-to-peak histogram (days to reach MFE).

    Args:
        data: List of days to reach MFE

    Returns:
        Plotly Figure
    """
    df = pd.Series(data)

    median_val = df.median()
    p75_val = df.quantile(0.75)

    fig = go.Figure()

    fig.add_trace(go.Histogram(
        x=df,
        nbinsx=30,
        marker_color='orange',
        opacity=0.7,
        hovertemplate='Days: %{x}<br>Count: %{y}<extra></extra>'
    ))

    fig.add_vline(
        x=median_val,
        line_dash="dash",
        line_color="red",
        annotation_text=f"Median: {median_val:.0f}d",
        annotation_position="top right"
    )

    fig.add_vline(
        x=p75_val,
        line_dash="dot",
        line_color="gray",
        annotation_text=f"75th: {p75_val:.0f}d",
        annotation_position="top left"
    )

    fig.update_layout(
        title='Time to Peak (Days to Reach MFE)',
        xaxis_title='Days',
        yaxis_title='Count',
        template='plotly_white',
        height=400
    )

    return fig


# =============================================================================
# M01 VISUALIZATIONS (Regression)
# =============================================================================

def create_decile_bar_chart(decile_data: List[Dict]) -> go.Figure:
    """
    Decile performance bar chart with gradient coloring.

    Args:
        decile_data: List of dicts with keys: decile, mean_return, count

    Returns:
        Plotly Figure
    """
    df = pd.DataFrame(decile_data).sort_values('decile')

    # Create gradient color scale
    colors = df['mean_return'].values

    fig = go.Figure()

    fig.add_trace(go.Bar(
        x=df['decile'],
        y=df['mean_return'],
        marker=dict(
            color=colors,
            colorscale='RdYlGn',
            colorbar=dict(title="Return %"),
            line=dict(color='white', width=1)
        ),
        hovertemplate='<b>Decile %{x}</b><br>' +
                     'Mean Return: %{y:.2f}%<br>' +
                     'Count: %{customdata}<extra></extra>',
        customdata=df['count']
    ))

    # Add median baseline
    median_return = df['mean_return'].median()
    fig.add_hline(
        y=median_return,
        line_dash="dash",
        line_color="gray",
        annotation_text=f"Median: {median_return:.2f}%",
        annotation_position="right"
    )

    fig.update_layout(
        title='Decile Performance Analysis<br><sub>Top decile (1) = highest predicted returns</sub>',
        xaxis_title='Decile',
        yaxis_title='Mean Return %',
        template='plotly_white',
        height=450,
        xaxis=dict(tickmode='linear', dtick=1)
    )

    return fig


def create_actual_vs_predicted_scatter(predictions: List[Dict], max_points: int = 1000) -> go.Figure:
    """
    Actual vs predicted scatter plot with R² overlay.

    Args:
        predictions: List of dicts with keys: y_pred, y_true, decile
        max_points: Maximum points to plot (for performance)

    Returns:
        Plotly Figure
    """
    df = pd.DataFrame(predictions)

    # Sample if too many points
    if len(df) > max_points:
        df = df.sample(n=max_points, random_state=42)

    # Calculate R²
    y_true = df['y_true'].values
    y_pred = df['y_pred'].values
    ss_res = np.sum((y_true - y_pred) ** 2)
    ss_tot = np.sum((y_true - np.mean(y_true)) ** 2)
    r2 = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0

    # Calculate RMSE
    rmse = np.sqrt(np.mean((y_true - y_pred) ** 2))

    fig = go.Figure()

    # Scatter plot
    fig.add_trace(go.Scatter(
        x=df['y_pred'],
        y=df['y_true'],
        mode='markers',
        marker=dict(
            color=df['decile'],
            colorscale='Viridis',
            size=5,
            opacity=0.6,
            colorbar=dict(title="Decile"),
            line=dict(color='white', width=0.5)
        ),
        hovertemplate='<b>Prediction</b><br>' +
                     'Predicted: %{x:.2f}%<br>' +
                     'Actual: %{y:.2f}%<br>' +
                     'Decile: %{marker.color}<extra></extra>'
    ))

    # Perfect prediction line (y=x)
    min_val = min(df['y_pred'].min(), df['y_true'].min())
    max_val = max(df['y_pred'].max(), df['y_true'].max())
    fig.add_trace(go.Scatter(
        x=[min_val, max_val],
        y=[min_val, max_val],
        mode='lines',
        line=dict(color='red', dash='dash', width=2),
        name='Perfect Prediction',
        hoverinfo='skip'
    ))

    fig.update_layout(
        title=f'Actual vs Predicted Returns<br><sub>R² = {r2:.3f} | RMSE = {rmse:.2f}%</sub>',
        xaxis_title='Predicted Return %',
        yaxis_title='Actual Return %',
        template='plotly_white',
        height=500,
        showlegend=True
    )

    return fig


def create_feature_importance_waterfall(importance_df: pd.DataFrame, top_n: int = 20) -> go.Figure:
    """
    Feature importance waterfall chart with cumulative contribution.

    Args:
        importance_df: DataFrame with columns: feature, gain, cumulative_pct
        top_n: Number of top features to display

    Returns:
        Plotly Figure
    """
    df = importance_df.head(top_n).copy()

    fig = go.Figure()

    # Waterfall bars
    fig.add_trace(go.Bar(
        y=df['feature'],
        x=df['gain_pct'],
        orientation='h',
        marker=dict(
            color=df['gain_pct'],
            colorscale='Blues',
            line=dict(color='white', width=1)
        ),
        hovertemplate='<b>%{y}</b><br>' +
                     'Gain: %{x:.1f}%<br>' +
                     'Cumulative: %{customdata:.1f}%<extra></extra>',
        customdata=df['cumulative_pct']
    ))

    # 80% threshold line
    fig.add_vline(
        x=80,
        line_dash="dash",
        line_color="red",
        annotation_text="80% threshold",
        annotation_position="top"
    )

    fig.update_layout(
        title=f'Feature Importance (Top {top_n})<br><sub>Sorted by XGBoost gain</sub>',
        xaxis_title='Contribution to Total Gain (%)',
        yaxis_title='Feature',
        template='plotly_white',
        height=max(500, top_n * 25),
        showlegend=False
    )

    return fig


def create_residual_plot(predictions: List[Dict]) -> go.Figure:
    """
    Residual analysis: residuals vs predicted values + residual histogram.

    Args:
        predictions: List of dicts with keys: y_pred, y_true

    Returns:
        Plotly Figure with subplots
    """
    from plotly.subplots import make_subplots

    df = pd.DataFrame(predictions)
    df['residual'] = df['y_true'] - df['y_pred']

    fig = make_subplots(
        rows=1, cols=2,
        subplot_titles=('Residuals vs Predicted', 'Residual Distribution'),
        horizontal_spacing=0.12
    )

    # Residual scatter
    fig.add_trace(
        go.Scatter(
            x=df['y_pred'],
            y=df['residual'],
            mode='markers',
            marker=dict(color='steelblue', size=4, opacity=0.5),
            hovertemplate='Predicted: %{x:.2f}%<br>Residual: %{y:.2f}%<extra></extra>'
        ),
        row=1, col=1
    )

    # Zero line
    fig.add_hline(
        y=0,
        line_dash="dash",
        line_color="red",
        row=1, col=1
    )

    # Residual histogram
    fig.add_trace(
        go.Histogram(
            x=df['residual'],
            nbinsx=30,
            marker_color='orange',
            opacity=0.7,
            hovertemplate='Residual: %{x:.2f}%<br>Count: %{y}<extra></extra>'
        ),
        row=1, col=2
    )

    fig.update_xaxes(title_text="Predicted Return %", row=1, col=1)
    fig.update_yaxes(title_text="Residual (Actual - Predicted) %", row=1, col=1)
    fig.update_xaxes(title_text="Residual %", row=1, col=2)
    fig.update_yaxes(title_text="Count", row=1, col=2)

    fig.update_layout(
        title_text='Residual Analysis',
        template='plotly_white',
        showlegend=False,
        height=400
    )

    return fig


# =============================================================================
# M02 VISUALIZATIONS (Classification)
# =============================================================================

def create_confusion_matrix(cm_data: Dict) -> go.Figure:
    """
    Confusion matrix heatmap for binary classification.

    Args:
        cm_data: Dict with keys: TP, FP, TN, FN

    Returns:
        Plotly Figure
    """
    tp, fp, tn, fn = cm_data['TP'], cm_data['FP'], cm_data['TN'], cm_data['FN']

    matrix = np.array([
        [tp, fp],
        [fn, tn]
    ])

    total = matrix.sum()
    matrix_pct = (matrix / total * 100).round(1)

    # Custom text with counts and percentages
    text = [
        [f"TP<br>{tp}<br>({matrix_pct[0,0]:.1f}%)", f"FP<br>{fp}<br>({matrix_pct[0,1]:.1f}%)"],
        [f"FN<br>{fn}<br>({matrix_pct[1,0]:.1f}%)", f"TN<br>{tn}<br>({matrix_pct[1,1]:.1f}%)"]
    ]

    fig = go.Figure(data=go.Heatmap(
        z=matrix,
        x=['Predicted: Positive (TP)', 'Predicted: Negative (SL/Time)'],
        y=['Actual: Positive (TP)', 'Actual: Negative (SL/Time)'],
        text=text,
        texttemplate="%{text}",
        textfont={"size": 14},
        colorscale='Blues',
        showscale=True,
        colorbar=dict(title="Count")
    ))

    # Calculate metrics
    accuracy = (tp + tn) / total
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0

    fig.update_layout(
        title=f'Confusion Matrix<br><sub>Acc: {accuracy:.2%} | Prec: {precision:.2%} | Recall: {recall:.2%} | F1: {f1:.2%}</sub>',
        xaxis_title='Predicted Label',
        yaxis_title='Actual Label',
        template='plotly_white',
        height=500
    )

    return fig


def create_roc_curve(roc_data: List[Dict], auc: float) -> go.Figure:
    """
    ROC curve with AUC score.

    Args:
        roc_data: List of dicts with keys: fpr, tpr, threshold
        auc: Area under curve

    Returns:
        Plotly Figure
    """
    df = pd.DataFrame(roc_data).sort_values('fpr')

    fig = go.Figure()

    # ROC curve
    fig.add_trace(go.Scatter(
        x=df['fpr'],
        y=df['tpr'],
        mode='lines',
        line=dict(color='blue', width=2),
        name=f'ROC (AUC = {auc:.3f})',
        hovertemplate='FPR: %{x:.3f}<br>TPR: %{y:.3f}<br>Threshold: %{customdata:.3f}<extra></extra>',
        customdata=df['threshold']
    ))

    # Random classifier baseline
    fig.add_trace(go.Scatter(
        x=[0, 1],
        y=[0, 1],
        mode='lines',
        line=dict(color='red', dash='dash', width=1),
        name='Random (AUC = 0.5)',
        hoverinfo='skip'
    ))

    fig.update_layout(
        title=f'ROC Curve<br><sub>AUC = {auc:.3f}</sub>',
        xaxis_title='False Positive Rate',
        yaxis_title='True Positive Rate',
        template='plotly_white',
        height=500,
        showlegend=True,
        xaxis=dict(range=[0, 1]),
        yaxis=dict(range=[0, 1])
    )

    return fig


def create_precision_recall_curve(pr_data: List[Dict]) -> go.Figure:
    """
    Precision-Recall curve (important for imbalanced classes).

    Args:
        pr_data: List of dicts with keys: precision, recall, threshold

    Returns:
        Plotly Figure
    """
    df = pd.DataFrame(pr_data).sort_values('recall')

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=df['recall'],
        y=df['precision'],
        mode='lines',
        line=dict(color='green', width=2),
        name='PR Curve',
        fill='tozeroy',
        fillcolor='rgba(0,128,0,0.1)',
        hovertemplate='Recall: %{x:.3f}<br>Precision: %{y:.3f}<br>Threshold: %{customdata:.3f}<extra></extra>',
        customdata=df['threshold']
    ))

    fig.update_layout(
        title='Precision-Recall Curve<br><sub>Critical for imbalanced classes</sub>',
        xaxis_title='Recall (True Positive Rate)',
        yaxis_title='Precision (Positive Predictive Value)',
        template='plotly_white',
        height=500,
        xaxis=dict(range=[0, 1]),
        yaxis=dict(range=[0, 1])
    )

    return fig


def create_calibration_plot(calibration_data: List[Dict]) -> go.Figure:
    """
    Calibration plot: predicted probability vs actual outcome rate.

    Args:
        calibration_data: List of dicts with keys: prob_bin, predicted, actual, count

    Returns:
        Plotly Figure
    """
    df = pd.DataFrame(calibration_data)

    fig = go.Figure()

    # Calibration curve
    fig.add_trace(go.Scatter(
        x=df['predicted'],
        y=df['actual'],
        mode='lines+markers',
        line=dict(color='blue', width=2),
        marker=dict(size=8),
        name='Model Calibration',
        hovertemplate='<b>%{customdata}</b><br>' +
                     'Predicted Prob: %{x:.3f}<br>' +
                     'Actual TP Rate: %{y:.3f}<br>' +
                     'Sample Size: %{text}<extra></extra>',
        customdata=df['prob_bin'],
        text=df['count']
    ))

    # Perfect calibration line
    fig.add_trace(go.Scatter(
        x=[0, 1],
        y=[0, 1],
        mode='lines',
        line=dict(color='red', dash='dash', width=1),
        name='Perfect Calibration',
        hoverinfo='skip'
    ))

    fig.update_layout(
        title='Calibration Plot<br><sub>Predicted probability vs actual TP rate</sub>',
        xaxis_title='Predicted Probability',
        yaxis_title='Actual TP Rate',
        template='plotly_white',
        height=500,
        showlegend=True,
        xaxis=dict(range=[0, 1]),
        yaxis=dict(range=[0, 1])
    )

    return fig


def create_barrier_outcome_by_decile(outcome_data: List[Dict]) -> go.Figure:
    """
    Stacked bar chart: barrier outcomes by probability decile.

    Args:
        outcome_data: List of dicts with keys: decile, TP, SL, Time

    Returns:
        Plotly Figure
    """
    df = pd.DataFrame(outcome_data).sort_values('decile')

    fig = go.Figure()

    # TP (green)
    fig.add_trace(go.Bar(
        name='Take Profit',
        x=df['decile'],
        y=df['TP'] * 100,
        marker_color='green',
        hovertemplate='Decile %{x}<br>TP Rate: %{y:.1f}%<extra></extra>'
    ))

    # SL (red)
    fig.add_trace(go.Bar(
        name='Stop Loss',
        x=df['decile'],
        y=df['SL'] * 100,
        marker_color='red',
        hovertemplate='Decile %{x}<br>SL Rate: %{y:.1f}%<extra></extra>'
    ))

    # Time (gray)
    fig.add_trace(go.Bar(
        name='Time Exit',
        x=df['decile'],
        y=df['Time'] * 100,
        marker_color='gray',
        hovertemplate='Decile %{x}<br>Time Exit Rate: %{y:.1f}%<extra></extra>'
    ))

    fig.update_layout(
        barmode='stack',
        title='Barrier Outcomes by Probability Decile<br><sub>Higher decile = higher model confidence</sub>',
        xaxis_title='Probability Decile',
        yaxis_title='Outcome Distribution (%)',
        template='plotly_white',
        height=500,
        xaxis=dict(tickmode='linear', dtick=1)
    )

    return fig


# =============================================================================
# DUAL-MODEL VISUALIZATIONS
# =============================================================================

def create_complementarity_scatter(dual_data: List[Dict], max_points: int = 1000) -> go.Figure:
    """
    M01 expected return vs M02 ignition probability scatter.

    Args:
        dual_data: List of dicts with keys: m01_pred, m02_prob, outcome, actual_return
        max_points: Maximum points to plot

    Returns:
        Plotly Figure
    """
    df = pd.DataFrame(dual_data)

    # Sample if too many
    if len(df) > max_points:
        df = df.sample(n=max_points, random_state=42)

    # Color mapping
    color_map = {'TP': 'green', 'SL': 'red', 'Time': 'gray'}

    fig = go.Figure()

    for outcome in ['TP', 'SL', 'Time']:
        subset = df[df['outcome'] == outcome]
        if len(subset) > 0:
            fig.add_trace(go.Scatter(
                x=subset['m01_pred'],
                y=subset['m02_prob'],
                mode='markers',
                marker=dict(color=color_map[outcome], size=5, opacity=0.5),
                name=outcome,
                hovertemplate='<b>%{fullData.name}</b><br>' +
                             'M01 Predicted: %{x:.2f}%<br>' +
                             'M02 Probability: %{y:.3f}<br>' +
                             'Actual Return: %{customdata:.2f}%<extra></extra>',
                customdata=subset['actual_return']
            ))

    # Quadrant lines
    median_m01 = df['m01_pred'].median()
    median_m02 = df['m02_prob'].median()

    fig.add_hline(y=median_m02, line_dash="dash", line_color="black", opacity=0.3)
    fig.add_vline(x=median_m01, line_dash="dash", line_color="black", opacity=0.3)

    # Annotations for quadrants
    fig.add_annotation(x=df['m01_pred'].quantile(0.75), y=df['m02_prob'].quantile(0.75),
                      text="High Return<br>High Ignition", showarrow=False, opacity=0.5)
    fig.add_annotation(x=df['m01_pred'].quantile(0.25), y=df['m02_prob'].quantile(0.25),
                      text="Low Return<br>Low Ignition", showarrow=False, opacity=0.5)

    fig.update_layout(
        title='Dual-Model Complementarity Analysis<br><sub>M01 (return prediction) vs M02 (ignition probability)</sub>',
        xaxis_title='M01: Expected Return %',
        yaxis_title='M02: Ignition Probability',
        template='plotly_white',
        height=550,
        showlegend=True
    )

    return fig


# =============================================================================
# BACKTEST VISUALIZATIONS
# =============================================================================

def create_equity_curve(equity_data: List[Dict]) -> go.Figure:
    """
    Equity curve with drawdown shading.

    Args:
        equity_data: List of dicts with keys: date, portfolio_value, drawdown

    Returns:
        Plotly Figure
    """
    from plotly.subplots import make_subplots

    df = pd.DataFrame(equity_data)
    df['date'] = pd.to_datetime(df['date'])

    fig = make_subplots(
        rows=2, cols=1,
        row_heights=[0.7, 0.3],
        subplot_titles=('Portfolio Value', 'Drawdown'),
        vertical_spacing=0.1,
        shared_xaxes=True
    )

    # Equity curve
    fig.add_trace(
        go.Scatter(
            x=df['date'],
            y=df['portfolio_value'],
            mode='lines',
            line=dict(color='blue', width=2),
            name='Portfolio Value',
            hovertemplate='Date: %{x}<br>Value: $%{y:,.0f}<extra></extra>'
        ),
        row=1, col=1
    )

    # Drawdown
    fig.add_trace(
        go.Scatter(
            x=df['date'],
            y=df['drawdown'] * 100,
            mode='lines',
            fill='tozeroy',
            line=dict(color='red', width=1),
            fillcolor='rgba(255,0,0,0.2)',
            name='Drawdown',
            hovertemplate='Date: %{x}<br>Drawdown: %{y:.2f}%<extra></extra>'
        ),
        row=2, col=1
    )

    fig.update_xaxes(title_text="Date", row=2, col=1)
    fig.update_yaxes(title_text="Portfolio Value ($)", row=1, col=1)
    fig.update_yaxes(title_text="Drawdown (%)", row=2, col=1)

    fig.update_layout(
        title_text='Equity Curve & Drawdown Analysis',
        template='plotly_white',
        height=600,
        showlegend=True
    )

    return fig


def create_monthly_returns_heatmap(monthly_data: List[Dict]) -> go.Figure:
    """
    Monthly returns heatmap.

    Args:
        monthly_data: List of dicts with keys: year, month, return

    Returns:
        Plotly Figure
    """
    df = pd.DataFrame(monthly_data)

    # Pivot to heatmap format
    pivot = df.pivot(index='year', columns='month', values='return')
    pivot = pivot * 100  # Convert to percentage

    # Month names
    month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                   'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

    fig = go.Figure(data=go.Heatmap(
        z=pivot.values,
        x=month_names,
        y=pivot.index,
        colorscale='RdYlGn',
        zmid=0,
        text=pivot.values.round(1),
        texttemplate='%{text}%',
        textfont={"size": 10},
        colorbar=dict(title="Return %")
    ))

    fig.update_layout(
        title='Monthly Returns Heatmap',
        xaxis_title='Month',
        yaxis_title='Year',
        template='plotly_white',
        height=400
    )

    return fig


def create_trade_distribution_histogram(trade_returns: List[float]) -> go.Figure:
    """
    Histogram of trade returns distribution.

    Args:
        trade_returns: List of return % values

    Returns:
        Plotly Figure
    """
    df = pd.Series(trade_returns)

    mean_val = df.mean()
    median_val = df.median()
    std_val = df.std()

    fig = go.Figure()

    fig.add_trace(go.Histogram(
        x=df,
        nbinsx=40,
        marker_color='steelblue',
        opacity=0.7,
        hovertemplate='Return: %{x:.2f}%<br>Count: %{y}<extra></extra>'
    ))

    # Mean line
    fig.add_vline(
        x=mean_val,
        line_dash="solid",
        line_color="red",
        annotation_text=f"Mean: {mean_val:.2f}%",
        annotation_position="top right"
    )

    # Median line
    fig.add_vline(
        x=median_val,
        line_dash="dash",
        line_color="green",
        annotation_text=f"Median: {median_val:.2f}%",
        annotation_position="top left"
    )

    fig.update_layout(
        title=f'Trade Return Distribution<br><sub>Mean: {mean_val:.2f}% | Median: {median_val:.2f}% | Std: {std_val:.2f}%</sub>',
        xaxis_title='Return %',
        yaxis_title='Count',
        template='plotly_white',
        height=450
    )

    return fig
