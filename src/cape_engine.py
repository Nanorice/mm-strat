"""CAPE Engine — self-computed aggregate market CAPE, written to macro_data as CAPE_OURS.

Shiller's own workbook is dormant (last update 2024-09) and FRED has no S&P EPS series, so
the valuation pillar can't stay sourced from Yale. This computes a live CAPE-equivalent from
data we already ingest nightly (price, shares, fundamentals) + FRED CPI.

Method (validated in scripts/validate_own_cape.py — level corr 0.871, rank corr 0.874 vs
true Shiller CAPE over the 2012-2024 overlap; winsorize re-confirmed 2026-07-04, see
CAP_WINSOR comment):
  aggregate CAPE = winsorized cap-weighted mean of per-ticker real-P/E10
  where P/E10_i = real_marketcap_i / mean(10yr trailing real TTM net_income_i)
  (impossible caps masked by an absolute ceiling before weighting — dirt guard only)

CAVEAT — survivorship: the basket is FIXED to current deep-earnings survivors, so historical
values carry a survivorship lift (our level runs ~1.28x Shiller). This is accepted by design:
the dashboard ranks the pillar against its OWN history, and the same fixed basket every month
means the same bias every month, so the timing/percentile signal stays internally consistent.
It is NOT an official S&P 500 CAPE and must not be fed to any model/backtest — display only.
"""
import logging
import pandas as pd
import numpy as np
from pathlib import Path

import sys
sys.path.append(str(Path(__file__).parent.parent))
import config
from src import db

logger = logging.getLogger(__name__)

SYMBOL = "CAPE_OURS"
MIN_QUARTERS = 60          # basket: >=60 quarters (15yr) of net_income
MIN_NAMES = 100            # skip months with too thin a cross-section
E10_WINDOW = 120           # 10yr trailing mean (monthly)
# Dirt guard: mask impossible caps before any weighting. Caps are clean at source now
# (T1 cleanup + engine clamps + Phase 1.6 gate); this is the residual belt-and-suspenders.
CAP_CEILING = config.T1_PLAUSIBILITY_BOUNDS['implied_cap_max']
# Weight cap, NOT a dirt filter (re-evaluated 2026-07-04 with clean caps): removing the
# winsorize flattens the drift vs Shiller (+0.022 -> +0.004/yr) but COLLAPSES tracking
# (level corr 0.871 -> 0.514, rank corr 0.874 -> 0.416) because it silently limits mega-cap
# concentration. The percentile gauge lives on rank corr, so the winsorize stays — now
# deliberately, as a concentration cap operating on already-clean caps.
CAP_WINSOR = 0.99
PE_CLIP = 500.0            # drop absurd per-ticker P/E10 (near-zero-earnings dirt)


class CapeEngine:
    def __init__(self, db_path: str = None, *, min_quarters: int = MIN_QUARTERS,
                 min_names: int = MIN_NAMES, e10_window: int = E10_WINDOW,
                 start_month: str = '2003-01-01'):
        # params are overridable so a unit test can shrink the basket/window to a
        # tiny hand-computable panel; defaults are the production values.
        self.db_path = db_path or str(config.DUCKDB_PATH)
        self.min_quarters = min_quarters
        self.min_names = min_names
        self.e10_window = e10_window
        self.start_month = start_month

    def _fetch_cpi(self) -> pd.Series:
        """Monthly CPIAUCSL from macro_data (mirrored there by MacroEngine) or FRED fallback."""
        with db.connect(self.db_path, read_only=True) as conn:
            df = conn.execute(
                "SELECT date, close FROM macro_data WHERE symbol='CPIAUCSL' ORDER BY date"
            ).fetchdf()
        if not df.empty:
            s = df.set_index(pd.to_datetime(df['date']))['close']
            s.index = s.index.to_period('M').to_timestamp()
            return s
        # fallback: FRED direct (CPI isn't in our FRED_SERIES set today)
        import requests
        r = requests.get(
            "https://api.stlouisfed.org/fred/series/observations",
            params={'series_id': 'CPIAUCSL', 'api_key': config.FRED_API_KEY,
                    'file_type': 'json', 'observation_start': '1990-01-01'}, timeout=30)
        obs = [o for o in r.json()['observations'] if o['value'] != '.']
        s = pd.Series({pd.Timestamp(o['date']): float(o['value']) for o in obs}).sort_index()
        s.index = s.index.to_period('M').to_timestamp()
        return s

    def compute(self) -> pd.Series:
        """Compute the monthly CAPE_OURS series. Returns a Series indexed by month-start date."""
        with db.connect(self.db_path, read_only=True) as conn:
            basket = conn.execute(f"""
                WITH deep AS (
                  SELECT ticker, COUNT(DISTINCT date_trunc('quarter', period_end)) q,
                         MAX(period_end) mx
                  FROM fundamentals
                  WHERE net_income IS NOT NULL AND period_type='quarterly'
                  GROUP BY ticker
                )
                SELECT ticker FROM deep WHERE q >= {self.min_quarters} AND mx >= (
                    SELECT MAX(period_end) - INTERVAL 18 MONTH FROM fundamentals
                )
            """).fetchdf()['ticker'].tolist()
            if len(basket) < self.min_names:
                raise ValueError(f"CAPE basket too small: {len(basket)} (<{self.min_names})")
            ph = ','.join(['?'] * len(basket))

            ni = conn.execute(f"""
                SELECT ticker, date_trunc('quarter', period_end) AS q, net_income
                FROM (
                  SELECT ticker, period_end, filing_date, net_income,
                         row_number() OVER (PARTITION BY ticker, date_trunc('quarter', period_end)
                                            ORDER BY period_end DESC, filing_date DESC) rn
                  FROM fundamentals
                  WHERE period_type='quarterly' AND net_income IS NOT NULL AND ticker IN ({ph})
                ) WHERE rn = 1
            """, basket).fetchdf()

            cap = conn.execute(f"""
                WITH px AS (SELECT ticker, date_trunc('month', date) m, last(close ORDER BY date) AS c
                            FROM price_data WHERE ticker IN ({ph}) AND date>=DATE '2002-01-01'
                            GROUP BY ticker, date_trunc('month', date)),
                     sh AS (SELECT ticker, date_trunc('month', date) m,
                                   last(shares_outstanding ORDER BY date) AS s
                            FROM shares_history WHERE ticker IN ({ph}) AND date>=DATE '2002-01-01'
                            GROUP BY ticker, date_trunc('month', date))
                SELECT px.ticker, px.m, px.c, sh.s FROM px LEFT JOIN sh USING (ticker, m)
            """, basket + basket).fetchdf()

        cpi = self._fetch_cpi()
        cpi_latest = cpi.iloc[-1]

        # per-ticker TTM net income (rolling 4 quarters), then monthly ffill
        ni['q'] = pd.to_datetime(ni['q'])
        ni = ni.sort_values(['ticker', 'q'])
        ni['ttm'] = ni.groupby('ticker')['net_income'].rolling(4, min_periods=4).sum().reset_index(0, drop=True)
        ni = ni.dropna(subset=['ttm'])

        cap['m'] = pd.to_datetime(cap['m'])
        cap = cap.sort_values(['ticker', 'm'])
        cap['s'] = cap.groupby('ticker')['s'].ffill()
        cap = cap.dropna(subset=['s'])
        cap['mktcap'] = cap['c'] * cap['s']

        midx = pd.date_range(self.start_month, cap['m'].max(), freq='MS')
        cpi_m = cpi.reindex(midx).ffill()

        # 10yr real E10 panel (months x tickers)
        e10_cols = []
        for tkr, g in ni.groupby('ticker'):
            s = g.set_index('q')['ttm'].reindex(midx).ffill()
            real = s * (cpi_latest / cpi_m)
            e10_cols.append(real.rolling(self.e10_window, min_periods=self.e10_window).mean().rename(tkr))
        e10_panel = pd.concat(e10_cols, axis=1)

        cap_real = (cap.pivot_table(index='m', columns='ticker', values='mktcap')
                    .reindex(midx).mul(cpi_latest / cpi_m, axis=0))
        # mask (don't clip) impossible caps: a dirty cap must not participate at any weight
        cap_real = cap_real.where(cap_real <= CAP_CEILING)

        common = e10_panel.columns.intersection(cap_real.columns)
        e10_panel, cap_real = e10_panel[common], cap_real[common]
        valid = e10_panel.notna() & cap_real.notna() & (e10_panel > 0)
        pe = (cap_real / e10_panel).where(valid & ((cap_real / e10_panel) < PE_CLIP))
        cap_w = cap_real.where(pe.notna())
        cap_w = cap_w.clip(upper=cap_w.quantile(CAP_WINSOR, axis=1), axis=0)  # concentration cap
        cape = (pe * cap_w).sum(axis=1) / cap_w.sum(axis=1)
        n_names = valid.sum(axis=1)
        # need a real cross-section; cap the floor by basket size so small test panels work
        floor = min(self.min_names, valid.shape[1])
        cape = cape[n_names >= floor].dropna().rename(SYMBOL)
        logger.info(f"Computed {len(cape)} CAPE_OURS months, latest {cape.index[-1].date()} = {cape.iloc[-1]:.1f}")
        return cape

    def update(self) -> int:
        """Compute and upsert CAPE_OURS into macro_data. Returns rows written.

        Uses INSERT OR REPLACE (not IGNORE): the trailing months recompute as new prices /
        earnings arrive, so existing recent rows must be overwritten, not skipped.
        """
        cape = self.compute()
        feed = pd.DataFrame({
            'date': pd.to_datetime(cape.index).date,
            'symbol': SYMBOL,
            'close': cape.values,
        })
        with db.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS macro_data (
                    date DATE NOT NULL, symbol VARCHAR NOT NULL, close DOUBLE,
                    volume UBIGINT, value DOUBLE, unit VARCHAR,
                    PRIMARY KEY (date, symbol)
                )
            """)
            conn.register('cape_feed', feed)
            conn.execute("""
                INSERT OR REPLACE INTO macro_data (date, symbol, close)
                SELECT date, symbol, close FROM cape_feed
            """)
        logger.info(f"[macro_data] {SYMBOL}: upserted {len(feed)} rows")
        return len(feed)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    n = CapeEngine().update()
    print(f"CAPE_OURS: wrote {n} rows")
