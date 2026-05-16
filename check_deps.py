import os
import re

legacy_modules = [
    "daily_scanner_duckdb", "data_curator_duckdb", "features", "features_stub",
    "feature_config", "feature_preprocessor", "feature_rehydrator", "alpha_factors",
    "cross_sectional_features", "indicators", "dataset_merger", "dataset_rehydrator",
    "fundamental_merger", "fundamental_processor", "fundamental_column_mapping",
    "vectorized_screening", "triple_barrier_labeler", "database", "database_duckdb",
    "buy_list_manager", "backtester", "trade_simulator", "trade_simulator_fast",
    "strategy", "trading_config", "ticker_filter", "temporal_validator",
    "evaluate_model", "ml_scorer", "model_preparation", "train_model", "reporting",
    "dashboard_reports", "base_evaluator", "classification_report", "errors",
    "feature_analyzer", "feature_screener", "m01_evaluator", "m03_grid_search",
    "metrics", "plotting", "ranking", "reports", "targets"
]

pattern = re.compile(r"^(?:from\s+[\w\.]*\b(" + "|".join(legacy_modules) + r")\b\s+import|import\s+[\w\.]*\b(" + "|".join(legacy_modules) + r")\b)", re.MULTILINE)

found_deps = []

for root_dir in ["src", "scripts", "tools", "notebooks", "."]:
    if not os.path.exists(root_dir): continue
    for dirpath, dirnames, filenames in os.walk(root_dir):
        # Skip archive and venv
        if "archive" in dirpath or ".venv" in dirpath or "__pycache__" in dirpath or ".git" in dirpath:
            continue
        for f in filenames:
            if f.endswith(".py"):
                path = os.path.join(dirpath, f)
                # Avoid self-checking and the files to be archived themselves if we want,
                # but let's check all to see if active files import them.
                with open(path, "r", encoding="utf-8", errors="ignore") as file:
                    content = file.read()
                    matches = pattern.findall(content)
                    if matches:
                        # flatten matches
                        matched_mods = {m for tup in matches for m in tup if m}
                        found_deps.append((path, matched_mods))

for path, mods in found_deps:
    print(f"{path}: {mods}")
