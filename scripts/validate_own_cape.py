"""Validate a self-computed aggregate CAPE against Shiller's true CAPE (read-only).

Aggregate = winsorized cap-weighted mean of per-ticker real-P/E10 over a deep-earnings
basket (~1808 tickers, >=60 quarters of net_income spanning 2005->2024). Both cap and
earnings deflated by FRED CPIAUCSL. Winsorizing caps at the monthly 99th pct is load-
bearing: a single dirty shares_outstanding row (PCG 2016 = 44 quadrillion cap) otherwise
dominates the sum. Median-of-ratios tracks *direction* but undershoots level (down-weights
mega-caps); winsorized cap-weight recovers both.

Result: level corr 0.886, 12m-change corr 0.853, percentile-rank corr 0.870 vs Shiller.
Offset is a stable ~1.28x (broader-than-SP500 basket); after that single recalibration,
mean APE 5.9% / max 20.6%. Latest value computable through the current month — the point:
this updates nightly forever, no dependence on Shiller's dormant workbook.

See docs/session_logs/sprint_13/cape_fred_proxy_findings.md.
"""
import sys; sys.path.insert(0, r'c:\Users\Hang\PycharmProjects\quantamental')
import duckdb, requests, config
import pandas as pd, numpy as np

def fred(sid, start='1990-01-01'):
    r = requests.get('https://api.stlouisfed.org/fred/series/observations',
        params={'series_id': sid, 'api_key': config.FRED_API_KEY,
                'file_type': 'json', 'observation_start': start}, timeout=30)
    obs = [o for o in r.json()['observations'] if o['value'] != '.']
    return pd.Series({pd.Timestamp(o['date']): float(o['value']) for o in obs}).sort_index()

con = duckdb.connect('data/market_data.duckdb', read_only=True)
basket = con.execute("""
    WITH deep AS (
      SELECT ticker, COUNT(DISTINCT date_trunc('quarter', period_end)) q,
             MIN(period_end) mn, MAX(period_end) mx
      FROM fundamentals WHERE net_income IS NOT NULL AND period_type='quarterly'
      GROUP BY ticker
    )
    SELECT ticker FROM deep WHERE mn <= DATE '2005-01-01' AND mx >= DATE '2024-06-01' AND q >= 60
""").fetchdf()['ticker'].tolist()
ph = ','.join(['?']*len(basket))
print(f'basket: {len(basket)}')

# quarterly NI, deduped to ONE row per calendar quarter (latest filing)
ni = con.execute(f"""
    SELECT ticker, date_trunc('quarter', period_end) AS q, net_income,
           row_number() OVER (PARTITION BY ticker, date_trunc('quarter', period_end)
                              ORDER BY period_end DESC, filing_date DESC) rn
    FROM fundamentals
    WHERE period_type='quarterly' AND net_income IS NOT NULL AND ticker IN ({ph})
""", basket).fetchdf()
ni = ni[ni.rn == 1].drop(columns='rn')

# monthly cap per ticker (ffill shares)
cap = con.execute(f"""
    WITH px AS (SELECT ticker, date_trunc('month', date) m, last(close ORDER BY date) AS c
                FROM price_data WHERE ticker IN ({ph}) AND date>=DATE '2002-01-01'
                GROUP BY ticker, date_trunc('month', date)),
         sh AS (SELECT ticker, date_trunc('month', date) m, last(shares_outstanding ORDER BY date) AS s
                FROM shares_history WHERE ticker IN ({ph}) AND date>=DATE '2002-01-01'
                GROUP BY ticker, date_trunc('month', date))
    SELECT px.ticker, px.m, px.c, sh.s FROM px LEFT JOIN sh USING (ticker, m)
""", basket + basket).fetchdf()
con.close()

cpi = fred('CPIAUCSL'); cpi.index = cpi.index.to_period('M').to_timestamp()
cpi_latest = cpi.iloc[-1]

# ---- per-ticker TTM real earnings, then 10yr trailing mean, monthly ----
ni['q'] = pd.to_datetime(ni['q'])
ni = ni.sort_values(['ticker','q'])
ni['ttm'] = ni.groupby('ticker')['net_income'].rolling(4, min_periods=4).sum().reset_index(0, drop=True)
ni = ni.dropna(subset=['ttm'])
ni['m'] = ni['q']  # quarter-start month

cap['m'] = pd.to_datetime(cap['m'])
cap = cap.sort_values(['ticker','m'])
cap['s'] = cap.groupby('ticker')['s'].ffill()
cap = cap.dropna(subset=['s'])
cap['mktcap'] = cap['c'] * cap['s']

# build monthly panel per ticker: forward-fill TTM into every month, deflate, 10yr mean
rows = []
midx = pd.date_range('2003-01-01', cap['m'].max(), freq='MS')
cpi_m = cpi.reindex(midx).ffill()
for tkr, g in ni.groupby('ticker'):
    s = g.set_index('m')['ttm'].reindex(midx).ffill()
    real = s * (cpi_latest / cpi_m)
    e10 = real.rolling(120, min_periods=120).mean()
    rows.append(e10.rename(tkr))
e10_panel = pd.concat(rows, axis=1)  # months x tickers, real 10yr avg earnings

# cap panel months x tickers
cap_panel = cap.pivot_table(index='m', columns='ticker', values='mktcap').reindex(midx)
cap_real = cap_panel.mul(cpi_latest / cpi_m, axis=0)

# Cap-weighted aggregate P/E10 (like Shiller — mega-caps dominate), but WINSORIZE caps
# each month so a single dirty shares_outstanding row (PCG 2016 = 44 quadrillion) can't
# dominate the sum. Clip each month's caps at the 99th pct; drop absurd per-ticker P/E.
common = e10_panel.columns.intersection(cap_real.columns)
e10_panel, cap_real = e10_panel[common], cap_real[common]
valid = e10_panel.notna() & cap_real.notna() & (e10_panel > 0)
pe = (cap_real / e10_panel).where(valid & ((cap_real/e10_panel) < 500))
cap_w = cap_real.where(pe.notna())
# winsorize caps at monthly 99th percentile (kills PCG-type dirt, keeps real mega-caps)
cap99 = cap_w.quantile(0.99, axis=1)
cap_w = cap_w.clip(upper=cap99, axis=0)
cape_ours = (pe * cap_w).sum(axis=1) / cap_w.sum(axis=1)
n_names = valid.sum(axis=1)
cape_ours = cape_ours[n_names >= 100].rename('CAPE_ours')

# ---- compare to Shiller ----
con = duckdb.connect('data/market_data.duckdb', read_only=True)
sh = con.execute("SELECT date, close FROM macro_data WHERE symbol='CAPE' ORDER BY date").fetchdf()
con.close()
sh = sh.set_index(pd.to_datetime(sh['date']))['close'].rename('CAPE_shiller')

df = pd.concat([cape_ours, sh], axis=1).dropna()
print(f'\noverlap {len(df)} mo ({df.index.min().date()}..{df.index.max().date()})  n_names last={int(n_names.iloc[-1])}')
print(f'level: ours {df.CAPE_ours.mean():.1f}  shiller {df.CAPE_shiller.mean():.1f}')
print(f'corr level: {df.CAPE_ours.corr(df.CAPE_shiller):.3f}   corr 12m-chg: {df.CAPE_ours.diff(12).corr(df.CAPE_shiller.diff(12)):.3f}')
r1,r2 = df.CAPE_ours.rank(pct=True), df.CAPE_shiller.rank(pct=True)
print(f'corr pct-rank: {r1.corr(r2):.3f}   mean|rank diff|: {(r1-r2).abs().mean()*100:.1f}pts')
print('\ntail:'); print(df.tail(6).round(1).to_string())
print(f'\nCAPE_ours latest: {cape_ours.index[-1].date()} = {cape_ours.iloc[-1]:.1f}  (live-updatable)')

# self-check: the whole point is that ours tracks Shiller. Fail loudly if it stops.
lvl = df.CAPE_ours.corr(df.CAPE_shiller)
rnk = r1.corr(r2)
assert lvl > 0.80, f'CAPE_ours level corr with Shiller degraded to {lvl:.2f} (<0.80) — check winsorize/basket'
assert rnk > 0.75, f'CAPE_ours percentile-rank corr degraded to {rnk:.2f} (<0.75)'
assert cape_ours.index[-1] > pd.Timestamp('2025-01-01'), 'CAPE_ours not computing to recent months'
print('\n[OK] tracking asserts pass')
