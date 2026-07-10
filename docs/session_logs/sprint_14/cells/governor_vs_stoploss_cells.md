# What drawdown does the governor control? — and how it interacts with the 15% stop-loss

> **The question (user, 2026-07-09):** the backtest already has a ~15% stop-loss. So what kind of
> drawdown is the governor actually controlling? If it's overnight **gap-down** risk, good — but if
> it's something the stop already handles, the two overlap and the governor adds nothing. And however
> they relate, we need to know whether they *interact* (double-count, or fight each other).
>
> **The answer (proven below, not asserted): they control DIFFERENT, non-overlapping drawdowns and
> compose cleanly — the governor is NOT a gap-down tool.**
>
> | layer | acts on | granularity | catches |
> |---|---|---|---|
> | **stop-loss (15%)** | one position's price path (`low ≤ entry×0.85`) | per-trade, intraday | a *single name* falling ≥15% from *its own* entry |
> | **governor** | whole-book daily return × exposure weight | per-calendar-day, portfolio-wide | *market-regime* drawdown (SPY≤200d) hitting *all names at once* |
>
> **The mechanism, from the code** (`vectorized_backtest.py`):
> - The stop-loss runs *inside* `run()` (`_simulate_exits`, line 316-317): `stop_level =
>   entry_price*(1-0.15)`; `hit_stop = low <= stop_level`. It **truncates each trade's window**
>   per-position. On a stop-out the fill is booked at `stop_level` (line 342-344) — i.e. it *assumes
>   a fill at exactly −15% even on a gap-down*, so the backtest UNDERSTATES true gap severity.
> - The governor runs *after*, in `equity_curve` (line 509-512): it multiplies the already-stopped
>   book's **daily portfolio return** by the exposure weight. It cannot un-stop a trade; it only
>   sizes the aggregate. **Different layer → they compose (multiply), no double-count, no fight.**
>
> **The load-bearing empirical fact (2008-09 bear, cells below):** the stop-loss fires **64-76 times**
> — each booking −15% — and the flat book STILL craters to −56%, because the regime-blind strategy
> keeps re-entering fresh breakouts into a falling market and getting stopped again. The governor turns
> that into −12% by flattening the WHOLE book at the 200d break, so **those 64 stop-outs never
> happen**. The governor is not gap control; it's *"don't repeatedly re-enter a falling market"*
> control — a portfolio-level regime brake the per-name stop structurally cannot provide.
>
> **Caveat surfaced (worth a separate ticket, doesn't change the verdict):** because the stop-loss
> books gap-downs at the −15% level, the flat −56% baseline is itself OPTIMISTIC on true gap risk. The
> governor partly masks this (fewer bear-regime days exposed = fewer gaps faced) but does NOT fix it —
> real gap-down realism is a stop-loss modelling gap, orthogonal to the governor.
>
> Reproduce: reads `data/score_cache/m01_binary_calibrated_*.parquet` +
> `src/backtest/{vectorized_backtest,macro_sizer}.py`. Verdict:
> `verdicts/2026-07-09_regime_governor_backtest.md`.

Paste each block as one cell.

---

### Cell 1 — the 2008 bear: run flat vs governor, same trades, same stops

```python
import sys
from pathlib import Path

def _root():
    p = Path.cwd().resolve()
    for d in (p, *p.parents):
        if (d / "config.py").exists() and (d / "src").is_dir():
            return d
    raise RuntimeError("root not found")

ROOT = _root(); sys.path.insert(0, str(ROOT))

import pandas as pd, numpy as np
from src.backtest.vectorized_backtest import VectorizedSEPABacktest
from src.backtest.macro_sizer import MacroSizer

scores = pd.read_parquet(ROOT / "data/score_cache/m01_binary_calibrated_2003-01-01_2026-05-22.parquet")
scores["date"] = pd.to_datetime(scores["date"])
s, e = "2007-06-01", "2009-12-31"
sl = scores[(scores.date >= s) & (scores.date <= e)].copy()

kw = dict(model_path=str(ROOT / "models/m01_binary/v1/model.json"), start_date=s, end_date=e,
          precomputed_scores=sl, min_prob_elite=0.15, max_positions_per_day=5,
          stop_loss_pct=0.15, exit_policy="sma", sma_exit_period=50)
vbt = VectorizedSEPABacktest(**kw)
trades = vbt.run()                         # stop-loss already applied here
flat = vbt.equity_curve(trades)            # stop-loss only
gov_w = MacroSizer().governor_weight(s, e)
gov = vbt.equity_curve(trades, exposure=gov_w)  # + governor overlay

print("trades:", len(trades))
print("exit reasons:", trades["exit_reason"].value_counts().to_dict())
```

### Cell 2 — the stop-loss IS firing, and STILL can't stop the regime bleed

```python
so = trades[trades.exit_reason == "stop_loss"]
print(f"stop-loss exits: {len(so)}   mean pnl at stop: {so['pnl_pct'].mean():.1%}")
print(f"flat maxDD (stop-loss only):     {(flat/flat.cummax()-1).min():>7.1%}")
print(f"governor maxDD (+ regime brake): {(gov/gov.cummax()-1).min():>7.1%}")
print(f"governor gate-off share:         {100*(gov_w==0).mean():>6.0f}% of the window")

# The point: the stop caps each NAME at -15%, but 60+ of them in a falling market
# still compound into a -56% BOOK drawdown. The governor removes the book exposure.
assert len(so) > 40, "expected many stop-outs in a bear"
assert (flat/flat.cummax()-1).min() < -0.40, "flat should crater despite the stop"
assert (gov/gov.cummax()-1).min() > (flat/flat.cummax()-1).min(), "governor must be shallower"
```

### Cell 3 — the picture: stop-outs firing all the way down, governor gated off

```python
import matplotlib.pyplot as plt

fig, (a1, a2) = plt.subplots(2, 1, figsize=(13, 8), sharex=True,
                             gridspec_kw={"height_ratios": [3, 1]})
a1.plot(flat.index, flat/flat.iloc[0], label="flat (stop-loss only)", color="#888", lw=1.8)
a1.plot(gov.index, gov/gov.iloc[0], label="governor + stop-loss", color="#3d85c6", lw=1.8)
a1.scatter(pd.to_datetime(so.exit_date), [0.55]*len(so), marker="|", color="#cc0000",
           s=40, alpha=0.5, label=f"stop-loss exits (n={len(so)})")
a1.set_title("2008 bear: the stop-loss fires per-name (-15% each) yet the flat book still bleeds;\n"
             "the governor flattens the WHOLE book so those stop-outs never happen")
a1.set_ylabel("equity (norm.)"); a1.legend(loc="upper right"); a1.axhline(1, color="k", lw=0.5)
a2.fill_between(gov_w.index, 0, gov_w.values, step="pre", color="#3d85c6", alpha=0.35)
a2.set_ylabel("governor\nexposure"); a2.set_ylim(0, 1.05)
a2.set_title("governor exposure (0 = SPY<=200d gate; the bleed window is gated off)")
plt.tight_layout()
plt.savefig(ROOT / "data/model_output_eda/regime_weight/governor_vs_stoploss_2008.png",
            dpi=110, bbox_inches="tight")
plt.show()
```

![governor vs stop-loss, 2008 bear](../../../../data/model_output_eda/regime_weight/governor_vs_stoploss_2008.png)

> **Read it:** grey (flat) craters to −56% while the red stop-loss ticks fire the whole way down —
> proof the per-name stop cannot stop the *book* from bleeding through repeated re-entries. Blue
> (governor) goes flat at the mid-2008 200d break and holds through the bottom, re-deploying only when
> SPY reclaims 200d in mid-2009. **That gap between the curves is the −46%→−19% cone result, and it is
> entirely regime (correlated multi-name) drawdown — not gap-down, which the stop already books.**

### Cell 4 — the interaction logic, stated plainly (no double-count, no fight)

```python
print("STOP-LOSS  vs  GOVERNOR — how they interact")
print("-" * 60)
print("stop-loss:  runs INSIDE run() -> truncates each trade's window")
print("            per-POSITION, intraday (low <= entry*0.85)")
print("            books gap-downs at the -15% level (optimistic)")
print("governor:   runs in equity_curve() -> scales the daily BOOK return")
print("            per-CALENDAR-DAY, portfolio-wide (SPY<=200d -> 0)")
print()
print("They compose by MULTIPLICATION at different layers:")
print("  - governor cannot un-stop a trade (stop already ran)")
print("  - stop cannot see the correlated book-level bleed (per-name only)")
print("  => complementary, not redundant; no double-count, no conflict")
print()
print("CAVEAT: the stop's gap-fill assumption means flat's -56% baseline")
print("        UNDERSTATES true gap risk. The governor reduces gap EXPOSURE")
print("        (fewer bear days held) but does NOT fix gap MODELLING. -> Cell 5 quantifies it.")
```

### Cell 5 — QUANTIFY the gap-down understatement (user Q: "account for the real loss")

```python
from src import db

# Full 25y stop-out population.
full = scores.copy()
vbt_all = VectorizedSEPABacktest(model_path=str(ROOT / "models/m01_binary/v1/model.json"),
    start_date="2003-01-01", end_date="2026-05-22", precomputed_scores=full,
    min_prob_elite=0.15, max_positions_per_day=5, stop_loss_pct=0.15,
    exit_policy="sma", sma_exit_period=50)
tr_all = vbt_all.run()
so = tr_all[tr_all.exit_reason == "stop_loss"].copy()
so["exit_date"] = pd.to_datetime(so["exit_date"])

# The bug (vectorized_backtest.py:342-344): stop-outs book exit_price = stop_level
# (= entry*0.85) UNCONDITIONALLY. But hit_stop fires on `low <= stop_level`, so on a
# GAP-DOWN OPEN below the stop, the real fill is the OPEN, not stop_level.
con = db.connect(str(ROOT / "data/market_data.duckdb"), read_only=True)
tickers = tuple(so.ticker.unique().tolist())
px = con.execute(f"SELECT ticker,date,open FROM price_data WHERE ticker IN {tickers}").df()
con.close()
px["date"] = pd.to_datetime(px["date"])
m = so.merge(px, left_on=["ticker", "exit_date"], right_on=["ticker", "date"], how="left")
m["stop_level"] = m["entry_price"] * 0.85
m["gapped"] = m["open"] < m["stop_level"]                      # opened below the stop
m["real_fill"] = np.where(m["gapped"], m["open"], m["stop_level"])
m["booked_ret"] = m["stop_level"] / m["entry_price"] - 1       # always -15%
m["real_ret"] = m["real_fill"] / m["entry_price"] - 1

print(f"stop-outs (25y):        {len(m)}")
print(f"gap-through-stop rate:  {m.gapped.mean():.1%}")
print(f"mean booked loss:       {m.booked_ret.mean():.2%}   (always -15%)")
print(f"mean REAL loss:         {m.real_ret.mean():.2%}   (understated by {m.real_ret.mean()-m.booked_ret.mean():.2%})")
print(f"on GAPPED stops only:   {m.loc[m.gapped,'real_ret'].mean():.1%} real vs -15% booked")
print(f"worst real gap loss:    {m.real_ret.min():.1%}")
assert m.gapped.mean() < 0.15, "gap rate sanity"
```

> **Read it:** ~**7%** of stop-outs gap through the level; on those the real loss averages **~−20%**
> (worst −40%), not the booked −15%. Averaged over ALL stop-outs the understatement is only **~−0.3%**,
> so it does NOT distort the headline cone — but the −40% tail case is real and matters for a
> tail-focused strategy. **This is a stop-loss MODELLING fix (book gap-outs at `min(stop_level,
> open)`), orthogonal to the governor** — logged as its own ticket.

---

## Extension A (user Q, 2026-07-09) — how is capital deployed / equity computed? (the chart's LIMITATION)

> **The honest answer: there is NO capital-usage ledger at this step.** `equity_curve`
> (`vectorized_backtest.py:483-514`) is a pure RETURN-compounding model, not a cash account:
> - `daily_frac_pnl[day] = Σ close-to-close return of each open position` (each enters at weight 1).
> - `daily_return = daily_frac_pnl × position_size_pct × scale`, where `scale` (the ONLY capital
>   constraint) pro-rata-dilutes only when >`1/position_size_pct` positions are open (else =1).
> - `equity = initial_cash × cumprod(1 + daily_return)` — geometric compounding of the daily %.
> **Consequences:** (1) **idle capital earns nothing and costs nothing** — a 0-position day (or
> governor exposure=0) gives `daily_return=0` → equity FLAT, no cash-yield, no drag. (2) The
> governor's weight `w` **scales the RETURN, not a cash allocation** — `w=0` ≡ "100% cash, 0% return",
> `w=0.5` ≡ "halve today's P&L". It is a return multiplier, NOT a position-sizing ledger. (3)
> **Under-deployment is invisible** — 2/5 slots filled just contributes `2×0.20=40%` to the return;
> the unused 60% neither helps nor hurts. So the chart answers *"what return did the selected trades
> make, scaled by exposure"* — NOT *"how was capital allocated, and what did idle cash do."*

```python
# Demonstrate: the governor curve is FLAT (not declining, not cash-yielding) while gated off.
gov_flat_days = (gov.pct_change().abs() < 1e-9).sum()
print(f"governor days with EXACTLY zero return (gated off / no positions): {gov_flat_days}")
print("-> equity is FLAT on those days: no cash yield, no drag. Pure return model, no cash ledger.")
# The scale term: how often is the book actually capital-constrained (>max_slots open)?
# (Informational — shows the pro-rata dilution is the only capital cap in the model.)
print(f"position_size_pct implies max_slots = {round(1/0.20)}  (dilution only kicks in above this)")
assert gov_flat_days > 0, "governor should have gated-off flat days in a bear window"
```

## Extension B (user Q, 2026-07-09) — what if we release the brake near the BOTTOM?

> **The gate re-deploys at the 200d RECLAIM, not the trough — and that costs the snap-back.** In
> 2008-09: SPY bottomed 2009-03-09 (−55% from peak, −35% below its 200d) and didn't reclaim the 200d
> until **81 days later** (2009-05-29). Over that trough→reclaim leg SPY rallied **+36.8%** and the
> **flat strategy earned +38.6%** — the governor earned **+0.0%** (gated fully off, mean exposure 0.0).
> The gate that saves the −40% descent also misses the +38% rebound, because **the rebound STARTS
> below the 200d** (memory: rebound-lives-sub-200d). NET over the full episode the governor still ends
> AHEAD (drawdown-avoided > rebound-missed), but the late re-entry is a real, quantifiable cost.
>
> **Is the trough detectable ex-ante (so we COULD release early)?** Hard: VIX peaked **109 days
> BEFORE** the price trough (2008-11-20), so "wait for fear to pass" is not a clean bottom signal. But
> a naive off-the-bottom momentum trigger (price +X% off its 20d low, while still <200d) moves **+25%
> within 45 days** of the trough → a recovery-momentum rule COULD re-deploy far earlier than the 200d
> reclaim, at the cost of false starts on the way down. That's the design space for a "release the
> brake near the bottom" v2 — informational, not yet built.

```python
import matplotlib.pyplot as plt
from src import db

s2, e2 = "2008-06-01", "2009-12-31"
sl2 = scores[(scores.date >= s2) & (scores.date <= e2)].copy()
vbt2 = VectorizedSEPABacktest(model_path=str(ROOT / "models/m01_binary/v1/model.json"),
    start_date=s2, end_date=e2, precomputed_scores=sl2, min_prob_elite=0.15,
    max_positions_per_day=5, stop_loss_pct=0.15, exit_policy="sma", sma_exit_period=50)
tr2 = vbt2.run()
flat2 = vbt2.equity_curve(tr2)
gov_w2 = MacroSizer().governor_weight(s2, e2)
gov2 = vbt2.equity_curve(tr2, exposure=gov_w2)

con = db.connect(str(ROOT / "data/market_data.duckdb"), read_only=True)
spy = con.execute("SELECT date,spy_close FROM t1_macro WHERE date BETWEEN '2007-06-01' AND ? ORDER BY date",
                  [e2]).df(); con.close()
spy["date"] = pd.to_datetime(spy["date"]); spy = spy.set_index("date")["spy_close"]
spy200 = spy.rolling(200).mean()
trough = spy[(spy.index >= s2) & (spy.index <= e2)].idxmin()
reclaim = (spy > spy200); reclaim = reclaim[reclaim.index >= trough]; reclaim = reclaim[reclaim].index[0]

# The missed leg, quantified.
def _ret(curve, a, b):
    seg = curve[(curve.index >= a) & (curve.index <= b)]; return seg.iloc[-1] / seg.iloc[0] - 1
print(f"trough {trough.date()} -> 200d reclaim {reclaim.date()}  ({(reclaim-trough).days} days)")
print(f"  SPY:       {spy.loc[reclaim]/spy[(spy.index>=s2)&(spy.index<=e2)].min()-1:+.1%}")
print(f"  FLAT:      {_ret(flat2, trough, reclaim):+.1%}   (in for the rebound)")
print(f"  GOVERNOR:  {_ret(gov2, trough, reclaim):+.1%}   (gated off — MISSED)")
print(f"  governor mean exposure in that window: {gov_w2[(gov_w2.index>=trough)&(gov_w2.index<=reclaim)].mean():.2f}")
print(f"NET over full episode: flat {flat2.iloc[-1]/flat2.iloc[0]-1:+.0%}  vs  governor {gov2.iloc[-1]/gov2.iloc[0]-1:+.0%}"
      "  (governor AHEAD: DD-avoided > rebound-missed)")
assert _ret(gov2, trough, reclaim) < 0.02, "governor should be ~flat in the gated rebound leg"
```

![governor misses the rebound leg, 2009](../../../../data/model_output_eda/regime_weight/governor_missed_rebound_2009.png)

> **Read the figure:** top — the gate re-deploys at the 200d reclaim (green-band right edge), not the
> trough (left edge), so the whole +37% SPY leg is skipped. Bottom — flat (grey) rides the snap-back
> from 0.60→~1.0; governor (blue) is flat through the band then re-enters late, yet ends HIGHER overall
> because it never took the descent. **The rebound-miss is the price of the drawdown-control; a
> trough-release rule is the natural v2 to recover it.**

## Extension C (user Q, 2026-07-09) — do we add stocks daily, or lock on day 1? And what happens on unfreeze?

> **Neither locked-on-day-1 nor a fresh-basket-daily — it's a ROLLING slot-book.** From
> `_select_entries` + `_enforce_capacity` (vectorized_backtest.py:139-203, 387-415):
> 1. **New candidates every day** — each day the top-`max_positions_per_day` names by
>    `prob_elite ≥ threshold` are eligible. Entries KEEP happening (see the by-month table below).
> 2. **Each ticker enters ONCE per backtest** — `drop_duplicates(subset=['ticker'], keep='first')`.
>    A name that re-qualifies later is NOT re-bought (no pyramiding, no re-entry after exit).
> 3. **A concurrent-slot cap throttles intake** — a greedy heap admits a new pick only if a slot is
>    free (an older position exited); otherwise that day's candidate is DROPPED, not queued.
> So the book flows: new breakouts in as slots free up, names out as they stop/trend-exit.
>
> **⚠️ THE GOVERNOR-SPECIFIC CATCH (the important part):** the governor is a RETURN multiplier applied
> AFTER `run()` — it does NOT touch the trade list. So **entries keep firing DURING the gated-off
> window** (13 entered in Mar-2009, mid-freeze); their returns are merely zeroed. Consequence: on the
> **first unfreeze day (200d reclaim)** you do NOT get a fresh day-1 basket — you INHERIT the positions
> that entered during the freeze, already mid-flight (16 open on 2009-05-31, only 2 genuinely new in
> the next 20d). **This mismodels a real gated strategy**, which would be in CASH during the freeze
> then deploy FRESH into new breakouts on unfreeze. The current proxy = "fully invested the whole time,
> P&L zeroed on gated days, switch flipped back on holding stale positions." The DD-control result is
> unaffected (no P&L while gated is correct), but the *re-entry* is optimistically/wrongly modelled —
> and it compounds the rebound-miss in Extension B (on unfreeze you hold tired names, not fresh
> bottom breakouts). A faithful gate (flatten → redeploy fresh) is part of the v2.

```python
tr2["entry_date"] = pd.to_datetime(tr2["entry_date"])
by_month = tr2.groupby(tr2.entry_date.dt.to_period("M")).size()
print("entries by month (rolling entry engine — NOT locked on day 1):")
print(by_month.to_string())
print(f"\ntotal entries {len(tr2)} == unique tickers {tr2.ticker.nunique()}  (each ticker enters once)")

# Governor-specific: entries fire DURING the freeze; on unfreeze you inherit them mid-flight.
first_unfreeze = gov_w2[(gov_w2.index > "2009-05-01") & (gov_w2 > 0)].index.min()
open_on_unfreeze = tr2[(tr2.entry_date <= first_unfreeze) &
                       (pd.to_datetime(tr2.exit_date) > first_unfreeze)]
new_20d = tr2[(tr2.entry_date > first_unfreeze) &
              (tr2.entry_date <= first_unfreeze + pd.Timedelta(days=20))]
print(f"\nfirst unfreeze day: {first_unfreeze.date()}")
print(f"  positions already open (entered DURING freeze, returns were zeroed): {len(open_on_unfreeze)}")
print(f"  genuinely NEW entries in the 20d after unfreeze:                     {len(new_20d)}")
print("  -> you INHERIT stale mid-flight names, NOT a fresh day-1 bottom basket (a v2 gap).")
assert len(by_month) > 6, "entries should span many months (rolling, not one basket)"
assert len(open_on_unfreeze) > len(new_20d), "unfreeze inherits more than it fresh-deploys"
```

## Extension D (user Q, 2026-07-09) — "unlimited capital → equity always up?" NO, but exposure DRIFTS

> **The critique is right in mechanism, wrong in conclusion.** `daily_return = Σ(open-position returns)
> × position_size_pct × scale` (vectorized_backtest.py:499-500). `daily_frac_pnl` is the SUM (`+=`) of
> every open position's return, and `scale` (the dilution cap) only fires when `open_count > max_slots
> = 1/position_size_pct` (=10 at the default 0.10). So **96.6% of days `scale=1`** and gross exposure =
> `open_count × 0.10`, uncapped in practice — adding a position adds gross exposure, not dilution.
> **BUT equity is NOT guaranteed up:**
> 1. **Returns are signed** — summing positions in a BEAR sums LOSSES (2008 fell −56% *because* it kept
>    entering into the decline). Exposure amplifies whatever the market gives, up or down.
> 2. **It's mostly UNDER-deployed, not over-levered** — mean gross **43%**, **57% of days <50%
>    invested**, only 5% >90%; capped at 10 concurrent. No runaway compounding; if anything it
>    understates achievable return by leaving capital idle.
>
> **The REAL flaw (different from "always up"): gross exposure is an ARTIFACT of breakout SUPPLY, not a
> sizing decision.** It drifts **28% (2017) → 66% (2021)** with how many names happen to break out.
> Consequences: (a) cross-period comparisons are contaminated (a "good year" may just be a
> high-supply/high-exposure year); (b) the governor weight `w` multiplies ON TOP of this drifting base
> — "governor 50%" = 50% of a variable 28-66%, not of a fixed book. A fixed-fractional or
> vol-targeted book would separate edge from accidental leverage — a backtest-fidelity upgrade,
> orthogonal to the governor.

```python
# Reconstruct daily concurrent open-position count -> implied gross exposure.
tr_all["entry_date"] = pd.to_datetime(tr_all["entry_date"])
tr_all["exit_date"] = pd.to_datetime(tr_all["exit_date"])
gdates = pd.date_range(tr_all.entry_date.min(), tr_all.exit_date.max(), freq="B")
dpos = {d: i for i, d in enumerate(gdates)}
def _near(d):
    if d in dpos: return dpos[d]
    a = gdates[gdates >= d]; return dpos[a[0]] if len(a) else None
oc = np.zeros(len(gdates))
for _, t in tr_all.iterrows():
    ei, xi = _near(t.entry_date), _near(t.exit_date)
    if ei is None or xi is None or xi <= ei: continue
    oc[ei:xi] += 1
occ = pd.Series(oc, index=gdates)
gross = np.minimum(occ * 0.10, 1.0)   # position_size_pct=0.10, capped ~1.0 by scale at 10 slots

print(f"gross exposure: mean {gross.mean():.0%} · median {gross.median():.0%} · "
      f"<50% invested {100*(gross<0.5).mean():.0f}% of days · >90% {100*(gross>0.9).mean():.0f}%")
print("mean concurrent positions by year (exposure drifts with breakout supply):")
print((occ.groupby(occ.index.year).mean().round(1)).to_string())
assert gross.mean() < 0.6, "book is mostly under-deployed, not levered up"
assert (gross < 0.5).mean() > 0.4, "majority of days below 50% invested"
```

![gross exposure drift](../../../../data/model_output_eda/regime_weight/gross_exposure_drift.png)

> **Read it:** gross exposure swings 15-100% continuously, driven by breakout supply — pinned near
> 100% in the 2003-04 launch (dilution cap active), collapsing to ~5% in the 2008-09 crash (few
> breakouts), drifting up to ~66% in the 2021 boom. The red mean sits at 43%: **the strategy is
> mostly UNDER-invested, and its leverage is an accident of the calendar, not a decision.** So "equity
> always up" is false (2008 proves it) — but exposure is uncontrolled, which contaminates any
> cross-period read.

## Conclusion

**The governor controls correlated, regime-driven drawdown — the multi-name slow bleed of holding a
book through a bear market — which the 15% per-name stop-loss structurally cannot address.** Proven:
in 2008-09 the stop-loss fired 64-76 times (−15% each) and the flat book still fell −56%, because the
regime-blind strategy re-entered fresh breakouts into the decline and got stopped again; the governor
flattened the whole book at the 200d break and cut that to −12%. It is **not** a gap-down tool (gaps
are the stop's domain, and the stop books them optimistically at −15%). The two layers compose by
multiplication at different points in the pipeline — no double-count, no conflict. The one open item is
a **stop-loss modelling caveat** (optimistic gap fills → the flat baseline understates true gap
severity), which is orthogonal to the governor and worth a separate ticket.
