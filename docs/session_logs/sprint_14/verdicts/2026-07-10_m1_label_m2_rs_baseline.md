# M1+M2 verdict — m01a_tail_v1 label registered & leak-clean; RS-only baseline = the bar ML must beat

**Date:** 2026-07-10 · **Status:** ✅ M1 + M2 of `../plans/m01a_tail_ranker_plan.md`.
Parent: `2026-07-10_m0_horizon_sweep.md` (N=63, tail-magnitude label).

## M1 — label build + leakage audit

- **Registry:** `label_registry/m01a_tail_v1.json` (fingerprint `c142f255ad71…`), built by
  `scripts/build_m01a_tail_label.py`. Target `tail_mag_63 = max(MFE_63 − 30%, 0)`, binary diagnostic
  `home_run_63`; `horizon_days=63` **trading bars**, `exit_rule='fixed_horizon'`, entry at day-t close,
  window = bars t+1..t+63 (entry day excluded, full window required). Population = full `trend_ok`
  panel: **1,611,203 rows, 2001-01-02 → 2026-04-08, positive rate 11.45%.**
- **Not materialized anywhere** — the label recomputes from `source_query` in ~10s; the JSON is the
  canonical definition. Add a cache when M3 training needs one.
- **LeakageGuard.audit_label: PASS** — 1,500-row random sample, recompute-from-price_data reference,
  0 violations, 0 missing-price rows. The audited surrogate is `fh63` (the forward-window max, the
  label's only window-dependent term); `tail_mag_63`/`home_run_63` are asserted in-script to be pure
  functions of `(fh63, entry_close)`. `audit_label`'s price query widened `SELECT date, close → SELECT *`
  so high-based labels can be recomputed (tests still green).

### Dirt found & FIXED AT SOURCE: isolated corrupt highs (new dirt class)

The first M2 run showed a D2/2001-09 tail_mag cell 5× too big — **82% of it was one bar**: EXEL
2007-10-22 `high=999.99` (yfinance sentinel; real price ~11). `GREATEST(high, close)` does NOT catch
these (low/close are plausible). Fixed at source (user call — a label-side guard would have left the
same bars poisoning M3's high-based features): **`clean_dirty_shares_price.py` part G nulled 178
highs** (high only; open/low/close/volume kept) where `high > 2× GREATEST(open, close)` AND
(`high = 999.99` sentinel OR dollar volume < $50k). Adjudication that shaped the rule:

- **Neighbor isolation is NOT a valid dirt test** — real one-day pump-and-dumps look isolated
  (PHUN 2021-10-22, UPXI 2025-04-21, meme-era AAME/ATCH). **Dollar-volume support is**: real spikes
  trade $100M+; dirt prints trade $0–44k (MRDN vol 0, PED vol 1, reverse-split micro-cap junk). All
  178 nulled bars are sentinel-or-unsupported; every kept flag has real money behind it.
- **AIG's three 999.99 highs are real** (~$50 pre-1:20-split × adjustment ≈ 999.8, ~1× body) — kept
  by the 2×-body condition. The sentinel value alone is not sufficient evidence.
- **Lows deliberately NOT touched**: isolated low dips include real history (UAL 2008-09-08
  false-bankruptcy $3 print, 2010-05-06 Flash Crash, KKR 2015-08-24) — no mechanical separator
  exists; deferred with eyes open (affects future MAE/stop labels, not this one).
- Side-catch: part D would have nulled a **legit** QXO shares row (725M→1.04B Jacobs-era step,
  cap ~$15B; the 100×-median rule misfires on its micro-cap-era median) — whitelisted.

After the source fix the interim label-side guard was **removed** (label is plain
`GREATEST(high, close)` again); audit re-run clean; the M2 table below is **bit-identical** to the
guarded run, confirming guard ≡ source fix on this panel. Registry fingerprint: `c142f255ad71…`.
Home-run rates were never affected (robust stat); M0's decision unaffected.

## M2 — RS-only baseline (no ML): the honesty floor

Full panel 2001–2026, thirds split at 2009-07/2017-12. Lift = bucket mean ÷ universe mean.

**tail_mag_63 lift vs universe:**

| bucket | 2001-09 | 2009-17 | 2018-26 | ALL |
|---|--:|--:|--:|--:|
| D9 | 1.75 | 2.00 | 1.83 | 1.85 |
| D10 | 3.02 | 3.88 | 3.53 | **3.54** |
| top 5% | 3.38 | 4.71 | 4.27 | **4.23** |
| top 2% | 3.14 | 6.05 | 5.27 | **5.09** |

**home_run_63 rate lift vs universe:**

| bucket | 2001-09 | 2009-17 | 2018-26 | ALL |
|---|--:|--:|--:|--:|
| D10 | 2.48 | 2.82 | 2.33 | **2.49** (28.5% vs 11.5%) |
| top 5% | 2.73 | 3.13 | 2.57 | **2.74** |
| top 2% | 2.60 | 3.40 | 2.76 | **2.89** |

- The ramp keeps rising **inside** the top decile (top 2% > top 5% > D10) in 2009+ — RS alone
  concentrates the tail all the way up. In 2001-09 the extreme top compresses slightly (top 2% < top
  5%) — the dot-com/GFC third blunts the very top, consistent with pro-cyclicality
  ([[project_tail_magnitude_objective]]).
- Universe base rates are regime-dependent (11.5% ALL, 8.1% in 2009-17 vs 15.2% in 2018-26); the
  *lift* is what's stable.

**The M3 bar:** the ML ranker must beat, out-of-sample and across start-date variation,
**top-decile tail_mag lift 3.5× / top-5% 4.2×** (home-run lift 2.5×/2.7×). If it can't, ship the
one-column RS rule (plan kill criterion #2).

## Reproduce

- M1: `.venv/Scripts/python.exe scripts/build_m01a_tail_label.py --sample 1500` (read-only; rewrites
  the registry JSON + reruns the audit).
- M2: single read-only query (~5s), session scratchpad `m2_rs_baseline.py` — label CTEs + NTILE(10)
  and PERCENT_RANK() per date on RS_Universe_Rank, GROUPING SETS by (third, bucket).
