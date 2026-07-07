# m01_rank — Phase 2 Backtest Engine (paste-ready artifact)

**Created:** 2026-05-21
**Companion to:** `m01_rank_dense_grain_audit_2026_05_20.md`, `m01_rank_phase1_findings_2026_05_21.md`
**Implements:** Audit Phase 2 (2.1–2.4) under the dense-grain strategy
(User Decision 2026-05-20).
**Workflow:** no direct notebook edits — paste these cells in manually,
replacing the existing G6 cell (`vectorized_backtest_nonoverlap`).

---

## Why the old engine produced 28×

Phase 1 proved the signal is real, so the 28× is a **construction defect**, not
fake metrics. Three compounding bugs in the old `vectorized_backtest_nonoverlap`:

1. **Return source is the 20-day forward return.** `ret = r.fwd_return` books a
   full 20d move *per trade*, then the NAV spreads it back over the hold and
   compounds. On a dense panel the same SEPA episode generates a fresh
   `streak>=consec` entry on many days → the same 20-day move is harvested
   repeatedly across overlapping windows. This is the dominant inflator.
2. **Entry persistence conflated with hold duration.** `consec=3` gated entry,
   then the position was force-held `hold_days` regardless of whether the name
   stayed elite. That is not the strategy the audit specifies.
3. **No holdings-based daily P&L.** Returns were trade-grain, not
   "what did the book actually earn today," so cross-trade overlap was invisible.

The fix is a **holdings-based daily-rebalance engine**: decide *what you hold each
day*, then earn each held name's **realised next-day return**. A 20-day move can
then only be earned once, by holding across those 20 days.

---

## Cell 0 — exclude known-bad tickers (run ONCE, right after G0 load)

`detect_bad_tickers` in `src/evaluation/data_quality.py` only *flags* extreme-
return names as a warning — it does NOT drop them, and the project's hardcoded
`BAD_TICKERS` list is not wired into the loader. So names like LIF (a +2.7M× 1d
return from a near-zero denominator / ticker reuse) and CUE reach the backtest.
Excluding them at the source keeps `df`, `scored`, and BOTH return lookups
consistent. Paste immediately after the G0 `df = load_pretrain_data(...)` /
date-filter cell, before features are selected.

```python
BAD_TICKERS = {
    "LIF",  # +2.7M% 1d return (near-zero denominator / ticker reuse artifact)
    "CUE",  # bad 1d return 2026-04-24
}
_before = df["ticker"].nunique()
df = df[~df["ticker"].isin(BAD_TICKERS)].copy()
print(f"Dropped {len(BAD_TICKERS)} bad tickers; "
      f"{_before} -> {df['ticker'].nunique()} tickers")
```

The Cell A / Cell D return lookups below ALSO exclude these (they read
`price_data` directly, not `df`), so the same set is applied there.

---

## Cell A — daily next-day returns (prerequisite)

The engine needs realised **1-day** forward returns per (ticker, date).

**Do NOT derive this from `df` / `t3_sepa_features`.** That table is the dense
SEPA-candidate panel, which is *gappy*: `groupby("ticker")["close"].shift(-1)`
returns the close of the next day the ticker *reappears as a SEPA candidate*,
which can be weeks-to-years later (verified: 2,867 gaps >7d, max 8,795 days).
Each such gap books a multi-week move as a single "1-day" return — that is the
source of the vertical NAV jumps and the implausible 28× / 200% ann_return. It
is the same double-count as the old `fwd_return`, just relocated.

Source the next-day return from **`price_data`** (the continuous daily price
table: 356 gaps >7d, max 219d — genuine halts/delistings, not panel artifacts)
and only accept it when the next row is a genuine adjacent trading day. Paste as
a new cell **before** the backtest cell.

**CRITICAL (verified 2026-05-22):** `price_data.adj_close`, `adj_factor`, and
`vwap` are **100% NULL** in this DB — only `close` is populated. Use `close`.
(Consequence: returns are NOT split/dividend-adjusted, so a stock split shows as
a spurious ±large 1-day return. The adjacency guard does not catch splits; if the
sanity `max` below is implausibly large, a split leaked — acceptable for now, but
note it. Populating `adj_close` upstream is the proper fix, out of scope here.)

```python
import duckdb
from config import DUCKDB_PATH

# True next-trading-day return per (ticker, date) from the CONTINUOUS price panel.
# Uses `close` (adj_close is unpopulated — see note above).
# Guard: only keep ret_1d_fwd when the next row is within MAX_GAP_DAYS calendar
# days (a real adjacent session); otherwise NULL — a held name spanning a
# delisting/halt earns 0 that day, never a stale multi-week jump.
MAX_GAP_DAYS = 5
con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
_bad = "', '".join(sorted(BAD_TICKERS))
_px = con.execute(f"""
    WITH r AS (
        SELECT ticker, date, close,
               LEAD(close) OVER w AS nxt_close,
               LEAD(date)  OVER w AS nxt_date
        FROM price_data
        WHERE ticker NOT IN ('{_bad}')
        WINDOW w AS (PARTITION BY ticker ORDER BY date)
    )
    SELECT ticker, date,
           CASE WHEN datediff('day', date, nxt_date) <= ?
                THEN nxt_close / NULLIF(close, 0) - 1.0 END AS ret_1d_fwd
    FROM r
""", [MAX_GAP_DAYS]).df()
con.close()

_px["date"] = pd.to_datetime(_px["date"])

# Sanitize unadjusted-close artifacts. Since close is NOT split-adjusted, splits
# and bad prints produce impossible 1-day returns (verified: a +2.7M× outlier on
# LIF 2024-06-05; ~1,208 rows with |ret|>100% over the window). One such name in
# a top-K book fabricates the entire backtest. Drop |ret|>50% to NaN — a real
# single-session equity move rarely exceeds that, and the backtest treats NaN as
# 0/skip. This is a blunt guard; the proper fix is populating adj_close upstream.
RET_CLIP = 0.50
_n_bad = (_px["ret_1d_fwd"].abs() > RET_CLIP).sum()
_px.loc[_px["ret_1d_fwd"].abs() > RET_CLIP, "ret_1d_fwd"] = np.nan
ret1d_lookup = _px.set_index(["date", "ticker"])["ret_1d_fwd"]
print(f"ret_1d_fwd built from price_data: "
      f"{ret1d_lookup.notna().sum():,} non-null (ticker,date) pairs "
      f"({_n_bad:,} dropped as |ret|>{RET_CLIP:.0%} split/print artifacts)")
# Sanity: MUST be non-zero and tight. If non-null == 0, you used a NULL column.
# A max far above ~0.5 (50% in one session) means a split/gap leaked through.
print(f"  ret_1d_fwd  non_null={ret1d_lookup.notna().sum():,}  "
      f"min={ret1d_lookup.min():.3f}  median={ret1d_lookup.median():.4f}  "
      f"max={ret1d_lookup.max():.3f}")
assert ret1d_lookup.notna().sum() > 0, "ret_1d_fwd all NULL — wrong price column"
```

---

## Cell B — dense-grain holdings backtest (replaces G6 cell)

```python
def holdings_backtest(scored, ret1d_lookup, top_k=3, enter_persist=3,
                      exit_persist=3, rebalance="D", cost_bps=10):
    """Daily-rebalance-to-top-K with symmetric persistence (User Decision 2026-05-20).

    Eligibility (entry):  ticker is in the daily top-K for >= enter_persist
                          consecutive trading days.
    Exit:                 ticker has been OUT of the daily top-K for
                          >= exit_persist consecutive days (symmetric; Open Q1=(b)).
    rebalance:            "D" = re-evaluate the held set every day.
                          "W" = re-evaluate only on the first trading day of each
                                ISO week; hold the set fixed between rebalances.
    P&L:                  each held name earns its realised next-day return
                          (ret1d_lookup). Equal weight across top_k SLOTS; empty
                          slots hold cash (0). A 20d move is earned once, by
                          holding across the 20 days — no per-trade double-count.

    Returns (led_holdings_df, stats, nav_series).
    """
    s = scored.sort_values(["date", "ticker"]).copy()
    # Daily cross-sectional rank → membership of the top-K each day.
    s["rank"] = s.groupby("date")["prob"].rank(method="first", ascending=False)
    s["in_topk"] = s["rank"] <= top_k

    # Consecutive in / out streaks per ticker (over trading days the ticker appears).
    g = s.groupby("ticker", group_keys=False)
    s["in_streak"] = g["in_topk"].transform(
        lambda x: x.groupby((~x).cumsum()).cumsum())
    notin = ~s["in_topk"]
    s["out_streak"] = s.groupby("ticker", group_keys=False)["in_topk"].transform(
        lambda x: (~x).groupby(x.cumsum()).cumsum())

    dates = np.sort(s["date"].unique())
    # Weekly rebalance gate: only re-evaluate the held set on the first trading
    # day of each ISO week; otherwise carry yesterday's held set forward.
    if rebalance == "W":
        wk = pd.Series(dates).dt.isocalendar().week.values
        is_rebal_day = np.r_[True, wk[1:] != wk[:-1]]
    else:
        is_rebal_day = np.ones(len(dates), dtype=bool)

    by_date = {d: x.set_index("ticker") for d, x in s.groupby("date")}
    held = set()
    rows = []
    for di, d in enumerate(dates):
        day = by_date[d]
        prev_held = set(held)

        if is_rebal_day[di]:
            # Exit rules:
            #  (1) a held name that has left the dense panel entirely (no row
            #      today) is force-sold — it is no longer tradeable. Without
            #      this it would be stranded in `held` forever, freezing a slot
            #      and booking 0 daily return (the flat-NAV bug).
            #  (2) a held name still in the panel exits once it has been OUT of
            #      the top-K for >= exit_persist consecutive days.
            for tkr in list(held):
                if tkr not in day.index:
                    held.discard(tkr)
                elif day.at[tkr, "out_streak"] >= exit_persist:
                    held.discard(tkr)
            # Add eligible names (entry persistence met), best prob first,
            # until top_k slots are full.
            cands = (day[(day["in_streak"] >= enter_persist)]
                     .sort_values("prob", ascending=False))
            for tkr in cands.index:
                if len(held) >= top_k:
                    break
                held.add(tkr)
        # else: carry prev held set unchanged (weekly hold)

        # Turnover cost: charge cost_bps on each side of every name that
        # entered or left the book today.
        turnover = len(held ^ prev_held)
        cost = turnover * cost_bps / 1e4

        # Today's P&L: each held name earns its realised next-day return.
        if held:
            legs = [ret1d_lookup.get((d, tkr), 0.0) for tkr in held]
            gross = float(np.nansum(legs)) / top_k        # empty slots = cash
        else:
            gross = 0.0
        rows.append({"date": d, "n_held": len(held),
                     "port_ret": gross - cost / top_k})

    led = pd.DataFrame(rows).set_index("date")
    if led.empty or led["port_ret"].std() == 0:
        return led, {"n_days": len(led), "nav_sharpe": 0.0}, None

    nav = (1 + led["port_ret"]).cumprod()
    sharpe = float(led["port_ret"].mean() / led["port_ret"].std() * np.sqrt(252))
    ann = (1 + led["port_ret"].mean()) ** 252 - 1
    return led, {
        "n_days": int(len(led)),
        "avg_n_held": float(led["n_held"].mean()),
        "ann_return": float(ann),
        "total_ret_nav": float(nav.iloc[-1] - 1),
        "nav_sharpe": sharpe,
        "max_dd": float((nav / nav.cummax() - 1).min()),
    }, nav

# Scored panel for the validation window — prob + daily membership inputs only.
# NOTE: no fwd_return column needed; P&L comes from ret1d_lookup.
scored = df_valid[["date", "ticker"]].copy()
scored["prob"] = p_valid

# Sweep top_k and rebalance cadence (daily vs weekly), persistence fixed at 3.
sweep_rows, sample_nav = [], None
for rb in ["D", "W"]:
    for tk in [2, 3, 5]:
        _, st, nav = holdings_backtest(
            scored, ret1d_lookup, top_k=tk, enter_persist=3,
            exit_persist=3, rebalance=rb, cost_bps=10,
        )
        sweep_rows.append({"rebalance": rb, "top_k": tk, **st})
        if rb == "D" and tk == 3:
            sample_nav = nav
sweep = pd.DataFrame(sweep_rows)
display(sweep)

if sample_nav is not None:
    plt.figure(figsize=(10, 4))
    plt.plot(sample_nav.index, sample_nav.values)
    plt.title("Portfolio NAV — daily rebalance, top_k=3, persist=3 (validation)")
    plt.ylabel("NAV (start=1.0)"); plt.grid(alpha=0.3); plt.show()

# G6 gate — a REGION of cells must clear, not one cell.
ok = sweep[(sweep["ann_return"] > 0) & (sweep["nav_sharpe"] > 1.0)]
print(f"\nG6 gate: {len(ok)} / {len(sweep)} cells beat (ann_return>0, nav_sharpe>1)")
assert len(ok) >= 3, "G6 failed — no robust parameter region"
```

### Reading the NAV SHAPE, not just the level (critical)

A **flat plateau with a single vertical jump** (as seen in the first run:
1.2→3.0 in one step, then flat for ~7 months) is a FAILURE signature even if
`total_ret_nav` looks plausible (~2×) and the G6 gate passes 6/6. Flat NAV =
zero daily turnover and zero daily P&L = the book is frozen. Root cause that the
v2 exit fix above addresses: a held name that **drops out of the dense SEPA
panel** was never evaluated for exit, so it was stranded in `held` forever,
freezing a slot and booking `ret1d_lookup.get(...)=0.0` every day. The one big
jump is one or two names' multi-day run while the rest of the book sat dead.

After the fix, re-run and confirm the curve is **continuously varying** (visible
daily wiggle), not a step function. Add this diagnostic to verify turnover is
alive:

```python
led_d, _, _ = holdings_backtest(scored, ret1d_lookup, top_k=3,
                                enter_persist=3, exit_persist=3, rebalance="D")
print("days with zero port_ret:", int((led_d['port_ret'] == 0).sum()), "/", len(led_d))
print("median daily n_held:", led_d['n_held'].median())
# Healthy: very few exact-zero days; n_held near top_k throughout.
```

### What to expect / sanity bounds

- `total_ret_nav` should now be in the **single-digit-x at most** over a ~1y
  validation window, NOT 28×. If it's still huge, the 20d return is leaking in
  somewhere — re-check that P&L uses `ret1d_lookup`, never `fwd_return`.
- **Curve shape > final level.** A smoothly rising/varying NAV is the pass; a
  flat-with-a-spike curve is a fail regardless of the endpoint (see above).
- `nav_sharpe` 1.0–2.5 = plausible edge. **Sharpe > 4 → investigate**, do not
  celebrate (insufficient sample or residual leak).
- Daily vs weekly: weekly should show **lower turnover** (fewer entries/exits in
  the cost term) and similar/slightly-lower return. If weekly massively
  outperforms daily, the daily version is being whipsawed by score flicker —
  raise `exit_persist`.
- `avg_n_held` should sit near `top_k`. Much lower means the persistence filter
  is starving the book of eligible names; consider `enter_persist=2`.

---

## Cell C — leakage stress tests (2.4)

Paste after Cell B. Both must behave as described or G6 is not trustworthy.

```python
# (1) Shuffled-target control — destroy the prob→return link; Sharpe must collapse to ~0.
rng = np.random.default_rng(0)
scored_shuf = scored.copy()
scored_shuf["prob"] = rng.permutation(scored_shuf["prob"].values)
_, st_shuf, _ = holdings_backtest(scored_shuf, ret1d_lookup, top_k=3,
                                  enter_persist=3, exit_persist=3, rebalance="D")
print(f"Shuffled-prob nav_sharpe: {st_shuf['nav_sharpe']:.2f}  (expect ~0, |.|<0.5)")
assert abs(st_shuf["nav_sharpe"]) < 0.5, "LEAK: shuffled prob still profitable"

# (2) Lagged-feature control — score on features shifted +5d per ticker.
# AUC/edge should drop modestly but stay positive (signal is slow, not instantaneous).
#
# Build Xlag by MUTATING A COPY OF X_valid IN PLACE, never rebuilding it. X_valid
# already has the exact dtypes the model was fit on (it scored fine in the refit
# cell). We only overwrite the *values* of numeric columns with their +5d-shifted
# version, column by column via .values — this preserves each column's dtype
# object and leaves categorical/bool columns completely untouched. The earlier
# frame-level assignment (Xlag[NUM_COLS] = ...) was what collapsed a bool column
# into a scalar numpy.bool that XGBoost rejected with "has no len()".
NUM_COLS = list(X_valid.select_dtypes(include=[np.number]).columns)
Xlag = X_valid.copy()
g = df_valid.groupby("ticker")
for c in NUM_COLS:
    shifted = g[c].shift(5)
    Xlag[c] = shifted.where(shifted.notna(), X_valid[c]).astype(X_valid[c].dtype).values
# Sanity: dtypes must match X_valid exactly before scoring.
assert (Xlag.dtypes == X_valid.dtypes).all(), \
    f"dtype drift: {Xlag.dtypes[Xlag.dtypes != X_valid.dtypes]}"
p_lag = model.predict_proba(Xlag)[:, 1]
scored_lag = scored.copy(); scored_lag["prob"] = p_lag
_, st_lag, _ = holdings_backtest(scored_lag, ret1d_lookup, top_k=3,
                                 enter_persist=3, exit_persist=3, rebalance="D")
print(f"5d-lagged nav_sharpe: {st_lag['nav_sharpe']:.2f}  "
      f"(expect close to live D/top_k=3 sharpe; signal is slow so lag barely hurts)")
```

---

## Cell D — horizon-mismatch diagnostic (why daily P&L went negative)

**Finding (2026-05-22 run):** with the gappy-return leak removed, daily-rebalance
top-K is NEGATIVE (−2.4% to −3.7%, Sharpe ~−6 to −11) and the shuffle control
kills Sharpe to 0.00 → the loss is **signal-driven, not noise**. The top-K names
systematically underperform *next-day*.

**Hypothesis:** the model predicts a **20-day** forward home-run. High-`prob`
names are extended/overbought on the signal day, so they tend to pull back
*short-term* before continuing. Harvesting a 20-day edge one day at a time buys
the local top every day. The edge may be real at the horizon it was trained on.

**Test:** hold each entered name for the **full 20 days** and book its realized
20d return ONCE — with strict non-overlap (no re-entry while a position is open),
so we do NOT recreate the original double-count. Returns from `price_data`,
guarded over the 20d window.

```python
import duckdb
from config import DUCKDB_PATH

# Realized H-day forward return per (ticker, date) from the CONTINUOUS price
# panel, guarded: the H-th-ahead row must be within ~1.5*H calendar days (a real
# 20-trading-day span, not a jump across an active-universe hole). adj_close.
# Uses `close` (adj_close is unpopulated). Guard: the H-th-ahead row must be
# within ~1.6*H calendar days (20 trading rows span ~29 cal days median, up to
# ~77 across light gaps — so the guard must be generous or it nukes everything).
H = HORIZON  # 20, from G0
con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
_bad = "', '".join(sorted(BAD_TICKERS))
_pxH = con.execute(f"""
    WITH r AS (
        SELECT ticker, date, close,
               LEAD(close, ?) OVER w AS fwd_close,
               LEAD(date, ?)  OVER w AS fwd_date
        FROM price_data
        WHERE ticker NOT IN ('{_bad}')
        WINDOW w AS (PARTITION BY ticker ORDER BY date)
    )
    SELECT ticker, date,
           CASE WHEN datediff('day', date, fwd_date) <= ?
                THEN fwd_close / NULLIF(close, 0) - 1.0 END AS retH_fwd
    FROM r
""", [H, H, int(H * 2.5)]).df()  # ~50 cal days: covers the 77-day tail
con.close()
_pxH["date"] = pd.to_datetime(_pxH["date"])
# Sanitize split/print artifacts (see Cell A note). A 20d move can legitimately
# be large, so clip wider than the 1d guard — but a >300% 20d move on unadjusted
# close is almost always a split, and at ~36 trades ONE such name dominates
# avg_trade_ret (the 10% mean vs 0.94% median gap is exactly this fingerprint).
RETH_CLIP = 3.0
_nb = (_pxH["retH_fwd"].abs() > RETH_CLIP).sum()
_pxH.loc[_pxH["retH_fwd"].abs() > RETH_CLIP, "retH_fwd"] = np.nan
retH_lookup = _pxH.set_index(["date", "ticker"])["retH_fwd"]
print(f"retH_fwd (H={H}) non-null: {retH_lookup.notna().sum():,} "
      f"({_nb:,} dropped as |ret|>{RETH_CLIP:.0%} split artifacts)")
assert retH_lookup.notna().sum() > 0, "retH_fwd all NULL — wrong price column or guard too tight"

def nonoverlap_holds(scored, retH_lookup, hold_days=H, top_k=3,
                     enter_persist=3, cost_bps=10):
    """Per-trade, NON-OVERLAPPING: when a name enters the top_k with entry
    persistence met, book its realized hold_days return once and lock that
    slot/ticker until the hold expires. Each H-day move counted exactly once."""
    s = scored.sort_values(["date", "ticker"]).copy()
    s["rank"] = s.groupby("date")["prob"].rank(method="first", ascending=False)
    s["in_topk"] = s["rank"] <= top_k
    s["in_streak"] = s.groupby("ticker", group_keys=False)["in_topk"].transform(
        lambda x: x.groupby((~x).cumsum()).cumsum())
    elig = s[(s["in_topk"]) & (s["in_streak"] >= enter_persist)]

    open_until, trades = {}, []
    for d, day in elig.groupby("date"):
        n_open = sum(1 for t in open_until.values() if t >= d)
        for tkr in day.sort_values("prob", ascending=False)["ticker"]:
            if n_open >= top_k:
                break
            if open_until.get(tkr, pd.Timestamp.min) >= d:
                continue
            r = retH_lookup.get((d, tkr), np.nan)
            if pd.isna(r):
                continue
            trades.append({"date": d, "ticker": tkr, "ret": r - 2 * cost_bps / 1e4})
            open_until[tkr] = d + pd.offsets.BDay(hold_days)
            n_open += 1
    led = pd.DataFrame(trades)
    if led.empty:
        return led, {"n_trades": 0}
    return led, {
        "n_trades": len(led),
        "avg_trade_ret": float(led["ret"].mean()),
        "median_ret": float(led["ret"].median()),
        "win_rate": float((led["ret"] > 0).mean()),
        # Annualize off the MEDIAN, not the mean — robust to the few remaining
        # fat-tail winners that survive the clip. Mean-based ann_per_slot is
        # reported too but treated as optimistic.
        "ann_per_slot_median": float((1 + led["ret"].median()) ** (252 / hold_days) - 1),
        "ann_per_slot_mean": float((1 + led["ret"].mean()) ** (252 / hold_days) - 1),
    }

led_h, st_h = nonoverlap_holds(scored, retH_lookup, top_k=3)
print(st_h)
print(f"  trade-ret quantiles: "
      f"p10={led_h['ret'].quantile(0.1):.3f}  p50={led_h['ret'].median():.3f}  "
      f"p90={led_h['ret'].quantile(0.9):.3f}")
# Verdict — judge on MEDIAN + win_rate, NOT the mean (one fat winner inflates it):
#   median_ret > 0 AND win_rate > 0.50  -> edge is REAL at the 20d horizon; the
#       negative daily result was a horizon-mismatch construction artifact.
#       m01_rank should drive a HOLD-~20d strategy, not daily rebalance.
#   median_ret ~ 0 / win_rate ~ 0.5     -> no real forward edge even at native
#       horizon; the mean was carried by outliers. Revisit target/features.
#   n_trades is only ~36 over one year -> SMALL SAMPLE. Confirm on a longer
#       window (multi-year validation) before trusting either verdict.
```

**Interpretation guide (revised 2026-05-22 — both engines are POSITIVE on real
returns):** the all-NULL-return run that suggested "daily negative / horizon
mismatch" was a data artifact (adj_close was NULL). With close-based returns,
daily rebalance is Sharpe ~1.8–2.0 AND 20d-hold median is +0.94%/trade — both
positive, leakage controls pass. The mean/median gap in Cell D is a genuine
fat-tailed winner distribution (normal for breakout strategies), NOT an outlier
artifact (LIF/CUE verified absent from the 2023 window). Trust the median.

The remaining doubt is **scope, not validity**: this is ONE year (2023, a
momentum-friendly regime) on a 2–5 name book with −40% max drawdown. That is
what Cell E tests.

---

## Cell E — walk-forward multi-year backtest (durability test)

**Why:** Cells B/D ran only on the 2023 validation slice (the model trains
`<2023`, validates `[2023,2024)`). A Sharpe ~2.0 in one momentum-friendly year
is not a durable edge. To backtest other years out-of-sample WITHOUT leakage, we
cannot just widen `scored` (that would include training rows). Instead, **expand-
ing walk-forward**: for each test year Y, train on everything `< Y`, score Y,
backtest Y with the SAME engines. Mirrors the notebook's G3 AUC walk-forward.

```python
def fit_score_year(df_all, feature_cols, target, train_end, test_start, test_end):
    """Train on <train_end, return scored = (date,ticker,prob) for [test_start,test_end]."""
    tr = df_all[df_all["date"] < pd.Timestamp(train_end)]
    te = df_all[(df_all["date"] >= pd.Timestamp(test_start)) &
                (df_all["date"] <  pd.Timestamp(test_end))]
    Xtr, ytr = tr[feature_cols].copy(), tr[target]
    Xte = te[feature_cols].copy()
    for c in Xtr.select_dtypes(include=["object", "category"]).columns:
        Xtr[c] = Xtr[c].astype("category"); Xte[c] = Xte[c].astype("category")
    spw = (len(ytr) - ytr.sum()) / (ytr.sum() + 1e-5)
    m = xgb.XGBClassifier(objective="binary:logistic", n_estimators=100,
        max_depth=4, learning_rate=0.05, subsample=0.8, colsample_bytree=0.8,
        scale_pos_weight=spw, enable_categorical=True, tree_method="hist",
        random_state=42).fit(Xtr, ytr)
    out = te[["date", "ticker"]].copy()
    out["prob"] = m.predict_proba(Xte)[:, 1]
    return out

# Expanding folds — each year tested on a model trained only on prior years.
# 2018-2019 reserved as the first training base. 2022 = the drawdown stress year.
WF_YEARS = [2020, 2021, 2022, 2023, 2024]
rows = []
for y in WF_YEARS:
    sc = fit_score_year(df, feature_cols, "y_homerun",
                        f"{y}-01-01", f"{y}-01-01", f"{y+1}-01-01")
    # Daily rebalance, top_k=3 (the headline cell)
    _, stB, _ = holdings_backtest(sc, ret1d_lookup, top_k=3,
                                  enter_persist=3, exit_persist=3, rebalance="D")
    # 20d non-overlapping hold
    _, stD = nonoverlap_holds(sc, retH_lookup, top_k=3, enter_persist=3)
    rows.append({"year": y,
                 "B_ann": stB.get("ann_return"), "B_sharpe": stB.get("nav_sharpe"),
                 "B_maxdd": stB.get("max_dd"),
                 "D_n": stD.get("n_trades"), "D_median": stD.get("median_ret"),
                 "D_win": stD.get("win_rate")})
wf_bt = pd.DataFrame(rows)
display(wf_bt)

print(f"\nDaily Sharpe — mean: {wf_bt['B_sharpe'].mean():.2f}  "
      f"min: {wf_bt['B_sharpe'].min():.2f}  "
      f"(2022 drawdown year: {wf_bt.loc[wf_bt.year==2022,'B_sharpe'].iloc[0]:.2f})")
# DURABILITY VERDICT:
#   Sharpe positive in MOST years incl. 2022, mean >1.0  -> durable edge. SHIP to G7.
#   Sharpe great in 2023 but <=0 in 2022 / other years   -> 2023 was a regime fluke;
#       the strategy is momentum-beta, not alpha. Do NOT promote on the 2023 number.
#   D_median positive across years -> the 20d signal is regime-robust too.
```

**Read the 2022 row first.** It is the regime stress test. If daily Sharpe is
positive in 2020, 2021, 2023, 2024 but collapses in 2022, the edge is long-only
momentum beta that dies in drawdowns — a real but fragile finding, not the
regime-robust conviction signal m01_rank is meant to be.

---

## Open questions — Phase 2 resolutions

1. **Exit symmetry (2.1):** implemented as **(b) symmetric** — out of top-K for
   `exit_persist` days. Swap to (a) any-day exit by setting `exit_persist=1`.
2. **K in top-K:** swept {2,3,5}. Phase 1's `n_tickers_scored` (>1,200/fold)
   confirms breadth supports K up to ~5 without starving.
3. **Persistence window:** fixed at 3 (entry and exit). Promote `enter_persist`/
   `exit_persist` to the sweep once the engine is validated.
4. **Weekly cadence (Open Q4):** implemented as "first trading day of each ISO
   week" (`rebalance="W"`), holding the set fixed between rebalances — the
   simpler, less-ambiguous of the two options the audit floated.

---

## Carry-forward to cookbook (2.2 / Phase 4.2)

Once this engine validates in the notebook, replace the cookbook's Cell 20
(`vectorized_backtest_nonoverlap`) with `holdings_backtest` and add a one-line
note: **"dense-grain models must book holdings-based daily P&L, never per-trade
forward returns — the latter double-counts overlapping episodes."**
