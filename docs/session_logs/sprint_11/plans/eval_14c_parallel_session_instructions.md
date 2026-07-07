# §1.4(c) Parallel-Session Instructions — Deep Rigor Pass on `m01_prototype_may/v2_gated`

> **Goal:** complete the original plan's §8 Definition-of-Done verification for
> `m01_prototype_may/v2_gated` so we have a formal "demote, hold, or promote"
> sign-off backed by bootstrap CI, permutation null, ablation, regime
> decomposition, and decile analysis. This produces the
> `full_eval_report.md` one-pager the original plan called for.
>
> **Why this runs in parallel.** The main session is pivoting to a binary
> Home-Run reformulation (per the 2026-05-24 assessment, multi-class boundaries
> at 10%/30% MFE are in the noise — `Strong` AUC = 0.51). This session
> documents the failure of the 4-class formulation so we have an explicit
> demotion record, not a quiet skip.
>
> **Expected outcome.** A clear **DEMOTE** verdict. Most of the value is the
> evidence trail — bootstrap CI on Sharpe likely straddles zero, permutation
> null likely fails its gate, ablations likely show no single group as a
> load-bearing source of the (already-weak) alpha. If by surprise any of these
> *pass*, escalate — the model is not viable today but the diagnostic could
> reframe what to fix.
>
> **Owner.** Spawn this in a fresh Claude Code session against this repo.
> Estimated wallclock: ~8h (mostly permutation null at 1000 perms).

---

## 0. Preflight (5 min)

```powershell
cd C:\Users\Hang\PycharmProjects\quantamental
.\.venv\Scripts\Activate.ps1

# Confirm the target model exists
Test-Path models\m01_prototype_may\v2_gated\model.json
Test-Path models\m01_prototype_may\v2_gated\evaluation\results.json
Test-Path models\m01_prototype_may\v2_gated\folds\fold_00\model.json
Test-Path models\m01_prototype_may\v2_gated\wf_backtest\summary.json
```

If any path is missing, **stop** — the main-session retrain hasn't landed and
this work has no model to evaluate.

Create the output directory:
```powershell
$EVAL = "models\m01_prototype_may\v2_gated\evaluation"
New-Item -ItemType Directory -Force "$EVAL\full_eval"  | Out-Null
```

---

## 1. Bootstrap CI on the standalone backtest trades  *(~30 min)*

**Where the trades live.** Walk-forward backtest already produced per-fold
trades — concatenate them into one trade list:

```python
# scripts/run_bootstrap_ci.py — write this file
import json
from pathlib import Path
import pandas as pd

from src.evaluation.bootstrap import (
    circular_block_bootstrap, sharpe_from_trades, total_return_from_trades,
)

MODEL_DIR = Path("models/m01_prototype_may/v2_gated")
WF_DIR = MODEL_DIR / "wf_backtest"
OUT = MODEL_DIR / "evaluation" / "full_eval" / "bootstrap_ci.json"

trades = pd.concat([
    pd.read_parquet(fold / "trades.parquet")
    for fold in sorted(WF_DIR.glob("fold_*"))
    if (fold / "trades.parquet").exists()
], ignore_index=True)
print(f"Loaded {len(trades)} trades from {len(list(WF_DIR.glob('fold_*')))} folds")

sharpe_result = circular_block_bootstrap(
    trades, sharpe_from_trades, n_iterations=10_000, seed=42,
)
return_result = circular_block_bootstrap(
    trades, total_return_from_trades, n_iterations=10_000, seed=42,
)

payload = {
    "n_trades": len(trades),
    "n_iterations": 10_000,
    "sharpe": {
        "observed": sharpe_result["observed"],
        "median": sharpe_result["median"],
        "ci_lo_95": sharpe_result["ci_lo"],
        "ci_hi_95": sharpe_result["ci_hi"],
        "gate": sharpe_result["gate"].__dict__,
    },
    "total_return_pct": {
        "observed": return_result["observed"],
        "median": return_result["median"],
        "ci_lo_95": return_result["ci_lo"],
        "ci_hi_95": return_result["ci_hi"],
    },
}
OUT.write_text(json.dumps(payload, indent=2, default=str))
print(f"Wrote {OUT}")
print(f"Sharpe 95% CI: [{sharpe_result['ci_lo']:.3f}, {sharpe_result['ci_hi']:.3f}]")
```

Run:
```powershell
.\.venv\Scripts\python.exe scripts\run_bootstrap_ci.py
```

**Interpret:** If `ci_lo_95 < 0 < ci_hi_95`, the model's edge is statistically
indistinguishable from zero. Record the CI in the one-pager.

---

## 2. Permutation null backtest  *(~6-8h — the long pole)*

**What this tests.** Shuffles which (ticker, date) pairs receive a "buy" signal
within each date, then re-runs the backtest. If the model has no real signal,
the observed Sharpe sits in the middle of the null distribution. Gate passes
if observed percentile > 95.

**Build a signals dataframe from the WF folds.** Aggregate all fold OOS scores
into a single long DF with (`date`, `ticker`, `signal`) where `signal` is
P(Home Run).

```python
# scripts/run_permutation_null.py — write this file
import json
from pathlib import Path
import numpy as np
import pandas as pd
import xgboost as xgb

from src.evaluation.permutation_null import permutation_null_backtest
from src.backtest.runner import SEPABacktestRunner  # adjust if module path differs

MODEL_DIR = Path("models/m01_prototype_may/v2_gated")
DB = Path("data/market_data.duckdb")
OUT = MODEL_DIR / "evaluation" / "full_eval" / "permutation_null.json"
N_PERMS = 1000  # plan §1.4 calls for "deep mode, 1000 perms"
PRODUCTION_CLASS_IDX = 3  # Home Run (last bucket, 4-class label)

# Reuse the SAME signals the WF backtest used — read each fold's trades to
# recover (date, ticker, score) triples. Alternative: regenerate from
# v_d3_deployment + each fold's serialized model.
fold_dirs = sorted((MODEL_DIR / "wf_backtest").glob("fold_*"))
all_signals = []
for fold_dir in fold_dirs:
    trades_path = fold_dir / "trades.parquet"
    if not trades_path.exists():
        continue
    # Trades carry (entry_date, ticker, score); reshape to (date, ticker, signal).
    fold_trades = pd.read_parquet(trades_path)
    # Adjust column names if needed — inspect with: print(fold_trades.columns)
    all_signals.append(fold_trades.rename(columns={"entry_date": "date", "score": "signal"})[["date", "ticker", "signal"]])
signals_df = pd.concat(all_signals, ignore_index=True)
print(f"Signals: {len(signals_df)} rows, {signals_df['date'].nunique()} unique dates")

# Backtest closure — must be DETERMINISTIC. The only randomness comes from
# permutation_null_backtest's internal shuffle.
def backtest_fn(df: pd.DataFrame) -> dict:
    runner = SEPABacktestRunner(
        db_path=DB,
        initial_cash=100_000,
        # Configure to match WF-backtest defaults — same top-N, same hold rules.
    )
    return runner.run_from_signals(df)  # returns {"sharpe_ratio": ..., ...}

result = permutation_null_backtest(
    signals_df=signals_df,
    backtest_fn=backtest_fn,
    n_permutations=N_PERMS,
    seed=42,
    signal_col="signal",
    date_col="date",
    metric_key="sharpe_ratio",
    one_sided=True,
)
OUT.write_text(json.dumps(result, indent=2, default=str))
print(f"observed={result['observed_metric']:.3f}, percentile={result['percentile']:.1f}, gate={result['gate'].status}")
```

**Heads up on runtime.** Each permutation runs the full SEPA backtester end
to end. 1000 perms on the standard runner is the ~8h estimate from the plan.
If it's hitting OOM or hangs, drop to `N_PERMS = 100` ("fast mode") and
document the reduced precision in the one-pager — the plan explicitly allows
this.

**Inspect signals columns first.** Before running 1000 perms, run a single
perm and confirm `trades.parquet` actually has `entry_date` and `score`
columns. If they're named differently (`date`, `prob_home_run`, etc.), adjust
the rename map. Run:

```powershell
.\.venv\Scripts\python.exe -c "import pandas as pd; print(pd.read_parquet('models/m01_prototype_may/v2_gated/wf_backtest/fold_00/trades.parquet').columns.tolist())"
```

Then:
```powershell
.\.venv\Scripts\python.exe scripts\run_permutation_null.py
```

**Interpret:** percentile > 95 → real edge; percentile in [50, 95] → "could
be luck"; percentile < 50 → model is anti-skilled at this metric.

---

## 3. Ablation backtest  *(~2-3h)*

**Already has a CLI** — `scripts/ablation_backtest.py`. Feature groups should
correspond to entries in `model_feature_sets.feature_group`. Inspect them
first:

```powershell
.\.venv\Scripts\python.exe -c "import duckdb; con = duckdb.connect('data/market_data.duckdb', read_only=True); print(con.execute(\"SELECT DISTINCT feature_group FROM model_feature_sets WHERE feature_set_id = 'fs_m01_prototype' ORDER BY feature_group\").fetchall())"
```

Then run ablation for each substantive group (typical groups: `momentum`,
`volume`, `volatility`, `fundamentals`, `regime_context`, `cross_sectional`):

```powershell
.\.venv\Scripts\python.exe scripts\ablation_backtest.py `
  --model-version v2_gated `
  --model-name m01_prototype_may `
  --feature-set fs_m01_prototype `
  --feature-groups "momentum,volume,volatility,fundamentals,regime_context,cross_sectional" `
  --output models\m01_prototype_may\v2_gated\evaluation\full_eval\ablation\ `
  --backtest-start 2023-05-01 `
  --backtest-end 2026-05-22
```

Adjust the group names to match what the catalog actually has (the
inspection query above is the source of truth).

**Interpret:** look at `ablation_summary.json::deltas`. If removing any single
group drops Sharpe by ≥0.3 in absolute terms, that group is load-bearing. If
all deltas are within ±0.15, the model has diffuse signal (or none) —
common with weak models, and consistent with the multiclass collapse we've
already seen.

---

## 4. Per-regime AUC check  *(~10 min)*

This was already wired into the main training run via `--with-regime-decomp`,
but verify the gate result:

```powershell
.\.venv\Scripts\python.exe -c @'
import json
res = json.load(open(r'models\m01_prototype_may\v2_gated\evaluation\results.json'))
for gate in res.get('gates', []):
    if 'regime' in gate.get('name', '').lower():
        print(f"{gate['name']:40s} {gate['status']:6s} value={gate.get('value', 'n/a')}")
metrics_by_regime = res.get('metrics_by_regime', {})
for regime, stats in metrics_by_regime.items():
    auc = stats.get('roc_auc_Home Run (>30%)')
    print(f"Regime {regime}: AUC(Home Run) = {auc}, n = {stats.get('n', '?')}")
'@
```

**Plan gate:** Per-regime AUC ≥ 0.55 in at least 3 of 5 regimes. Record which
regimes pass / fail in the one-pager.

---

## 5. Decile analysis (Information Coefficient)  *(~30 min)*

For each WF fold, bucket OOS predictions into deciles by P(Home Run), compute
mean realized MFE per decile. A working model has monotone decile means —
top decile delivers higher MFE than bottom.

```python
# scripts/run_decile_analysis.py — write this file
import json
from pathlib import Path
import numpy as np
import pandas as pd
import xgboost as xgb
from scipy.stats import spearmanr
import duckdb

MODEL_DIR = Path("models/m01_prototype_may/v2_gated")
OUT = MODEL_DIR / "evaluation" / "full_eval" / "decile_analysis.json"
DB = Path("data/market_data.duckdb")

# Pull fold-by-fold OOS predictions. Easiest: re-score each fold's test slice
# with that fold's frozen model.json and join MFE outcomes from v_d2_training.
folds_dir = MODEL_DIR / "folds"
panel = []
con = duckdb.connect(str(DB), read_only=True)

for fold_dir in sorted(folds_dir.glob("fold_*")):
    spec = json.loads((fold_dir / "spec.json").read_text())
    booster = xgb.Booster()
    booster.load_model(str(fold_dir / "model.json"))

    # Pull this fold's test rows from v_d2_training. NOTE: must match the same
    # feature_version + min_date as the trainer used.
    df = con.execute("""
        SELECT * FROM v_d2_training
        WHERE feature_version = 'v3.1'
          AND date BETWEEN ? AND ?
          AND mfe_pct IS NOT NULL
    """, [spec["test_start"], spec["test_end"]]).df()

    # Score (you'll need to reattach categorical mapping — see categorical_mapping.json).
    # If this gets fiddly, fall back to reading the WF-backtest trades for prob_home_run instead.
    # ... scoring code here ...
    # panel.append(df_with_scores)

# Decile by score, compute mean MFE per decile
all_scored = pd.concat(panel, ignore_index=True)
all_scored["decile"] = pd.qcut(all_scored["score"], 10, labels=False, duplicates="drop")
decile_stats = all_scored.groupby("decile").agg(
    n=("mfe_pct", "size"),
    mean_mfe=("mfe_pct", "mean"),
    home_run_rate=("mfe_pct", lambda x: (x > 30).mean()),
).reset_index()

# Spearman rank correlation between decile and outcome (= IC)
rho, p = spearmanr(all_scored["score"], all_scored["mfe_pct"])

OUT.write_text(json.dumps({
    "decile_stats": decile_stats.to_dict(orient="records"),
    "spearman_ic": float(rho),
    "p_value": float(p),
    "n_predictions": len(all_scored),
}, indent=2, default=str))
print(f"Spearman IC = {rho:.4f} (p = {p:.4f})")
print(decile_stats.to_string())
```

**Interpret:**
- Monotone deciles → real signal.
- Top decile home-run rate ≥ 2× bottom → tradable edge.
- Spearman IC > 0.05 with p < 0.01 → statistically significant ranking power.

If the scoring code in §5 turns into a yak shave, **the WF-backtest trades
already contain `score` and `mfe_pct` columns** (or close analogues — inspect
`trades.parquet`). Use those instead of rescoring from scratch.

---

## 6. The one-pager  *(~30 min)*

Write `models/m01_prototype_may/v2_gated/evaluation/full_eval/full_eval_report.md`.
Template:

```markdown
# m01_prototype_may/v2_gated — Full Evaluation Report

**Generated:** <date>
**Verdict:** DEMOTE / HOLD / PROMOTE (pick one)

## Headline gates

| Gate | Threshold | Observed | Status |
|---|---|---|---|
| WF worst-fold AUC (Home Run) | ≥ 0.65 | <val> | <pass/fail> |
| WF backtest mean Sharpe | > 0.5 | <val> | <pass/fail> |
| WF backtest worst Sharpe | > −0.3, ≥3/4 positive | <val> | <pass/fail> |
| WF backtest worst max DD | < 35% | <val> | <pass/fail> |
| WF backtest mean top-3 home-run lift | > 5× | <val> | <pass/fail> |
| Bootstrap CI lower bound on Sharpe | > 0 | <val> | <pass/fail> |
| Permutation null percentile | > 95 | <val> | <pass/fail> |
| Per-regime AUC ≥ 0.55 in ≥3/5 regimes | yes | <count> | <pass/fail> |
| Spearman IC | > 0.05, p < 0.01 | <val> | <pass/fail> |

## Bootstrap CI
- N trades: <n>
- Sharpe observed: <val>
- Sharpe 95% CI: [<lo>, <hi>]
- Total return 95% CI: [<lo>, <hi>]
- Interpretation: <one sentence>

## Permutation null
- N permutations: <n>
- Observed Sharpe: <val>
- Null median: <val>
- Percentile: <val>
- Interpretation: <one sentence>

## Ablation
| Feature group | Δ Sharpe vs full | Δ Return vs full |
|---|---|---|
| momentum | ... | ... |
| ... | ... | ... |
- Load-bearing groups (|Δ Sharpe| ≥ 0.3): <list or "none">
- Interpretation: <one sentence>

## Per-regime AUC
| Regime | n | AUC(Home Run) |
|---|---|---|
| 0 | ... | ... |
| ... | ... | ... |
- Regimes passing 0.55: <count>/5

## Decile analysis
| Decile | n | Mean MFE | Home-Run rate |
|---|---|---|---|
| 0 | ... | ... | ... |
| ... | ... | ... | ... |
- Spearman IC: <val> (p = <val>)
- Monotone: <yes/no>
- Interpretation: <one sentence>

## Conclusion

<2-3 sentences. Reference the binary-label reformulation that is happening in
parallel — this report is the demotion record for the 4-class formulation, not
a recommendation to invest more in it.>
```

---

## 7. Acceptance criteria

This session is done when:

1. `models/m01_prototype_may/v2_gated/evaluation/full_eval/` contains:
   - `bootstrap_ci.json`
   - `permutation_null.json`
   - `ablation/ablation_summary.json` (plus the plot the CLI emits)
   - `decile_analysis.json`
   - `full_eval_report.md`
2. The one-pager has a clear verdict (DEMOTE / HOLD / PROMOTE) with the gate
   table filled in.
3. If any gate **passes against expectation** — call this out at the top of
   the one-pager. It could change the strategy for the binary reformulation.

---

## 8. Things this session must NOT do

- Do **not** retrain the model. The whole point of §1.4(c) is verifying the
  already-trained model.
- Do **not** touch the binary-label reformulation work in the main session —
  that's a different label_id, different model_dir, and is its own decision.
- Do **not** promote anything. `promote_prod` is the main-session call after
  the binary model is also evaluated.
- Do **not** delete or modify any existing artifacts under
  `models/m01_prototype_may/v2_gated/` — only write under `evaluation/full_eval/`.

---

## 9. Known gotchas (from main-session investigation)

- **`v_d2_training` cache.** The training script reads via
  `d2_training_cache` (materialized). If you regenerate signals from
  `v_d2_training` directly, results may not match the fold's trained model.
  Prefer reading `trades.parquet` from `wf_backtest/fold_*/`.
- **Categorical mapping.** `sector`/`industry` are XGBoost categoricals.
  If rescoring from scratch in §5, load `categorical_mapping.json` and
  reapply category codes — out-of-vocab tickers will produce wrong scores.
- **`SEPABacktestRunner` runtime.** Each call is ~30s on a 3-year window.
  At 1000 perms, that's ~8h. If you need to cut this short, use 100 perms
  ("fast mode" per plan §1.4) and note it in the report.
- **WF fold 3 is degenerate.** Only 21 days of test data, 0 trades. Most
  per-fold metrics for fold 3 are `null` — handle gracefully (skip in
  aggregations rather than NaN-poisoning).
