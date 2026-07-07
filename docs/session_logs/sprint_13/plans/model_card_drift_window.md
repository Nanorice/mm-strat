# Model Card Drift Window — Design & Future Work

**Status:** (a) shipped 2026-06-12 · (b) proposed
**Owner:** Hang
**Related:** `src/orchestrators/daily_pipeline_orchestrator.py::_run_phase_10_model_card`,
`src/evaluation/model_card/sections/section_g_edge.py`

## Context

Phase 10 of the daily pipeline rebuilds a **model card** for the frozen prod
model. The model is never retrained here — the card re-runs inference over an
evaluation window and recomputes Sections A–G + benchmarks. It answers:
*"Does this frozen model's measured behavior still hold up on fresh data?"*

### The problem with a full-history window
`load_eval_data` defaults to the entire history (2001–present, ~37.9K SEPA
rows over 5,645 trading days). The model's training span (2003–2026) overlaps
this almost entirely, so each weekly rebuild dilutes a sliver of genuinely-new
post-training data into 20+ years. A real regime break in the latest week
barely moves the aggregate verdict. As wired originally, the weekly card was a
"hasn't gone stale" smoke test, not a drift alarm.

Two distinct cards, two distinct purposes:
- **Gate card** (`model_card_path`): full-history, authoritative promotion verdict.
- **Drift card** (`model_card_drift_path`): recency-focused monitoring artifact.

These must not share a path — overwriting the gate card with a recency-only
verdict would weaken the promotion gate.

## (a) Trailing 1-year window — SHIPPED 2026-06-12

Phase 10 builds a drift card over `[target_date − 365d, target_date]` and
registers it to `model_card_drift_path` (separate from the gate card).

- Row support: the card reads from **`d2_training_cache`** (the labeled
  outcome set), NOT raw `t3_sepa_features`. Measured 1-year window =
  **2,470 rows / 453 positives / 237 days** (build 2026-06-12). This is thin —
  near the lower bound for Section G's 500-perm / 500-bootstrap resampling; the
  band came back `WEAK`. (An earlier estimate of ~603K cited t3_sepa_features
  by mistake — irrelevant, since the cache is what feeds the card.)
- Build time: full-history = 2,780s; 1-year window = **157s** (n_days 5,645 →
  237 is the cost lever). Comfortably inside the 1,800s timeout.
- New registry columns: `model_card_drift_path`, `model_card_drift_built_at`.
- New methods: `ModelRegistry.register_drift_card`, `get_drift_card_info`,
  `get_model_slug`.
- Freshness gate: skip if a drift card was built in the last 7 days.
- Subprocess timeout raised 600s → 1800s (full-history build measured 2,780s;
  the 1y window is materially smaller but Section G is still the cost driver).

### Limitation of (a)
A hard 365-day cutoff is discontinuous: everything at day 366 is discarded,
and the window edge can wobble the verdict when a notable day rolls in/out.
It also weights all in-window days equally, so a shift in the most recent
weeks is averaged against data up to a year old.

**Power is the real constraint** (measured, not theoretical): the 1-year cache
window is only ~2.5K rows / ~450 positives, and the band came back WEAK. This
strengthens the case for (b) — a hard window that's short enough to be
recency-sensitive is also short enough to be underpowered. A decay weight over
a LONGER horizon may give both recency-sensitivity AND usable n. Consider also
whether the drift card should widen to 18m/2y to recover power, accepting less
recency focus.

## (b) Recency-weighted bootstrap — FUTURE DEV

Instead of (or in addition to) a hard window, keep more history but weight
recent observations more heavily in Section G's permutation/bootstrap.

### Sketch
- **Block bootstrap (Section G):** replace uniform block sampling with a
  sampling probability that decays with block age (e.g. exponential half-life
  of ~90 trading days). Recent regime gets more influence; long-run signal is
  attenuated, not deleted.
- **Permutation test:** the label-shuffle null must stay valid under weighting
  — weight the test statistic consistently under both observed and permuted
  assignments, or the p-value is biased. Needs care; validate against a known
  null (shuffled outcomes should still yield ~uniform p-values).
- **Knobs:** half-life (days), optional hard horizon cap (e.g. drop >3y).
- **Touch points:** `section_g_edge.py` sampler; expose CLI flags on
  `build_model_card.py` (`--recency-half-life`, default off = uniform).

### Open questions
1. Is a smooth decay actually more interpretable to the operator than a fixed
   window, or just harder to reason about? Consider shipping (a) and observing
   how jumpy the fixed-window verdict is before investing in (b).
2. Should the drift card report BOTH uniform and weighted Section G stats
   side-by-side so the operator sees the recency effect explicitly?
3. Power: does down-weighting old data effectively shrink n enough to widen
   CIs beyond usefulness? Check effective sample size at the chosen half-life.

### Effort estimate
~0.5–1 day: sampler change + permutation-validity check + CLI plumbing +
a null-calibration test.
