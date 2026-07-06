# ISSUE: Corrupt shares_outstanding / price rows escape the DQ audit (implied caps in the thousands of trillions)

**Status:** CLOSED 2026-07-04 (second pass). The 1e11→3e10 tightening exposed a **sub-ceiling
dirt tier**: the same ~1000× FMP scaling dirt on SMALL tickers lands *below* any global bound
(GTLS 29.9B vs real 30M; 86 shares rows / 36 tickers, 38 fundamentals rows / 12 tickers, all
source=fmp — incl. OPTT at ~10× scale). Adjudicated row-by-row against current fundamentals +
implied cap; nulled via parts D/E of the cleanup script (EXE 2020-04-10 whitelisted — legit
1.957B pre-1:200-reverse-split count). New relative tripwires (`>1B AND >500× ticker median`)
live on BOTH shares_history and fundamentals. OHLC-ordering class resolved: 99.9% was <0.1%
rounding epsilon, 34 recurring live-feed tape artifacts (WARN), 3 corrupt bars (nulled) — check
recalibrated to three tiers. `null_or_zero_close` refined to exclude deliberately-nulled bars.
⚠️ Re-run `clean_dirty_shares_price.py` on the sh019 box (its DB copy still has the dirt).
Cleanup applied via `scripts/clean_dirty_shares_price.py` (machine-portable: config-relative DB
path + `src.db` governed connection — runs on the ITX/`sh019` infra box too). Backfill script
`backfill_shares_from_fundamentals.py` now bounded (`basic_avg_shares < 3e10`) so it can't re-leak.
Three of four DQ checks now green; `ohlc_ordering` (41,373 rows) is a separate class, still FAIL.
**Severity:** HIGH. Silent data corruption in **two** T1 tables (`shares_history` AND
`price_data`) that feed any market-cap computation. Surfaced while building CAPE_OURS; the
99th-pct winsorize was accidentally masking it (see
[cape_fred_proxy_findings.md](cape_fred_proxy_findings.md), drift decomposition).
**Fix this before revisiting CAPE.** Root cause is a *systemic* DQ gap (every check validates
presence/type, none validate plausibility) — see the table under "Why the DQ audit missed it".

---

## What's wrong

Some `shares_history` rows carry `shares_outstanding` values in the **trillions** (real
companies have millions–billions), producing implied market caps of **thousands of
trillions of dollars** — physically impossible (largest company ever ≈ $4.7T, NVDA 2026).

Two *distinct* corruption modes (the fix must handle both):

### Mode A — corrupt `shares_outstanding` (shares bug)
| ticker | dirty shares (max) | sane shares (min) | pattern |
|---|--:|--:|---|
| FITB | 796,283,198,000,000 (796T) | 330M | **one** bad row (2010-09-30), ~10⁶× scaling error |
| PCG | 513,773,072,000,000 (513T) | 344M | **sustained block** 2011–2017 (16+ months) |
| CNA | 269,946,268,000,000 (270T) | 156M | block 2012–2014 |
| CBT | 63,994,075,000,000 (64T) | 52M | 2 rows 2012–2013 |
| CNNE, CG, HII, PEB | 43T–72T | — | isolated rows |

Broad scan: **31 rows with `shares_outstanding > 10 trillion` across 9 tickers**;
**61 rows > 100 billion across 20 tickers.** (100B shares is already larger than any real
company, so 100B is a safe lower bound for "impossible".)

### Mode B — corrupt `close` price (price bug, NOT shares)
Some tickers have *sane* shares but insane implied caps → the **price** is dirty:
| ticker | implied cap (max) | max shares | note |
|---|--:|--:|---|
| TNXP | $438,763T | 552M (fine) | price astronomically wrong |
| ADTX | $259,585T | 45M (fine) | price bug |
| GPUS | $1,818T | 14M (fine) | price bug |

Full scan: `scripts/analyze_cape_drift.py` (drift decomposition) and the ad-hoc queries in
this session. Reproduce with: implied cap = `last(shares) * last(close)` per ticker-month,
filter `> 8e12`.

---

## Why the DQ audit missed it (root cause of the DQ gap)

`tools/audit_t1_data_quality.py :: check_shares_integrity()` only checks:
- duplicate `(ticker, date)` keys,
- `shares_outstanding IS NULL OR <= 0` (non-positive),
- date range / freshness.

**There is no UPPER-BOUND / sanity-range check.** A value of 796 *trillion* is positive and
non-null, so it sails through every existing gate. Likewise:
- `price_data` checks (volume UBIGINT, OHLC ordering, coverage) have no **implied-market-cap**
  sanity check, so Mode B (dirty price) is invisible too.
- No check ever **joins shares × price** to test the derived market cap — the one quantity
  that makes the corruption obvious.

This is the classic "we validate presence and type, not plausibility" gap.

### This is systemic, not a one-off (verified across the audit)
The same gap exists in **every** integrity check — they all validate presence/type, none
validate plausibility ranges. Verified against the live DB this session:

| table | plausibility gap | unchecked dirt (live counts) |
|---|---|---|
| `shares_history` | no **upper** bound on shares (only null/≤0 floor) | 61 rows >100B, 31 rows >10T |
| `price_data` | **no upper bound on `close`** | 78,265 rows (66 tickers) with close >$1M/share; MRDN @ $1.6T/share, NUWE @ $721B |
| cross-table | no implied-cap sanity (no join exists) | 101 ticker-days >$8T |
| `price_data` | **OHLC ordering never checked** | 41,522 rows (high<close OR low>close OR high<low) |

Two structural lessons:
1. **The Mode B root cause is the unchecked `close` ceiling in `price_data`** — not merely a
   downstream cap symptom. Fixing it belongs in `price_data` and needs its own DQ check (below).
2. **Delta-based checks cannot catch scale corruption.** The existing `extreme_price_moves_gt200pct`
   check (a day-over-day % move) barely sees MRDN's dirt — a *sustained block* of $1.6T prices has
   almost no jump *inside* it (only 15 qualifying moves). And that check is `WARNING`-only with a
   >100 threshold (currently 998 rows), so it never escalates. **Absolute bounds are the only thing
   that catches wrong-scale blocks** — the same reason the doc rejects a percentile for shares.

---

## Source investigation (traced this session — root cause found, both modes)

The threshold-delete plan below was reconsidered after tracing where the dirt actually comes
from. **The corruption originates one layer deeper than `shares_history` / `price_data`.**

### Mode A (shares) — leaked from `fundamentals.basic_avg_shares` via a backfill
- The live `SharesEngine` (`src/shares_engine.py`) **only writes today's snapshot** (yfinance
  `sharesOutstanding` is point-in-time). It is NOT the source of historical dirt.
- The historical rows were written **March 2026** by
  [`scripts/backfill_shares_from_fundamentals.py`](../../../scripts/backfill_shares_from_fundamentals.py),
  which copies `fundamentals.basic_avg_shares` straight into `shares_outstanding` with **no
  sanity bound** (only `> 0`). Same "presence not plausibility" gap, now at the source.
- The true dirt is **`source='fmp'` rows in `fundamentals.basic_avg_shares`** — FMP has sporadic
  1000×+ scaling corruption in that field (values up to 64 *trillion*). The backfill faithfully
  copied them.
- ⚠️ **Reconciliation gotcha:** `shares_history` currently holds MORE / different dirt than
  `fundamentals` does today. Example: REGN's shares_history dirt is at 2012-03/06 (93B), but
  REGN's `fundamentals` now only goes back to 2019 (all clean, ~110M). The corrupt 2012 fmp rows
  the backfill read **have since been re-fetched away** — the leaked dirt is a *frozen snapshot of
  an older, worse fundamentals state*. Consequence: **re-running the backfill today would NOT
  reproduce most of it**, but the leaked rows persist. Only 37 fundamentals rows (>30B, 6 tickers)
  are still dirty; 34 of those leaked into shares_history.
- **Refetch is NOT viable for shares history** — yfinance can't reproduce 2011 point-in-time
  share counts, and the corrupt fmp source rows are mostly gone. Cleanup must operate on
  `shares_history` directly (null+ffill or interpolate), and separately clean the 37 residual
  fundamentals rows + bound the backfill script so it can't leak again.

### Mode B (price) — legacy `source=None` import, and it IS refetchable
- The `close`-ceiling dirt is **97.7% in `source=None` rows** (129,079 of 132,006). Modern
  `source='yfinance'` rows are 99.96% clean (2,927 of 8M) — the current feed already self-corrected.
- No multi-source duplicates exist (`price_data` has 0 rows with >1 source per ticker-date), so
  the dirty legacy row is always the **sole copy** — can't just "prefer the clean source".
- BUT yfinance serves **historical daily OHLC** (unlike shares), and the affected tickers are
  still live (e.g. MRDN has rows through 2026-07-02). So **price dirt is refetchable**: re-pull
  the affected legacy tickers and overwrite. The clean source *is* the criteria — no magic
  threshold needed, and it fixes subtler tiers (the $100k–$810k rows) for free.

**Net effect on cleanup:** the "pick a threshold" question is largely moot. Price → refetch.
Shares → clean in place + fix the source table + bound the backfill script. See revised plan.

---

## Proposed fix (revised after source trace)

### 1. Clean the existing corrupt rows

**Mode B (price) — NULL IN PLACE. Refetch was investigated and REJECTED.**
- ❌ Refetch does NOT work: yfinance's own `period="max"` history for these low-float /
  reverse-split tickers is *also* dirty at the source (ADTX serves $3.7T/share for 1,140 of
  1,509 bars; ABVC $7.1M for 862 bars). The "modern feed is clean" observation held only for
  *recent* rows we sampled — the historical yfinance data is corrupt too. There is no clean
  upstream. (An early refetch attempt also truncated ADTX/ABVC history via a default-`period`
  bug — restored by null-in-place; a shrink-guard was added then the refetch path deleted.)
- ✅ **Actual fix:** null OHLC on bars with `close > 1e6`, preserving the date spine so downstream
  returns bridge the gap. Then a **cross-table sweep**: null sub-$1M bars whose implied cap > $8T
  (the $810k–$1M tier — TNXP/EMPD/PSTV — where shares are plausible so only the product reveals
  the dirt). Both in `scripts/clean_dirty_shares_price.py`.

**Mode A (shares) — CLEAN IN PLACE (refetch not viable, see source trace).**
- Flag rows by an absolute bound (`shares_outstanding > 3e10` — real max is AAPL ~25B, so 30B is
  a safe floor for "impossible"; note the original 1e11 cut MISSES the REGN/IFF ~1000× tier at
  80–94B). Null the flagged rows so downstream `ffill` bridges them — a monthly-cap consumer
  tolerates a gap far better than a 1000× spike.
- ⚠️ **Sustained blocks** (PCG 2011–2017): nulling leaves a long hole. Interpolate from
  surrounding sane values, or accept the ffill bridge.
- **Also clean the source:** the 37 residual dirty `fundamentals.basic_avg_shares` rows
  (`source=fmp`, >30B, 6 tickers) — null them, else a future backfill of one of those tickers
  re-leaks. AND add a sanity bound to
  [`backfill_shares_from_fundamentals.py`](../../../scripts/backfill_shares_from_fundamentals.py)
  (the `WHERE basic_avg_shares > 0` clause needs an upper bound, e.g. `AND basic_avg_shares < 3e10`)
  so the copy can never leak absurd values again. **This is the real structural fix** — the DQ
  checks are a tripwire; the bound on the backfill is the dam.

### 2. Add DQ checks so it can never silently recur — ✅ DONE (wired in this session)
The four checks below are **live** in `tools/audit_t1_data_quality.py` (`check_shares_integrity`
+ `check_price_integrity`), all FAIL-level, verified firing at 61 / 78,265 / 41,522 / 101. They
are **tripwires only** (detect, not clean) — they'll stay red until the cleanup above runs.
⚠️ The `absurd_share_count` threshold is `1e11` (100B), which detects the egregious dirt but
MISSES the REGN/IFF ~1000× tier (80–94B). Cleanup uses the tighter `3e10` bound; consider
tightening the *check* to match once the sub-100B tier is cleaned (leaving it at 1e11 now avoids
false alarms on data we haven't cleaned yet — tighten it in lockstep with the cleanup).

Add to `check_shares_integrity()`:
```python
# absolute upper-bound sanity: no real company has > 100B shares
absurd = con.execute(
    "SELECT COUNT(*) FROM shares_history WHERE shares_outstanding > 1e11").fetchone()[0]
_check("shares_history", "absurd_share_count", "FAIL" if absurd else "OK", absurd,
       "rows with shares_outstanding > 100B (impossible; likely units/scaling error)")
```
The `shares > 1e11` check above is the **primary shares gate** — exact-date-independent, and
already catches 61 of the shares-side dirt directly.

Add a matching **`price_data` close ceiling** — this is the primary Mode B gate (the corruption
*lives* in `price_data`, so gate it there directly rather than only via the cross-table join):
```python
# absolute close ceiling: BRK-A (real, highest US share price) tops ~$810k.
# > $1M/share is not a real price (MRDN $1.6T, NUWE $721B — units/scaling error).
absurd_px = con.execute(
    "SELECT COUNT(*) FROM price_data WHERE close > 1e6").fetchone()[0]
_check("price_data", "absurd_close_price", "FAIL" if absurd_px else "OK", absurd_px,
       "rows with close > $1M/share (impossible; BRK-A real max ~$810k)")
```
Add an **OHLC ordering** check (41,522 dirty rows today, never validated):
```python
# high must be >= close/low, low must be <= close. Violations = corrupt bars.
bad_ohlc = con.execute(
    "SELECT COUNT(*) FROM price_data WHERE high < close OR low > close OR high < low").fetchone()[0]
_check("price_data", "ohlc_ordering", "FAIL" if bad_ohlc else "OK", bad_ohlc,
       "rows violating high>=close>=low ordering (corrupt bars)")
```

Add a **derived market-cap sanity** check as the belt-and-suspenders net for both modes:
```python
# implied market cap > $8T is impossible (largest company ever ~$4.7T)
absurd_cap = con.execute('''
  WITH s AS (SELECT ticker, date, shares_outstanding FROM shares_history),
       p AS (SELECT ticker, date, close FROM price_data)
  SELECT COUNT(*) FROM s JOIN p USING(ticker, date)
  WHERE s.shares_outstanding * p.close > 8e12
''').fetchone()[0]
_check("cross_table", "absurd_implied_market_cap", "FAIL" if absurd_cap else "OK", absurd_cap,
       "ticker-days with implied cap > $8T (dirty shares OR dirty price)")
```
⚠️ **The cross-table join is a NET, not a primary gate.** `JOIN ... USING(ticker, date)` only
covers **60.4% of `shares_history` rows** — the other 40% have no same-date `price_data` row
(shares dates aren't all trading days; shares extend past price coverage). It catches today's 101
only because those tickers overlap; a corrupt row on a non-matching date passes silently. That's
fine *because* the two per-table ceilings (`shares > 1e11`, `close > 1e6`) gate each side directly
and are date-independent. The cap check adds value only for the rare case where shares AND price
are each individually plausible but their product isn't — keep it, but don't rely on it as the
sole guard. (Upgrading it to an as-of join for ~100% coverage is possible but not worth the SQL
given the two direct ceilings already cover both sides.)

(Threshold `$8T` leaves headroom above today's ~$4.7T top; revisit if a real company ever
approaches it. `ponytail:` absolute bounds, not percentiles — percentiles are unstable across
the panel, which is exactly what corrupted the CAPE winsorize, AND they can't catch a sustained
wrong-scale *block*, only isolated spikes.)

---

## Blast radius (why this matters beyond CAPE)

`shares_history` × `price_data` = market cap feeds **anything** cap-weighted or cap-filtered:
- CAPE_OURS (found here) — mitigated by winsorize today, but that masks not fixes.
- Any universe/screener step that ranks or filters by market cap or float.
- Liquidity/size features, cap-weighted aggregates, backtests that size by cap.

Audit these consumers once the rows are cleaned. Grep starting points:
`shares_outstanding`, `market_cap`, `mktcap`, `* close` cap computations.

---

## Acceptance criteria
1. **Shares side (Mode A):** rows with `shares_outstanding > 1e11` identified, root-caused
   (units? source?), and cleaned (refetch or null+ffill), with the fix logged.
2. **Price side (Mode B):** rows with `close > 1e6` identified, root-caused (split/scaling in the
   raw price source), and cleaned. This is a separate `price_data` cleanup — cleaning shares alone
   will NOT green the price/cap checks.
3. Four new DQ checks live, all **FAIL** status, wired into the nightly audit:
   `absurd_share_count`, `absurd_close_price`, `ohlc_ordering`, `absurd_implied_market_cap`.
   Each check goes green only after *its own* table is cleaned (the cross-table cap check needs
   BOTH shares and price clean).
4. Downstream cap-consumers audited; note any that were silently affected.
5. Then: revisit CAPE — with clean caps, re-evaluate whether the winsorize can be replaced by
   the absolute ceiling (the drift decomposition showed winsorize was ~80% of the apparent
   drift *because* of this dirt).

> **Scope note:** the OHLC-ordering dirt (41,522 rows) is a genuinely separate corruption class
> from the cap issue and is far larger — cleaning it may warrant its own sub-task. It's listed
> here because it's the same root DQ gap (no plausibility check), but the memory note
> `price_data_ohlc_dirt` already mitigates it downstream (bound excursions with GREATEST/LEAST).
> Decide whether to clean the rows or just add the FAIL check as a tripwire.
