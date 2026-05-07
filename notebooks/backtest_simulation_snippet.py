# ==============================================================================
# SEPA BACKTEST — TWO ENGINES
# ==============================================================================
# OPTION A: Vectorized (seconds — for rapid iteration)
# OPTION B: BackTrader SEPAHybridV1 (minutes — for final validation)
# ==============================================================================

import json
from pathlib import Path
import sys

# Resolve pathing for notebook
ROOT = Path().resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ------------------------------------------------------------------------------
# STEP 1: STAGE THE PROTOTYPE MODEL
# ------------------------------------------------------------------------------
# UniverseScorer reads M01 model + metadata from models/m01_prototype/
proto_dir = ROOT / "models" / "m01_prototype"
proto_dir.mkdir(parents=True, exist_ok=True)

model_path = proto_dir / "model.json"
model.save_model(model_path)

meta = {"valid_features": list(selected_features)}
with open(proto_dir / "metadata.json", "w") as f:
    json.dump(meta, f)

print(f"Staged prototype model at: {proto_dir}")


# ============================================================
# OPTION A: FAST VECTORIZED BACKTEST (seconds)
# ============================================================
# Use for parameter sweeps and rapid model iteration.
# Trade-offs: approximate capital constraints, simplified single-exit logic.

from src.backtest import VectorizedSEPABacktest

print("\n--- OPTION A: Vectorized Backtest ---")

vbt = VectorizedSEPABacktest(
    model_path=str(model_path),
    start_date="2020-01-01",
    end_date="2025-01-01",
    min_prob_elite=0.15,
    max_positions_per_day=3,
    ranking_lookback_days=10,
    stop_loss_pct=0.10,
    sma_exit_period=50,
    warmup_days=10,
)
trades = vbt.run()
vbt.summary(trades)

# Uncomment to render interactive tearsheet:
# vbt.tearsheet(trades, benchmark='SPY')


# ============================================================
# OPTION B: FULL BACKTRADER BACKTEST (minutes)
# ============================================================
# Use for final production validation — realistic capital tracking,
# 3-tranche exits, regime gating, commission modeling.

# from scripts.run_backtest import run_backtest_duckdb
#
# print("\n--- OPTION B: SEPAHybridV1 BackTrader ---")
#
# metrics, runner = run_backtest_duckdb(
#     start_date="2020-01-01",
#     end_date="2025-01-01",
#     initial_cash=100000.0,
#     model="m01_prototype",
#     save_report=True,
#     no_plot=False,
#     save_run=False,
#     run_note="prototype_test_1",
#     force_overwrite=True,
# )
#
# runner.generate_tearsheet()   # Optional QuantStats interactive report
