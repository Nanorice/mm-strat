"""Feature Time Series — TradingView-style candlestick + feature panels."""

import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

DB_PATH = ROOT / "data" / "market_data.duckdb"

FEATURE_GROUPS = {
    "Momentum": [
        "rs", "rs_ma", "rs_velocity", "rs_rating",
        "mom_21d", "mom_63d", "mom_126d", "mom_252d",
        "breakout_momentum", "price_accel_10d", "price_momentum_curve",
    ],
    "Volatility": [
        "natr", "atr_20d", "volatility_20d",
        "vcp_ratio", "consolidation_width", "consolidation_duration",
    ],
    "Volume": [
        "vol_ratio", "vol_ratio_50", "dry_up_volume",
        "volume_acceleration", "turnover", "turnover_ma20",
    ],
    "Moving Averages": [
        "sma_20", "sma_50", "sma_150", "sma_200",
        "price_vs_sma_50", "price_vs_sma_150", "price_vs_sma_200",
        "sma_50_slope",
    ],
    "Oscillators": [
        "rsi_14", "green_days_ratio_20d",
    ],
    "52-Week Range": [
        "dist_from_52w_high", "dist_from_52w_low",
        "pct_from_high_52w", "pct_above_low_52w",
    ],
    "Relative Strength": [
        "RS_Universe_Rank", "RS_Sector_Rank", "RS_vs_Sector",
        "RS_Industry_Rank", "RS_vs_Industry",
        "Sector_Momentum", "Industry_Momentum",
    ],
    "Regime (M03)": [
        "m03_score", "m03_pillar_trend", "m03_pillar_liq", "m03_pillar_risk",
        "m03_delta_5d", "m03_delta_20d", "m03_regime_vol",
    ],
    "Returns": [
        "return_1d", "return_5d", "return_20d", "return_60d",
    ],
}

# Features that share the price y-axis (dollar-denominated or price-relative)
PRICE_OVERLAY_FEATURES = {
    "sma_20", "sma_50", "sma_150", "sma_200",
    "ema_8", "ema_21", "ema_50", "ema_100", "ema_200",
    "high_52w", "low_52w",
}

MA_COLORS = {
    "sma_20": "#ff9800", "sma_50": "#2196f3", "sma_150": "#9c27b0", "sma_200": "#e91e63",
    "ema_8": "#ff9800", "ema_21": "#2196f3", "ema_50": "#9c27b0",
    "ema_100": "#e91e63", "ema_200": "#4caf50",
    "high_52w": "#66bb6a", "low_52w": "#ef5350",
}

PANEL_COLORS = ["#2196f3", "#66bb6a", "#ffa726", "#ab47bc", "#ef5350", "#26c6da", "#ff7043"]

TIMEFRAMES = {"Daily": "D", "Weekly": "W", "Monthly": "ME"}


# ── Data loading ─────────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def load_tickers() -> list[str]:
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        df = con.execute(
            "SELECT DISTINCT ticker FROM t3_sepa_features ORDER BY ticker"
        ).fetchdf()
        return df["ticker"].tolist()
    finally:
        con.close()


@st.cache_data(ttl=300)
def load_watchlist_tickers() -> pd.DataFrame:
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        return con.execute("""
            SELECT ticker, company_name, sector, entry_date, status, pct_return
            FROM screener_watchlist
            ORDER BY entry_date DESC, ticker
        """).fetchdf()
    finally:
        con.close()


@st.cache_data(ttl=300)
def load_ticker_data(ticker: str, columns: list[str]) -> pd.DataFrame:
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        base = ["date", "open", "high", "low", "close", "volume"]
        all_cols = list(dict.fromkeys(base + columns))
        col_str = ", ".join(all_cols)
        df = con.execute(f"""
            SELECT {col_str}
            FROM t3_sepa_features
            WHERE ticker = ? AND feature_version = 'v3.1'
            ORDER BY date
        """, [ticker]).fetchdf()
        df["date"] = pd.to_datetime(df["date"])
        return df
    finally:
        con.close()


@st.cache_data(ttl=300)
def load_trade_entries(ticker: str) -> pd.DataFrame:
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        return con.execute("""
            SELECT entry_date, entry_price, exit_date, status, pct_return
            FROM screener_watchlist
            WHERE ticker = ?
            ORDER BY entry_date
        """, [ticker]).fetchdf()
    finally:
        con.close()


def get_available_columns(ticker: str) -> list[str]:
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        row = con.execute(
            "SELECT * FROM t3_sepa_features WHERE ticker = ? LIMIT 1", [ticker]
        ).fetchdf()
        return row.columns.tolist() if not row.empty else []
    finally:
        con.close()


# ── Resampling ───────────────────────────────────────────────────────────────

def resample_ohlcv(df: pd.DataFrame, freq: str, feature_cols: list[str]) -> pd.DataFrame:
    if freq == "D":
        return df

    df = df.set_index("date")

    ohlcv = df[["open", "high", "low", "close", "volume"]].resample(freq).agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
    }).dropna(subset=["open"])

    # Features: take last value per period (point-in-time snapshot)
    available = [c for c in feature_cols if c in df.columns]
    if available:
        feat = df[available].resample(freq).last()
        ohlcv = ohlcv.join(feat)

    return ohlcv.reset_index()


# ── Chart ────────────────────────────────────────────────────────────────────

def build_chart(
    df: pd.DataFrame, ticker: str, features: list[str],
    trades: pd.DataFrame, timeframe: str,
) -> go.Figure:
    overlay = [f for f in features if f in PRICE_OVERLAY_FEATURES and f in df.columns]
    panel_feats = [f for f in features if f not in PRICE_OVERLAY_FEATURES and f in df.columns]

    # Layout: price (large) + volume (small) + one row per feature panel
    n_rows = 2 + len(panel_feats)  # price, volume, panels...
    row_heights = [5, 1.5] + [2] * len(panel_feats)
    subplot_titles = ["", "Volume"] + panel_feats

    fig = make_subplots(
        rows=n_rows, cols=1, shared_xaxes=True,
        vertical_spacing=0.02,
        row_heights=row_heights,
        subplot_titles=subplot_titles,
    )

    # ── Price candlestick ────────────────────────────────────────────────
    green = "#26a69a"
    red = "#ef5350"

    fig.add_trace(
        go.Candlestick(
            x=df["date"], open=df["open"], high=df["high"],
            low=df["low"], close=df["close"], name="Price",
            increasing=dict(line=dict(color=green), fillcolor=green),
            decreasing=dict(line=dict(color=red), fillcolor=red),
        ),
        row=1, col=1,
    )

    # ── Price overlays (MAs, 52w levels) ─────────────────────────────────
    for feat in overlay:
        color = MA_COLORS.get(feat, "#888888")
        dash = "dot" if feat in ("high_52w", "low_52w") else "solid"
        fig.add_trace(
            go.Scatter(
                x=df["date"], y=df[feat], name=feat, mode="lines",
                line=dict(width=1.2, color=color, dash=dash),
            ),
            row=1, col=1,
        )

    # ── Trade markers ────────────────────────────────────────────────────
    if not trades.empty:
        entries = trades[["entry_date", "entry_price"]].dropna()
        if not entries.empty:
            fig.add_trace(
                go.Scatter(
                    x=entries["entry_date"], y=entries["entry_price"],
                    mode="markers", name="Entry",
                    marker=dict(symbol="triangle-up", size=11, color="#00e676",
                                line=dict(width=1, color="#1b5e20")),
                ),
                row=1, col=1,
            )

        exited = trades[trades["exit_date"].notna()].copy()
        if not exited.empty:
            # Look up exit price from OHLCV data
            exit_prices = []
            for _, t in exited.iterrows():
                match = df[df["date"] == pd.Timestamp(t["exit_date"])]
                exit_prices.append(match["close"].iloc[0] if not match.empty else np.nan)
            exited = exited.copy()
            exited["exit_price_chart"] = exit_prices
            exited = exited.dropna(subset=["exit_price_chart"])
            if not exited.empty:
                colors = ["#00e676" if r >= 0 else "#ff1744" for r in exited["pct_return"]]
                fig.add_trace(
                    go.Scatter(
                        x=exited["exit_date"], y=exited["exit_price_chart"],
                        mode="markers", name="Exit",
                        marker=dict(symbol="triangle-down", size=11, color=colors,
                                    line=dict(width=1, color="#424242")),
                    ),
                    row=1, col=1,
                )

    # ── Volume bars ──────────────────────────────────────────────────────
    vol_colors = [green if c >= o else red for c, o in zip(df["close"], df["open"])]
    fig.add_trace(
        go.Bar(
            x=df["date"], y=df["volume"], name="Volume",
            marker_color=vol_colors, opacity=0.6, showlegend=False,
        ),
        row=2, col=1,
    )

    # ── Feature panels ───────────────────────────────────────────────────
    for i, feat in enumerate(panel_feats):
        color = PANEL_COLORS[i % len(PANEL_COLORS)]

        # Area fill for bounded indicators (0-100 range)
        is_bounded = feat in ("rsi_14", "green_days_ratio_20d", "m03_score",
                              "m03_pillar_trend", "m03_pillar_liq", "m03_pillar_risk")
        fill = "tozeroy" if is_bounded else None
        opacity = 0.15 if is_bounded else None

        fig.add_trace(
            go.Scatter(
                x=df["date"], y=df[feat], name=feat, mode="lines",
                line=dict(width=1.5, color=color),
                fill=fill,
                fillcolor=f"rgba({int(color[1:3],16)},{int(color[3:5],16)},{int(color[5:7],16)},{opacity})" if fill else None,
            ),
            row=i + 3, col=1,
        )

        # Reference lines for bounded indicators
        if feat == "rsi_14":
            for lvl in (30, 70):
                fig.add_hline(y=lvl, line_dash="dot", line_color="#555",
                              line_width=0.8, row=i + 3, col=1)

    # ── Layout styling (TradingView-inspired) ────────────────────────────
    chart_height = 500 + 150 * len(panel_feats)

    fig.update_layout(
        height=chart_height,
        template="plotly_white",
        plot_bgcolor="#131722",
        paper_bgcolor="#131722",
        font=dict(color="#d1d4dc", size=11),
        legend=dict(
            orientation="h", yanchor="bottom", y=1.01, xanchor="left", x=0,
            bgcolor="rgba(0,0,0,0)", font=dict(size=10),
        ),
        margin=dict(l=60, r=20, t=30, b=30),
        xaxis_rangeslider_visible=False,
        hovermode="x unified",
    )

    # Style all axes
    axis_style = dict(
        gridcolor="#1e222d", zerolinecolor="#2a2e39",
        showgrid=True, gridwidth=0.5,
    )
    for i in range(1, n_rows + 1):
        yax = f"yaxis{i}" if i > 1 else "yaxis"
        xax = f"xaxis{i}" if i > 1 else "xaxis"
        fig.update_layout(**{
            yax: dict(**axis_style, tickfont=dict(size=10)),
            xax: dict(**axis_style, type="date"),
        })

    # Price y-axis on right side like TradingView
    fig.update_layout(yaxis=dict(side="right"))

    # Hide volume y-axis labels (not useful)
    fig.update_layout(yaxis2=dict(showticklabels=False))

    # Remove weekend gaps
    fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])

    # Title annotation
    fig.add_annotation(
        text=f"<b>{ticker}</b> — {timeframe}",
        xref="paper", yref="paper", x=0, y=1.06,
        showarrow=False, font=dict(size=14, color="#d1d4dc"),
    )

    return fig


# ── Page layout ──────────────────────────────────────────────────────────────

st.title("Feature Time Series")

# ── Ticker selection ─────────────────────────────────────────────────────
all_tickers = load_tickers()
watchlist = load_watchlist_tickers()

col_search, col_select, col_tf = st.columns([1, 2, 1])
with col_search:
    ticker_search = st.text_input(
        "Search Ticker", "", placeholder="e.g. ROST",
        key="ts_ticker_search",
    ).strip().upper()

if ticker_search:
    filtered_tickers = [t for t in all_tickers if ticker_search in t]
    filtered_watchlist = watchlist[
        watchlist["ticker"].str.contains(ticker_search, case=False, na=False)
    ]
else:
    filtered_tickers = all_tickers
    filtered_watchlist = watchlist

with col_select:
    if filtered_tickers:
        ticker = st.selectbox("Select Ticker", filtered_tickers, index=0)
    else:
        st.warning(f"No tickers match '{ticker_search}'")
        st.stop()

with col_tf:
    timeframe = st.selectbox("Timeframe", list(TIMEFRAMES.keys()), index=0)

# Watchlist context
if not filtered_watchlist.empty:
    with st.expander(f"Watchlist entries ({len(filtered_watchlist)})", expanded=False):
        st.dataframe(
            filtered_watchlist, use_container_width=True,
            height=min(200, 35 + 35 * len(filtered_watchlist)),
            hide_index=True,
        )

# ── Feature selection ────────────────────────────────────────────────────
available_cols = get_available_columns(ticker)

col_group, col_feat = st.columns([1, 3])
with col_group:
    group = st.selectbox("Feature Group", list(FEATURE_GROUPS.keys()))

group_features = [f for f in FEATURE_GROUPS[group] if f in available_cols]
with col_feat:
    selected = st.multiselect(
        "Features to Plot", group_features,
        default=group_features[:2] if group_features else [],
    )

if not selected:
    st.info("Select at least one feature to plot.")
    st.stop()

# ── Load, resample, plot ─────────────────────────────────────────────────
df = load_ticker_data(ticker, selected)
trades = load_trade_entries(ticker)

if df.empty:
    st.warning(f"No data found for {ticker} in t3_sepa_features.")
    st.stop()

freq = TIMEFRAMES[timeframe]
df_plot = resample_ohlcv(df, freq, selected)

st.caption(f"{len(df_plot)} bars  |  {df_plot['date'].min().date()} to {df_plot['date'].max().date()}")

fig = build_chart(df_plot, ticker, selected, trades, timeframe)
st.plotly_chart(fig, use_container_width=True, config={
    "scrollZoom": True,
    "displayModeBar": True,
    "modeBarButtonsToAdd": ["drawline", "drawrect"],
    "modeBarButtonsToRemove": ["lasso2d", "select2d"],
})

# ── Raw data ─────────────────────────────────────────────────────────────
with st.expander("Raw Data"):
    st.dataframe(df_plot, use_container_width=True, height=300)
