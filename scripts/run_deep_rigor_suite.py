"""§1.4 Deep-rigor suite runner.

One CLI that drives bootstrap CI, permutation null, decile analysis, and
ablation against a single trained model. Each sub-step is its own script
(kept that way for ad-hoc reruns and visibility) — this wrapper just
re-points the `MODEL_DIR` constants and orchestrates execution.

Usage:
    python scripts/run_deep_rigor_suite.py \\
        --model-name m01_binary --model-version v1 \\
        --feature-set fs_m01_prototype \\
        --label-id mfe_binary_homerun_v1 \\
        --feature-groups "Core_Volume,Fundamentals,Momentum_RS,Moving_Averages,Categoricals,M03_Regime,Fast_Alphas,Technical_Oscillators,Volatility_Ranges" \\
        --backtest-start 2023-05-01 --backtest-end 2026-05-22

Output: models/<name>/<version>/evaluation/full_eval/
    bootstrap_ci.json
    permutation_null.json
    decile_analysis.json
    ablation/<group>/{model.json, metadata.json, metrics.json}
    ablation/ablation_summary.json
    suite_summary.json   # this wrapper's run manifest

Sub-step toggles (default ALL on):
    --skip-bootstrap   --skip-permutation   --skip-decile   --skip-ablation

Each sub-step writes its own log under logs/deep_rigor/<sub>_<model>_<version>.log.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

PYTHON = REPO_ROOT / ".venv" / "Scripts" / "python.exe"
if not PYTHON.exists():
    PYTHON = Path(sys.executable)

LOG_DIR = REPO_ROOT / "logs" / "deep_rigor"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="§1.4 deep-rigor suite runner")
    p.add_argument("--model-name", required=True)
    p.add_argument("--model-version", required=True)
    p.add_argument("--feature-set", required=True,
                   help="Feature set id for ablation (e.g., fs_m01_prototype)")
    p.add_argument("--label-id", required=True,
                   help="Label registry id — drives ablation's XGBoost objective.")
    p.add_argument("--feature-groups", default=None,
                   help="Comma-separated groups to ablate. Default: all groups in --feature-set.")
    p.add_argument("--backtest-start", default="2023-05-01")
    p.add_argument("--backtest-end", default="2026-05-22")
    p.add_argument("--n-perms", type=int, default=200,
                   help="Permutation count for the null backtest (200 ~4 min, 1000 ~20 min).")
    p.add_argument("--skip-bootstrap", action="store_true")
    p.add_argument("--skip-permutation", action="store_true")
    p.add_argument("--skip-decile", action="store_true")
    p.add_argument("--skip-ablation", action="store_true")
    p.add_argument("--n-workers", type=int, default=4,
                   help="Parallel workers for the ablation step. Each group is a separate "
                        "subprocess; workers run them concurrently. Default 4. Set to 1 to "
                        "restore serial behaviour.")
    p.add_argument("--no-backtest", action="store_true",
                   help="Pass --no-backtest to the ablation step: measure ablation impact via "
                        "classification metrics (ROC-AUC, weighted-F1, positive-class precision) "
                        "instead of running Backtrader. Isolates model quality from strategy effects.")
    p.add_argument("--dry-run", action="store_true",
                   help="Print planned subprocess invocations without executing.")
    return p.parse_args()


def _patch_model_dir(script_path: Path, new_dir: str) -> None:
    """Rewrite the MODEL_DIR constant in a deep-rigor script in place.

    Idempotent — any prior MODEL_DIR Path() assignment is replaced.
    """
    text = script_path.read_text(encoding="utf-8")
    # Match either form used across scripts:
    #   MODEL_DIR = Path("...")
    #   MODEL_DIR = ROOT / "..." / "..."
    new_line = f'MODEL_DIR = Path("{new_dir}")'
    patterns = [
        r'MODEL_DIR\s*=\s*Path\([^)]*\)',
        r'MODEL_DIR\s*=\s*ROOT\s*/[^\n]+',
    ]
    found = False
    patched = text
    for pat in patterns:
        patched, n = re.subn(pat, new_line, patched, count=1)
        if n:
            found = True
            break
    if not found:
        raise RuntimeError(f"Could not locate MODEL_DIR assignment in {script_path}")
    script_path.write_text(patched, encoding="utf-8")


def _patch_production_class_idx(script_path: Path, idx: int) -> None:
    """Rewrite PRODUCTION_CLASS_IDX in the permutation null script."""
    text = script_path.read_text(encoding="utf-8")
    pat = r'PRODUCTION_CLASS_IDX\s*=\s*\d+'
    new = f'PRODUCTION_CLASS_IDX = {idx}'
    patched, n = re.subn(pat, new, text, count=1)
    if n == 0:
        logger.warning("PRODUCTION_CLASS_IDX not found in %s — skipping patch", script_path)
        return
    script_path.write_text(patched, encoding="utf-8")


def _detect_production_class_idx(model_dir: Path) -> int:
    """Read the model's label_definition.json to pick the production class index.

    For binary labels (bins=[t]) the positive class is index 1.
    For 4-class (bins=[2,10,30]) the Home Run class is index 3 (last bin).
    """
    label_path = model_dir / "label_definition.json"
    if not label_path.exists():
        logger.warning("No label_definition.json in %s — defaulting PRODUCTION_CLASS_IDX=1 (binary)", model_dir)
        return 1
    label = json.loads(label_path.read_text())
    bins = label.get("bins") or []
    n_classes = len(bins) + 1
    return n_classes - 1   # last bin = production class


def _run(cmd: List[str], log_path: Path, dry_run: bool, env: Optional[dict] = None) -> int:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("→ %s", " ".join(str(c) for c in cmd))
    logger.info("  log: %s", log_path)
    if dry_run:
        return 0
    t0 = time.time()
    with log_path.open("w", encoding="utf-8") as f:
        proc = subprocess.run(
            cmd,
            stdout=f,
            stderr=subprocess.STDOUT,
            cwd=str(REPO_ROOT),
            env=env,
        )
    elapsed = time.time() - t0
    logger.info("  exit=%d, elapsed=%.1fs", proc.returncode, elapsed)
    return proc.returncode


def _resolve_groups(args: argparse.Namespace) -> List[str]:
    """Return the ordered list of feature groups to ablate."""
    if args.feature_groups:
        return [g.strip() for g in args.feature_groups.split(",") if g.strip()]
    import duckdb
    con = duckdb.connect(str(REPO_ROOT / "data" / "market_data.duckdb"), read_only=True)
    try:
        rows = con.execute(
            "SELECT DISTINCT feature_group FROM model_feature_sets "
            "WHERE feature_set_id = ? ORDER BY feature_group",
            [args.feature_set],
        ).fetchall()
    finally:
        con.close()
    return [r[0] for r in rows]


def _base_ablation_cmd(
    args: argparse.Namespace,
    ablation_script: Path,
) -> List[str]:
    """Build the ablation command without --feature-groups (added per worker)."""
    cmd = [
        str(PYTHON), str(ablation_script),
        "--model-name", args.model_name,
        "--model-version", args.model_version,
        "--feature-set", args.feature_set,
        "--label-id", args.label_id,
        "--backtest-start", args.backtest_start,
        "--backtest-end", args.backtest_end,
    ]
    if args.no_backtest:
        cmd.append("--no-backtest")
    return cmd


def _run_ablation_parallel(
    base_cmd: List[str],
    groups: List[str],
    ablation_out: Path,
    tag: str,
    n_workers: int,
    dry_run: bool,
) -> Tuple[int, List[dict]]:
    """Fan out one subprocess per group, merge results into ablation_summary.json.

    Each group writes to ablation_out/<group>/ablation_summary.json so there
    are no write collisions between workers.  After all workers finish the
    per-group payloads are merged: the baseline from the first successful run
    is used (all groups share the same training data, so baselines should be
    identical); ablation entries are concatenated and re-sorted by delta.

    Returns (worst_exit_code, per_group_results_for_manifest).
    """
    ablation_out.mkdir(parents=True, exist_ok=True)
    actual_workers = min(n_workers, len(groups))
    logger.info("⚙️  Ablation: %d groups × %d workers", len(groups), actual_workers)

    def _run_one(group: str) -> Tuple[str, int, Optional[dict]]:
        group_out = ablation_out / f"group_{group}"
        group_out.mkdir(parents=True, exist_ok=True)
        cmd = base_cmd + ["--feature-groups", group, "--output", str(group_out)]
        log_path = LOG_DIR / f"ablation_{tag}_{group}.log"
        rc = _run(cmd, log_path, dry_run)
        payload = None
        summary = group_out / "ablation_summary.json"
        if rc == 0 and summary.exists():
            payload = json.loads(summary.read_text())
        return group, rc, payload

    group_results: List[Tuple[str, int, Optional[dict]]] = []
    with ThreadPoolExecutor(max_workers=actual_workers) as pool:
        futures = {pool.submit(_run_one, g): g for g in groups}
        for fut in as_completed(futures):
            group, rc, payload = fut.result()
            group_results.append((group, rc, payload))
            status = "✅" if rc == 0 else "❌"
            logger.info("%s ablation group=%s exit=%d", status, group, rc)

    worst_rc = max(rc for _, rc, _ in group_results)

    # Merge: collect all AblationDelta entries across groups, use first good baseline.
    merged_baseline: Optional[dict] = None
    merged_deltas: List[dict] = []
    for group, rc, payload in group_results:
        if payload is None:
            continue
        if merged_baseline is None:
            merged_baseline = payload.get("baseline", {})
        ablations = payload.get("ablations", [])
        if ablations:
            merged_deltas.extend(ablations)

    manifest_rows: List[dict] = [
        {"group": g, "exit_code": rc, "output_exists": p is not None}
        for g, rc, p in group_results
    ]

    if merged_baseline is not None:
        good = [p for _, _, p in group_results if p]
        primary = good[0].get("primary_metric", "sharpe_ratio") if good else "sharpe_ratio"
        merged_payload = {
            "primary_metric": primary,
            "baseline": merged_baseline,
            "ablations": sorted(merged_deltas, key=lambda x: x.get(f"delta_{primary}", 0.0)),
            "workers": actual_workers,
            "groups": manifest_rows,
        }
        summary_path = ablation_out / "ablation_summary.json"
        summary_path.write_text(json.dumps(merged_payload, indent=2, default=str))
        logger.info("💾 Merged ablation summary → %s", summary_path)

    return worst_rc, manifest_rows


def main() -> int:
    args = parse_args()
    model_dir = REPO_ROOT / "models" / args.model_name / args.model_version
    if not model_dir.exists():
        raise SystemExit(f"Model dir not found: {model_dir}")

    full_eval_dir = model_dir / "evaluation" / "full_eval"
    full_eval_dir.mkdir(parents=True, exist_ok=True)
    tag = f"{args.model_name}_{args.model_version}"

    model_dir_rel = f"models/{args.model_name}/{args.model_version}"

    prod_idx = _detect_production_class_idx(model_dir)
    logger.info("Detected production_class_idx=%d for %s", prod_idx, tag)

    bootstrap_script = REPO_ROOT / "scripts" / "run_bootstrap_ci.py"
    perm_script = REPO_ROOT / "scripts" / "run_permutation_null.py"
    decile_script = REPO_ROOT / "scripts" / "run_decile_analysis.py"
    ablation_script = REPO_ROOT / "scripts" / "ablation_backtest.py"

    # Patch the three constant-driven scripts (MODEL_DIR + PRODUCTION_CLASS_IDX).
    # We do this once up front, so subsequent runs against the same model are no-ops.
    if not args.dry_run:
        _patch_model_dir(bootstrap_script, model_dir_rel)
        _patch_model_dir(perm_script, model_dir_rel)
        _patch_model_dir(decile_script, model_dir_rel)
        _patch_production_class_idx(perm_script, prod_idx)
        logger.info("✅ Patched MODEL_DIR + PRODUCTION_CLASS_IDX (idx=%d) in deep-rigor scripts", prod_idx)

    results: dict = {
        "model_name": args.model_name,
        "model_version": args.model_version,
        "label_id": args.label_id,
        "production_class_idx": prod_idx,
        "no_backtest": args.no_backtest,
        "ablation_n_workers": args.n_workers,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "steps": [],
    }

    def _record(step: str, exit_code: int, log_path: Path, output_path: Optional[Path]) -> None:
        results["steps"].append({
            "step": step,
            "exit_code": exit_code,
            "log_path": str(log_path),
            "output_path": str(output_path) if output_path else None,
            "output_exists": bool(output_path and output_path.exists()),
        })

    # 1. Bootstrap CI
    if not args.skip_bootstrap:
        log = LOG_DIR / f"bootstrap_{tag}.log"
        rc = _run([str(PYTHON), str(bootstrap_script)], log, args.dry_run)
        _record("bootstrap_ci", rc, log, full_eval_dir / "bootstrap_ci.json")

    # 2. Decile analysis (cheap — run before the long perm null)
    if not args.skip_decile:
        log = LOG_DIR / f"decile_{tag}.log"
        rc = _run([str(PYTHON), str(decile_script)], log, args.dry_run)
        _record("decile_analysis", rc, log, full_eval_dir / "decile_analysis.json")

    # 3. Permutation null
    if not args.skip_permutation:
        log = LOG_DIR / f"permutation_{tag}.log"
        env = os.environ.copy()
        env["N_PERMS"] = str(args.n_perms)
        rc = _run([str(PYTHON), str(perm_script)], log, args.dry_run, env=env)
        _record("permutation_null", rc, log, full_eval_dir / "permutation_null.json")

    # 4. Ablation — parallel per group
    if not args.skip_ablation:
        ablation_out = full_eval_dir / "ablation"
        groups = _resolve_groups(args)
        logger.info("📋 Ablation groups (%d): %s", len(groups), groups)
        base_cmd = _base_ablation_cmd(args, ablation_script)
        rc, manifest_rows = _run_ablation_parallel(
            base_cmd=base_cmd,
            groups=groups,
            ablation_out=ablation_out,
            tag=tag,
            n_workers=args.n_workers,
            dry_run=args.dry_run,
        )
        results["ablation_groups"] = manifest_rows
        _record("ablation", rc, LOG_DIR / f"ablation_{tag}_<per-group>.log",
                ablation_out / "ablation_summary.json")

    results["finished_at"] = datetime.now(timezone.utc).isoformat()
    summary_path = full_eval_dir / "suite_summary.json"
    summary_path.write_text(json.dumps(results, indent=2, default=str))
    logger.info("📋 Suite summary → %s", summary_path)

    failed = [s for s in results["steps"] if s["exit_code"] != 0]
    if failed:
        logger.error("❌ %d step(s) failed", len(failed))
        for s in failed:
            logger.error("   %s (exit=%d, log=%s)", s["step"], s["exit_code"], s["log_path"])
        return 1

    logger.info("✅ All requested steps completed (%d steps)", len(results["steps"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
