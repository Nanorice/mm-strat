"""
Run all audit tools in sequence and produce a combined report.

Each audit runs as a subprocess (--json mode) so their module-level state
is isolated. Results are aggregated and saved to data/audit_reports/audit_report_YYYYMMDD.json.

Usage:
    python tools/run_all_audits.py
    python tools/run_all_audits.py --warn-only      # exit 1 if any FAIL/WARNING
    python tools/run_all_audits.py --json           # also print full JSON to stdout
    python tools/run_all_audits.py --date 2024-06-01  # pass spot-check date to T2/T3 audits
    python tools/run_all_audits.py --skip t1 t2_membership  # skip named audits
"""
import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

TOOLS_DIR = Path(__file__).parent
REPO_ROOT = TOOLS_DIR.parent
REPORT_DIR = REPO_ROOT / "data" / "audit_reports"
PYTHON = sys.executable

# Ordered audit definitions: (label, script, extra_args_fn)
# extra_args_fn receives parsed CLI args and returns a list of extra flags
AUDITS = [
    ("T1 Data Quality",       "audit_t1_data_quality.py",      lambda a: []),
    ("T2 Membership",         "audit_t2_membership.py",        lambda a: (["--date", a.date] if a.date else [])),
    ("T2 Screener Features",  "audit_t2_screener_features.py", lambda a: (["--date", a.date] if a.date else [])),
    ("T3 SEPA Features",      "audit_t3_sepa_features.py",     lambda a: (["--date", a.date] if a.date else [])),
]

# Short keys for --skip
AUDIT_KEYS = {
    "t1":            "T1 Data Quality",
    "t2_membership": "T2 Membership",
    "t2_screener":   "T2 Screener Features",
    "t3":            "T3 SEPA Features",
}

STATUS_ORDER = {"FAIL": 0, "WARNING": 1, "OK": 2, "INFO": 3}
STATUS_PREFIX = {"FAIL": "[FAIL]   ", "WARNING": "[WARN]   ", "OK": "[OK]     ", "INFO": "[INFO]   "}


def run_audit(label: str, script: str, extra_args: list[str]) -> tuple[list[dict], bool]:
    """Run one audit script via subprocess --json. Returns (results, success)."""
    cmd = [PYTHON, str(TOOLS_DIR / script), "--json"] + extra_args
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return [{"section": label, "check": "subprocess_timeout", "status": "FAIL",
                 "value": 0, "detail": f"{script} timed out after 120s"}], False
    except Exception as e:
        return [{"section": label, "check": "subprocess_error", "status": "FAIL",
                 "value": 0, "detail": str(e)}], False

    if proc.returncode not in (0, 1):
        # exit 2+ = crash, not just warnings
        err = proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else "unknown error"
        return [{"section": label, "check": "subprocess_crash", "status": "FAIL",
                 "value": proc.returncode, "detail": err}], False

    # Extract JSON from stdout — audit scripts print a header line before JSON
    stdout = proc.stdout.strip()
    json_start = stdout.find("[")
    if json_start == -1:
        return [{"section": label, "check": "no_json_output", "status": "FAIL",
                 "value": 0, "detail": "audit produced no JSON output"}], False

    try:
        results = json.loads(stdout[json_start:])
    except json.JSONDecodeError as e:
        return [{"section": label, "check": "json_parse_error", "status": "FAIL",
                 "value": 0, "detail": str(e)}], False

    # Prefix section names with the audit label for disambiguation
    for r in results:
        r["audit"] = label
    return results, True


def render_text(all_results: list[dict], warn_only: bool) -> int:
    exit_code = 0
    current_audit = None
    current_section = None

    for r in all_results:
        audit = r.get("audit", "")
        if audit != current_audit:
            current_audit = audit
            current_section = None
            print(f"\n{'#' * 70}")
            print(f"  {audit.upper()}")
            print(f"{'#' * 70}")

        if r["section"] != current_section:
            current_section = r["section"]
            print(f"\n{'=' * 60}")
            print(f"  {current_section.upper()}")
            print(f"{'=' * 60}")

        prefix = STATUS_PREFIX.get(r["status"], "[?]      ")
        val = str(r["value"])
        if isinstance(r["value"], float):
            val = f"{r['value']:.1f}%"
        line = f"  {prefix}{r['check']:<42} {val}"
        if r.get("detail"):
            line += f"\n           {r['detail']}"
        if not warn_only or r["status"] in ("FAIL", "WARNING"):
            print(line)
        if r["status"] in ("FAIL", "WARNING"):
            exit_code = 1

    return exit_code


def render_summary(all_results: list[dict], skipped: list[str]) -> None:
    total = {"FAIL": 0, "WARNING": 0, "OK": 0, "INFO": 0}
    per_audit: dict[str, dict] = {}

    for r in all_results:
        audit = r.get("audit", "unknown")
        total[r["status"]] = total.get(r["status"], 0) + 1
        per_audit.setdefault(audit, {"FAIL": 0, "WARNING": 0, "OK": 0, "INFO": 0})
        per_audit[audit][r["status"]] = per_audit[audit].get(r["status"], 0) + 1

    print(f"\n{'#' * 70}")
    print("  SUMMARY")
    print(f"{'#' * 70}")
    for audit, counts in per_audit.items():
        flag = " [FAIL]" if counts["FAIL"] else (" [WARN]" if counts["WARNING"] else " [OK]")
        print(f"  {audit:<35} FAIL={counts['FAIL']} WARN={counts['WARNING']} OK={counts['OK']}{flag}")
    if skipped:
        print(f"  Skipped: {', '.join(skipped)}")
    print(f"\n  TOTAL: {total['FAIL']} FAIL | {total['WARNING']} WARNING | {total['OK']} OK | {total['INFO']} INFO")
    print(f"{'#' * 70}")


def build_report(all_results: list[dict], skipped: list[str], run_ts: str) -> dict:
    """Wrap results in a metadata envelope for the saved report."""
    total = {"FAIL": 0, "WARNING": 0, "OK": 0, "INFO": 0}
    per_audit: dict[str, dict] = {}
    for r in all_results:
        audit = r.get("audit", "unknown")
        total[r["status"]] = total.get(r["status"], 0) + 1
        per_audit.setdefault(audit, {"FAIL": 0, "WARNING": 0, "OK": 0, "INFO": 0})
        per_audit[audit][r["status"]] += 1

    overall = "FAIL" if total["FAIL"] > 0 else ("WARNING" if total["WARNING"] > 0 else "OK")
    return {
        "run_at": run_ts,
        "overall": overall,
        "summary": {"total": total, "per_audit": per_audit, "skipped": skipped},
        "results": all_results,
    }


def find_new_fails(report: dict) -> list[dict]:
    """Diff current FAILs against the most recent previous report.

    Alert-fatigue fix: with standing FAILs the exit code / totals carry no signal —
    only a FAIL that wasn't there yesterday is actionable. First run (no previous
    report) treats every FAIL as new.
    """
    current = {(r.get("audit"), r["section"], r["check"]): r
               for r in report["results"] if r["status"] == "FAIL"}
    if not current:
        return []
    date_str = report["run_at"][:10].replace("-", "")
    prev_paths = sorted(p for p in REPORT_DIR.glob("audit_report_*.json")
                        if p.name != f"audit_report_{date_str}.json")
    if not prev_paths:
        return list(current.values())
    try:
        prev = json.loads(prev_paths[-1].read_text())
        prev_keys = {(r.get("audit"), r["section"], r["check"])
                     for r in prev.get("results", []) if r["status"] == "FAIL"}
    except Exception:
        return []  # unreadable previous report — no basis for a delta
    return [r for k, r in current.items() if k not in prev_keys]


def save_report(report: dict) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    date_str = report["run_at"][:10].replace("-", "")
    path = REPORT_DIR / f"audit_report_{date_str}.json"
    with open(path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Run all audit tools and produce a combined report")
    parser.add_argument("--json",      action="store_true", help="Also print full JSON report to stdout")
    parser.add_argument("--warn-only", action="store_true", help="Only print FAIL/WARNING; exit 1 if any found")
    parser.add_argument("--date",      type=str, default=None, help="Spot-check date (YYYY-MM-DD) passed to T2/T3 audits")
    parser.add_argument("--skip",      nargs="+", metavar="AUDIT",
                        help=f"Skip audits by key: {list(AUDIT_KEYS.keys())}")
    args = parser.parse_args()

    run_ts = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    skip_labels = {AUDIT_KEYS[k] for k in (args.skip or []) if k in AUDIT_KEYS}

    all_results: list[dict] = []
    skipped: list[str] = []

    for label, script, extra_args_fn in AUDITS:
        if label in skip_labels:
            skipped.append(label)
            continue
        print(f"\nRunning: {label} ...", flush=True)
        results, ok = run_audit(label, script, extra_args_fn(args))
        all_results.extend(results)
        counts = {"FAIL": 0, "WARNING": 0, "OK": 0}
        for r in results:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        status_str = f"FAIL={counts['FAIL']} WARN={counts['WARNING']} OK={counts['OK']}"
        marker = "[FAIL]" if counts["FAIL"] else ("[WARN]" if counts["WARNING"] else "[OK]  ")
        print(f"  {marker} {label}: {status_str}")

    report = build_report(all_results, skipped, run_ts)
    report["new_fails"] = find_new_fails(report)
    report_path = save_report(report)
    print(f"\nReport saved: {report_path}")

    if report["new_fails"]:
        print(f"\n  [ALERT] {len(report['new_fails'])} NEW FAIL(s) vs previous report:")
        for r in report["new_fails"]:
            print(f"    - {r.get('audit')}/{r['section']}.{r['check']} = {r['value']}")

    if args.json:
        print(json.dumps(report, indent=2, default=str))
        sys.exit(0)

    exit_code = render_text(all_results, args.warn_only)
    render_summary(all_results, skipped)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
