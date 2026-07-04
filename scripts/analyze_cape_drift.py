"""Decompose the CAPE_OURS vs Shiller drift (ratio 1.28x 2012 -> 1.53x 2024). Read-only.

Reuse the engine's data load, rebuild aggregation with one factor toggled at a time, and
regress each variant's ratio-vs-Shiller on time to find which factor drives the drift.

FINDING (2026-07-04): the drift is METHODOLOGY + DATA QUALITY, NOT scope. Three stacked
mechanisms, in order of persistence:
  1. Dirty caps — 4 tickers (PCG/CNA/GPUS/CBT) with corrupt shares_outstanding show caps of
     thousands of TRILLIONS in 2012-2017. The 99th-pct winsorize accidentally masked them
     (while also clipping 90%+ of legit cap mass those years — that instability WAS ~80% of
     the apparent drift). Fix = absolute sanity ceiling (drop cap > $8T), not a percentile.
  2. E10 10yr-window ramp — 2012-2015 P/E10 is inflated because the trailing 10yr earnings
     window straddles the 2008-09 crash trough (low E10 -> high P/E10). A methodology
     transient that rolls off by ~2019.
  3. Mega-cap concentration — top-5 cap share 13% (2016) -> 27% (2024, AAPL $4T). Cap-
     weighting genuinely loads high-P/E mega-caps more over time. The persistent structural
     driver; once dirt+ramp are removed the post-2016 slope is +0.09/yr (worse, not better).
Scope (top-500 basket) DOUBLES the drift (+0.043/yr) -> not the cause.

Consequence: no single clean fix recovers Shiller-level tracking (level corr) AND kills the
drift — mechanism 3 is real market structure. The gauge ranks on percentile, where this is
immaterial. See docs/session_logs/sprint_13/cape_fred_proxy_findings.md.
"""
import sys; sys.path.insert(0, r'c:\Users\Hang\PycharmProjects\quantamental')
import numpy as np, pandas as pd
from src import db
from src.cape_engine import CapeEngine, MIN_QUARTERS

eng = CapeEngine()

# --- load the same raw panels the engine uses ---
with db.connect(eng.db_path, read_only=True) as conn:
    basket = conn.execute(f"""
        WITH deep AS (SELECT ticker, COUNT(DISTINCT date_trunc('quarter',period_end)) q,
                             MAX(period_end) mx FROM fundamentals
                      WHERE net_income IS NOT NULL AND period_type='quarterly' GROUP BY ticker)
        SELECT ticker FROM deep WHERE q >= {MIN_QUARTERS}
          AND mx >= (SELECT MAX(period_end) - INTERVAL 18 MONTH FROM fundamentals)
    """).fetchdf()['ticker'].tolist()
    ph = ','.join(['?']*len(basket))
    ni = conn.execute(f"""
        SELECT ticker, date_trunc('quarter',period_end) AS q, net_income FROM (
          SELECT ticker, period_end, filing_date, net_income,
                 row_number() OVER (PARTITION BY ticker, date_trunc('quarter',period_end)
                                    ORDER BY period_end DESC, filing_date DESC) rn
          FROM fundamentals WHERE period_type='quarterly' AND net_income IS NOT NULL
            AND ticker IN ({ph})) WHERE rn=1
    """, basket).fetchdf()
    cap = conn.execute(f"""
        WITH px AS (SELECT ticker, date_trunc('month',date) m, last(close ORDER BY date) AS c
                    FROM price_data WHERE ticker IN ({ph}) AND date>=DATE '2002-01-01'
                    GROUP BY ticker, date_trunc('month',date)),
             sh AS (SELECT ticker, date_trunc('month',date) m, last(shares_outstanding ORDER BY date) AS s
                    FROM shares_history WHERE ticker IN ({ph}) AND date>=DATE '2002-01-01'
                    GROUP BY ticker, date_trunc('month',date))
        SELECT px.ticker, px.m, px.c, sh.s FROM px LEFT JOIN sh USING (ticker,m)
    """, basket+basket).fetchdf()
    sh_cape = conn.execute("SELECT date, close FROM macro_data WHERE symbol='CAPE' ORDER BY date").fetchdf()

cpi = eng._fetch_cpi(); cpi_latest = cpi.iloc[-1]
ni['q'] = pd.to_datetime(ni['q']); ni = ni.sort_values(['ticker','q'])
ni['ttm'] = ni.groupby('ticker')['net_income'].rolling(4, min_periods=4).sum().reset_index(0, drop=True)
ni = ni.dropna(subset=['ttm'])
cap['m'] = pd.to_datetime(cap['m']); cap = cap.sort_values(['ticker','m'])
cap['s'] = cap.groupby('ticker')['s'].ffill(); cap = cap.dropna(subset=['s'])
cap['mktcap'] = cap['c']*cap['s']

midx = pd.date_range('2003-01-01', cap['m'].max(), freq='MS')
cpi_m = cpi.reindex(midx).ffill()

# real E10 panel (allow negatives — we filter per-variant)
e10 = pd.concat([
    (g.set_index('q')['ttm'].reindex(midx).ffill() * (cpi_latest/cpi_m))
        .rolling(120, min_periods=120).mean().rename(t)
    for t, g in ni.groupby('ticker')], axis=1)
capr = cap.pivot_table(index='m', columns='ticker', values='mktcap').reindex(midx).mul(cpi_latest/cpi_m, axis=0)
common = e10.columns.intersection(capr.columns); e10, capr = e10[common], capr[common]

sh_cape = sh_cape.set_index(pd.to_datetime(sh_cape['date']))['close']


def variant(scope_topN=None, winsorize=True, drop_losses=True, weight='cap'):
    E, C = e10.copy(), capr.copy()
    present = E.notna() & C.notna()
    # scope: keep only top-N by cap each month (S&P-500-like)
    if scope_topN:
        rank = C.where(present).rank(axis=1, ascending=False)
        present = present & (rank <= scope_topN)
    posE = present & (E > 0)
    if drop_losses:
        valid = posE
        pe = (C/E).where(valid & ((C/E) < 500))
        w = C.where(pe.notna())
        if winsorize:
            w = w.clip(upper=w.quantile(0.99, axis=1), axis=0)
        if weight == 'cap':
            cape = (pe*w).sum(axis=1)/w.sum(axis=1)
        else:  # equal weight
            cape = pe.mean(axis=1)
    else:
        # aggregate ratio-of-sums INCLUDING losses (Shiller-style): sum cap / sum E10
        Cv = C.where(present); Ev = E.where(present)
        if winsorize:
            Cv = Cv.clip(upper=Cv.quantile(0.99, axis=1), axis=0)
        cape = Cv.sum(axis=1)/Ev.sum(axis=1)
    n = present.sum(axis=1)
    return cape[n >= 100].dropna()


def drift(cape):
    df = pd.concat([cape.rename('o'), sh_cape.rename('s')], axis=1).dropna()
    if len(df) < 24: return None
    r = df.o/df.s
    t = np.arange(len(df))
    slope = np.polyfit(t, r.values, 1)[0]*12   # per year
    return dict(n=len(df), ratio0=r.iloc[:12].mean(), ratio1=r.iloc[-12:].mean(),
                slope_yr=slope, corr=df.o.corr(df.s))


configs = {
    'BASE (current engine)':      dict(),
    'scope: top-500 only':        dict(scope_topN=500),
    'no winsorize':               dict(winsorize=False),
    'keep losses (ratio-of-sums)':dict(drop_losses=False),
    'equal-weight':               dict(weight='equal'),
    'top-500 + keep losses':      dict(scope_topN=500, drop_losses=False),
    'top-500 + no winsorize':     dict(scope_topN=500, winsorize=False),
}
print(f"{'variant':<30}{'n':>4}{'ratio 2012':>11}{'ratio 2024':>11}{'slope/yr':>10}{'corr':>7}")
print('-'*73)
for name, kw in configs.items():
    d = drift(variant(**kw))
    if d:
        print(f"{name:<30}{d['n']:>4}{d['ratio0']:>11.2f}{d['ratio1']:>11.2f}{d['slope_yr']:>+10.4f}{d['corr']:>7.2f}")
print('\nInterpretation: the config whose slope/yr collapses toward 0 isolates the drift cause.')
