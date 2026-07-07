# T1.1 Quality Gate — Patch Plan

> Date: 2026-05-17
> Scope: Surgical patch to make the existing T1 audit meaningful inside the daily run, and fix the
> yfinance all-or-nothing failure mode. No new architecture. No behavioural changes to phases 2–8.
> Prerequisite for the full T1.1 plan described in `system_design_review_action_plan_2026_05_16.md`.

> **Review revision 2026-05-17**: 4 correctness/consistency issues from code review folded in
> (see inline `[REVIEW]` notes in Steps 2 and 4). One new step added (Step 0 — logging hygiene)
> after inspecting actual per-run console output.

---

## Review corrections applied

| # | Issue | Resolution |
|---|---|---|
| 1 | `phase_1_only` returns at `run_pipeline` L180–181 **before** Phase 2 — original wiring with `if not phase_1_only:` meant Phase 1.5 never ran in `--phase-1-only` mode (the mode where the gate matters most) | Phase 1.5 now inserted at L179, **before** the `if phase_1_only: return`, with **no** `phase_1_only` guard |
| 2 | `phase_1_5_quality_gate` added to `PIPELINE_FAILURE_MODES` but Phase 1.5 bypasses `_execute_phase`, which is the only reader of that dict → dead config | **Dropped** the config entry. Step 5 deleted. The "never halts" contract lives in the docstring, enforced by construction |
| 3 | Step 2 retry sketch never flipped `results[ticker] = True` on recovered tickers → `update_cache:977` would still mark them errored in `last_errors` even though their rows were written | Retry extraction loop is now **identical** to the first pass, including `results[ticker] = True` |
| 4 | `_compute_price_coverage` uses *exact-day* presence; `audit_t1_data_quality.py` uses a *5-business-day* window (`STALE_PRICE_DAYS`). Centralising the threshold while forking the coverage definition reintroduces the fragmentation this patch claims to kill | Coverage definition explicitly documented as **exact-day** (correct for a same-run gate) with an explicit note that it differs from the audit tool's 5-day staleness window — by design, documented, not silent |

---

## Problem Summary

Three independent issues found during review. They compound: the retry loop planned for T1.1
is useless until issue 2 is fixed.

### Issue 1 — Threshold fragmentation (3 numbers for one concept)

| Location | Threshold | Meaning |
|---|---|---|
| `tools/audit_t1_data_quality.py:29` | 80% | Warn if price coverage below this |
| Plan doc T1.1 | 95% | Retry gate trigger |
| `orchestrators/daily_pipeline_orchestrator.py:869` | 99% | Phase 8 T2 coverage alert |

These are different concepts (T1 raw ingestion vs T2 computed features), but the 80% vs 95%
conflict is between the audit tool and the plan. A Phase 1.5 that retries on `<95%` while the
audit tool only warns at `<80%` would HALT when the audit says OK. The audit threshold needs to
be a named constant in `config.py`, not a hardcoded literal.

### Issue 2 — yfinance path has no per-ticker isolation

`DataRepository._update_cache_yfinance()` (`src/data_engine.py:1203`) issues one `yf.download()`
for all stale tickers. One 429 / connection timeout fails the entire call and marks **every**
ticker as `False`. The orchestrator then logs a warning and continues — downstream phases compute
features on yesterday's prices for all stale tickers.

The FMP path already has a two-pass retry with `max_workers=3` on the second pass. yfinance has
nothing equivalent.

### Issue 3 — Same-run recovery is "retry next run"

When >50% of price tickers fail (`orchestrators/daily_pipeline_orchestrator.py:489`), the
orchestrator logs `"will retry next run"` and proceeds. There is no same-run re-attempt.
Any Phase 1.5 retry loop needs a hook to re-trigger ingestion for the failed subset before the
audit runs.

---

## What this patch does NOT touch

- Phase 2 through Phase 8 — zero changes
- `PIPELINE_FAILURE_MODES` for existing phases — unchanged
- FMP ingestion path — already has retry, leave it
- `tools/audit_t1_data_quality.py` logic — no new checks added
- Orchestrator public API (`run_pipeline` signature) — unchanged

---

## Patch Steps

### Step 0 — Daily pipeline logging hygiene (do this first)

**Files**: `scripts/run_daily_pipeline.py`, `src/feature_pipeline.py`

**Assessment (grep-verified, not opinion).** The orchestrator itself logs cleanly — exactly one
`[Phase N] ...` summary line per phase at INFO, with all verbose detail correctly demoted to
`.debug()`. The console noise comes from **two specific sources**, neither of which is pipeline
logic:

1. **No third-party log suppression.** `scripts/run_daily_pipeline.py:28-36` sets the root logger
   to `INFO` and never raises the level for `yfinance`, `urllib3`, `requests`, or `peewee`.
   The yfinance bulk-download path emits one INFO line per ticker; with ~180+ stale tickers on a
   first/gap run, that buries every useful `[Phase N]` line. **This directly degrades the new
   Phase 1.5 signal**, which logs around the same yfinance path — hence fixing it belongs in
   this patch, not later.

2. **`src/feature_pipeline.py` uses `print()` instead of `logger`** — 24 raw `print()` calls
   (L102–L1523: `[T2]`, `[T3]`, `[B]`, `[C]` progress lines). These bypass the level filter
   entirely: always rendered, no timestamp, no level tag, impossible to route to file-only or
   silence. This is the single largest fixable source of Phase 5 console clutter.

**Fix 0a — suppress noisy libraries** (`run_daily_pipeline.py`, immediately after `basicConfig`):

```python
for _noisy in ("yfinance", "urllib3", "requests", "peewee"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)
```

**Fix 0b — route `feature_pipeline.py` progress through the module logger**. Replace the 24
`print(...)` calls with `logger.info(...)` / `logger.warning(...)` / `logger.error(...)` matching
the existing `[OK]` / `[WARN]` / `[ERROR]` prefixes. No message wording changes — only the sink.
This makes every Phase 5 line timestamped, level-tagged, and filterable, and keeps it in the
per-run log file alongside everything else.

**Explicitly NOT in scope**: changing what the orchestrator logs (it is already correct), adding
a `--quiet`/`--verbose` flag (the existing `--debug` at L124 already flips the root level), or
restructuring the log format.

**Acceptance**:
- A normal daily run prints **one line per phase** to the console (≤ ~15 lines total for phases
  1–8), no per-ticker yfinance spam.
- `--debug` still surfaces the full detail (DEBUG lines + library DEBUG) as before.
- The per-run log file content is unchanged or richer (feature_pipeline lines now captured there
  too), never poorer.

---

### Step 1 — Centralise the T1 price coverage threshold in `config.py`

**File**: `config.py`

Add one constant to the `PIPELINE_ALERT_THRESHOLDS` block:

```python
PIPELINE_ALERT_THRESHOLDS = {
    'breakout_drought_days': 5,
    'failure_rate_threshold': 0.1,
    't1_price_coverage_warn_pct': 80.0,   # ADD: audit warn threshold
    't1_price_coverage_retry_pct': 90.0,  # ADD: Phase 1.5 retry trigger
}
```

Then update `audit_t1_data_quality.py:29` to read from config instead of the hardcoded `80.0`:

```python
from config import PIPELINE_ALERT_THRESHOLDS
MIN_PRICE_COVERAGE_PCT = PIPELINE_ALERT_THRESHOLDS['t1_price_coverage_warn_pct']
```

The 95% in the plan doc was aspirational. 90% is the right retry trigger: strict enough to catch
a partial yfinance failure (~180 tickers missing), loose enough not to fire on normal delisting
churn. The warn threshold stays at 80% (below 90% means the retry already fired and failed).

**Acceptance**: `python tools/audit_t1_data_quality.py` still runs identically; both thresholds
are readable from one place.

---

### Step 2 — Add batched retry to `_update_cache_yfinance()`

**File**: `src/data_engine.py`, method `_update_cache_yfinance()`

Split the single bulk `yf.download()` into sequential batches of 200 tickers. On exception, mark
only that batch as failed and continue with the next. After all batches complete, collect the
failed tickers and retry them once in batches of 50 with a 15s sleep before the retry pass.

Sketch of the change (replace the single `try/except yf.download()` block):

```python
BATCH_SIZE = 200
RETRY_BATCH_SIZE = 50
RETRY_SLEEP_S = 15

all_failed: list[str] = []

for i in range(0, len(tickers), BATCH_SIZE):
    batch = tickers[i : i + BATCH_SIZE]
    try:
        data = yf.download(batch, start=from_date, end=end_date,
                           group_by='ticker', auto_adjust=True,
                           progress=False, threads=True)
        # ... existing per-ticker extraction loop ...
    except Exception as e:
        logger.warning(f"yfinance batch {i//BATCH_SIZE + 1} failed: {e}")
        for ticker in batch:
            results[ticker] = False
            all_failed.append(ticker)

# Retry pass — once, smaller batches
if all_failed:
    logger.info(f"yfinance retry: {len(all_failed)} tickers ({RETRY_SLEEP_S}s cooldown)")
    time.sleep(RETRY_SLEEP_S)
    for i in range(0, len(all_failed), RETRY_BATCH_SIZE):
        batch = all_failed[i : i + RETRY_BATCH_SIZE]
        try:
            data = yf.download(batch, start=from_date, end=end_date,
                               group_by='ticker', auto_adjust=True,
                               progress=False, threads=True)
            # [REVIEW #3] Extraction loop MUST be byte-identical to the first
            # pass, including `results[ticker] = True` on success. Otherwise a
            # ticker whose data is recovered here lands in `buffer` (and gets
            # written by _flush_buffer) but stays results=False, so
            # update_cache:977 wrongly reports it in `last_errors`.
            for ticker in batch:
                ticker_data = self._extract_ticker_from_batch(data, ticker)
                if ticker_data is not None and not ticker_data.empty:
                    buffer.append((ticker, ticker_data))
                    results[ticker] = True       # <-- the critical line
                # else: leave results[ticker] = False (set in first pass)
        except Exception as e:
            logger.warning(f"yfinance retry batch failed: {e}")
            # results[ticker] already False — no change needed
```

> **[REVIEW #3]** The original sketch elided the retry success path with
> `# ... same per-ticker extraction loop ...`, which read as "no change needed".
> That is only true for the *failure* path. The success path **must** flip
> `results[ticker] = True`, or recovered tickers are written to `price_data`
> yet still counted as failures by the caller.

**Why 200 / 50**: yfinance bulk downloads above ~300 tickers become unreliable (empirically).
200 is safe for the first pass. 50 for retries trades speed for reliability.

**Performance impact**: For a normal daily run with ~50–100 stale tickers, everything fits in
one batch — no change. Batching only kicks in on first run or after a multi-day gap.

**Acceptance**: Kill the network mid-download (`yf.download` raises `requests.exceptions.ConnectionError`).
Only the in-flight batch marks tickers failed; earlier batches' data is already in the buffer.

---

### Step 3 — Expose failed tickers from `update_cache()` to the orchestrator

**File**: `src/data_engine.py`, method `update_cache()`

The orchestrator already reads `self.data_repo.last_errors` (`orchestrators/daily_pipeline_orchestrator.py:485`).
`last_errors` is a list of `(ticker, error_msg)` tuples. This already works for the FMP path.
For the yfinance path it's already populated at line 977.

No change needed here — the hook already exists.

---

### Step 4 — Add Phase 1.5 to the orchestrator

**File**: `src/orchestrators/daily_pipeline_orchestrator.py`

Insert between Phase 1 and Phase 2. Phase 1.5 is a plain method, not wrapped in `_execute_phase`
(because it doesn't write rows — it reads and decides).

> **[REVIEW #2]** Because it bypasses `_execute_phase`, **do not** add a
> `PIPELINE_FAILURE_MODES` entry for it. That dict is read *only* inside the
> `_execute_phase` / HALT path (orchestrator L176, L497); an entry nothing
> consults is misleading dead config. The "never halts" contract is enforced
> structurally (the method has no `raise`) and stated in the docstring.

It should:

1. Compute current price coverage for `target_date` against `company_profiles`.
2. If coverage < `t1_price_coverage_retry_pct` (90%), re-run ingestion for the failed subset.
3. Re-check coverage.
4. If still below threshold, log a structured WARNING and set a flag — do NOT halt.
   The existing HALT mode for Phase 1 already covers catastrophic failure; Phase 1.5 handles
   partial failures that don't raise exceptions.

```python
def _run_phase_1_5_quality_gate(
    self,
    target_date: str,
    latest_trading_day: str,
) -> Dict:
    """
    Phase 1.5: T1 price coverage gate + same-run retry for partial failures.
    Read-only check + targeted re-ingest. Never halts — warns and records.
    """
    from config import PIPELINE_ALERT_THRESHOLDS
    retry_threshold = PIPELINE_ALERT_THRESHOLDS['t1_price_coverage_retry_pct']

    coverage_pct = self._compute_price_coverage(latest_trading_day)
    logger.info(f"[Phase 1.5] Price coverage: {coverage_pct:.1f}%")

    if coverage_pct >= retry_threshold:
        return {'coverage_pct': coverage_pct, 'retry': False, 'status': 'ok'}

    # Identify tickers missing for latest_trading_day
    missing = self._get_missing_price_tickers(latest_trading_day)
    logger.warning(
        f"[Phase 1.5] Coverage {coverage_pct:.1f}% < {retry_threshold}% — "
        f"retrying {len(missing)} tickers"
    )

    if missing:
        self.data_repo.update_cache(
            tickers=missing,
            source='yfinance',
            latest_trading_day=latest_trading_day,
        )

    coverage_pct_after = self._compute_price_coverage(latest_trading_day)
    logger.info(f"[Phase 1.5] Coverage after retry: {coverage_pct_after:.1f}%")

    warn_threshold = PIPELINE_ALERT_THRESHOLDS['t1_price_coverage_warn_pct']
    if coverage_pct_after < warn_threshold:
        logger.warning(
            f"[Phase 1.5] Coverage still {coverage_pct_after:.1f}% after retry — "
            f"downstream features will use stale prices for {len(missing)} tickers"
        )

    return {
        'coverage_pct': coverage_pct_after,
        'retry': True,
        'missing_count': len(missing),
        'status': 'warned' if coverage_pct_after < warn_threshold else 'recovered',
    }
```

Two helper methods to add (both are simple SQL queries):

```python
def _compute_price_coverage(self, trading_day: str) -> float:
    """
    % of active tickers with a price row EXACTLY ON trading_day.

    [REVIEW #4] This is an exact-day predicate, deliberately stricter than
    audit_t1_data_quality.py's STALE_PRICE_DAYS=5 business-day window. A
    same-run gate wants *today's* prices, not "traded sometime this week" —
    a ticker last seen 3 days ago is fine for the audit's staleness check
    but is exactly what Phase 1.5 must re-ingest. The two definitions are
    intentionally different; Step 1 centralises the THRESHOLD numbers, not
    the coverage predicate. This divergence is documented, not silent.
    """
    with duckdb.connect(self.db_path, read_only=True) as con:
        total, covered = con.execute("""
            SELECT
                (SELECT COUNT(*) FROM company_profiles WHERE is_active = TRUE),
                COUNT(DISTINCT p.ticker)
            FROM price_data p
            INNER JOIN company_profiles cp ON p.ticker = cp.ticker
            WHERE cp.is_active = TRUE AND p.date = ?
        """, [trading_day]).fetchone()
    return (covered / total * 100) if total else 100.0

def _get_missing_price_tickers(self, trading_day: str) -> list[str]:
    """Active tickers with no price row on trading_day."""
    with duckdb.connect(self.db_path, read_only=True) as con:
        rows = con.execute("""
            SELECT cp.ticker
            FROM company_profiles cp
            LEFT JOIN price_data p
              ON p.ticker = cp.ticker AND p.date = ?
            WHERE cp.is_active = TRUE AND p.ticker IS NULL
            ORDER BY cp.ticker
        """, [trading_day]).fetchall()
    return [r[0] for r in rows]
```

Wire Phase 1.5 into `run_pipeline()`. **[REVIEW #1]** The exact insertion point matters:
`run_pipeline` does `if phase_1_only: return critical_success` at **L180–181**, which is
*after* the Phase 1 `_execute_phase` block (L169–178) but *before* Phase 2 (L183+).

Insert Phase 1.5 at **L179** — after Phase 1 completes, **before** the `phase_1_only`
early-return — with **no `phase_1_only` guard**. The original `if not phase_1_only:` was wrong:
it would skip the gate precisely in `--phase-1-only` mode, the ingestion-debugging mode where
the coverage gate is most useful.

```python
            run_stats['phase_1'] = phase_stats
            if not phase_success and PIPELINE_FAILURE_MODES.get("phase_1_t1_price") == PipelineFailureMode.HALT:
                critical_success = False
                return False

            # Phase 1.5: T1 Price Quality Gate (read + conditional retry — non-blocking).
            # Runs in --phase-1-only mode too (placed BEFORE the early return below).
            stats_1_5 = self._run_phase_1_5_quality_gate(target_date, actual_trading_day)
            run_stats['phase_1_5'] = stats_1_5

            if phase_1_only:
                return critical_success
```

> **[REVIEW #2]** No `PIPELINE_FAILURE_MODES` entry is added — see the note under
> "Add `_run_phase_1_5_quality_gate`" above. Phase 1.5 never halts by construction.

**Acceptance**:
- Normal run (all tickers fresh): Phase 1.5 logs coverage ≥ 90%, no retry, proceeds in <1s.
- Partial failure run (simulate by deleting 150 rows from `price_data` for latest date):
  Phase 1.5 detects gap, retries those 150 tickers, logs final coverage.
- Phase 2 through 8 unaffected in both cases.

---

### Step 5 — ~~Add `config.py` failure mode entry~~ **REMOVED (review #2)**

Deleted. The original Step 5 added `"phase_1_5_quality_gate": PipelineFailureMode.WARN` to
`PIPELINE_FAILURE_MODES`. That dict is consulted **only** by the `_execute_phase` / HALT path,
which Phase 1.5 deliberately bypasses. An unread config entry is dead config that misleads future
readers into thinking the failure mode is wired. Phase 1.5's non-blocking contract is enforced by
construction (no `raise`) and documented in its docstring — no config needed.

---

## What this patch deliberately defers

| Deferred item | Why |
|---|---|
| `--exit-on-fail` flag on audit tool | `--warn-only` already does this; redundant |
| Running `audit_t1_data_quality.py` inside the DAG | Overkill for a patch — the audit is a CLI diagnostic. Phase 1.5 replaces it with targeted SQL checks |
| Fundamentals / shares / macro coverage gates | Phase 1.5 covers price only — those tables are WARN-mode and tolerate staleness |
| Automatic HALT on coverage failure | Explicit design choice: patch is non-blocking. Full automation (T1.1) adds the HALT after this patch is validated in production |
| `trend_exit_ok` materialisation (T1.2) | Separate task, no dependency on this patch |
| Invariant audits (T1.3) | Separate task |

---

## File change summary

| File | Change |
|---|---|
| `scripts/run_daily_pipeline.py` | **Step 0**: suppress `yfinance`/`urllib3`/`requests`/`peewee` to WARNING (4-line loop after `basicConfig`) |
| `src/feature_pipeline.py` | **Step 0**: replace 24 `print()` calls with `logger.{info,warning,error}` (sink change only, no wording change) |
| `config.py` | Add 2 threshold constants. ~~failure mode entry~~ **removed (review #2)** |
| `tools/audit_t1_data_quality.py` | Read `MIN_PRICE_COVERAGE_PCT` from config (1-line change) |
| `src/data_engine.py` | Replace single `yf.download()` with batched loop + retry pass in `_update_cache_yfinance()`; retry success path flips `results[ticker]=True` (review #3) |
| `src/orchestrators/daily_pipeline_orchestrator.py` | Add `_run_phase_1_5_quality_gate()`, `_compute_price_coverage()`, `_get_missing_price_tickers()`; wire Phase 1.5 at L179, **before** the `phase_1_only` return, no guard (review #1) |

**Total estimated effort**: 4–5 hours (Step 0 adds ~1h: the `feature_pipeline.py` print→logger
sweep is 24 mechanical edits + a Phase 5 smoke run to confirm no message regressions).
**Risk to existing pipeline**: Low. Phase 1.5 is read-mostly; the yfinance batching change is
additive (normal daily runs hit one batch, no behaviour change); Step 0 is a logging-sink change
with zero logic impact (verify the per-run log file is unchanged-or-richer, never poorer).

---

## Sequencing relative to T1.1 full plan

```
This patch ──▶ Validate in 3-5 daily runs ──▶ T1.1 (add HALT mode + audit_t1 in DAG)
                                           ──▶ T1.2 (trend_exit_ok)
                                           ──▶ T1.3 (invariant audits)
```

The patch is a prerequisite for T1.1: without the batched yfinance retry, the T1.1 retry loop
retries an all-or-nothing call and recovers nothing.
