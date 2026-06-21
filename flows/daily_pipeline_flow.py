"""Prefect flow wrapping the daily pipeline (coarse / outer-ring orchestration).

Prefect owns ONLY scheduling, crash-level retry, run history and the UI. The
9-phase business logic stays inside DailyPipelineOrchestrator — this flow shells
out to the canonical CLI (scripts/run_daily_pipeline.py) so there is exactly one
execution path. Per-phase health already lives in pipeline_runs (see
src/orchestrators/phase_registry.py); we deliberately do not re-model it here.

Usage:
    python flows/daily_pipeline_flow.py            # run the pipeline once (ad-hoc)
    python flows/daily_pipeline_flow.py --serve    # long-lived scheduler (boot proc)
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from prefect import flow, get_run_logger

PROJECT_ROOT = Path(__file__).resolve().parent.parent
VENV_PYTHON = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
CLI = PROJECT_ROOT / "scripts" / "run_daily_pipeline.py"

def _local_tz() -> str:
    """Machine's IANA tz (e.g. 'Europe/London'); UTC if it can't be resolved."""
    try:
        import tzlocal

        return tzlocal.get_localzone_name() or "UTC"
    except Exception:
        return "UTC"


# Overridable via env so the boot launcher can pin them without editing code.
# 22:00 Mon-Fri in the local IANA tz (Europe/London) — ~1h after the US close,
# which sits at ~21:00 London year-round. The IANA tz (not a fixed UTC offset)
# means the 22:00 wall-clock time auto-tracks the BST/GMT switch; no DST edits.
# Weekend runs are skipped here; the pipeline's idempotency would no-op them
# anyway, but Mon-Fri avoids the pointless wake-up. Holidays still fire and skip.
CRON = os.environ.get("PIPELINE_CRON", "0 22 * * 1-5")
CRON_TZ = os.environ.get("PIPELINE_CRON_TZ") or _local_tz()


def _python() -> str:
    """Project venv interpreter, falling back to the current one."""
    return str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable


def _suspend_pc() -> None:
    """Put Windows to sleep (S3; hibernate if enabled). Safe because the 21:55
    Task Scheduler wake task brings the box back before the next scheduled run."""
    try:
        subprocess.run(
            ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"], timeout=30
        )
    except Exception:
        pass


def _sleep_after_run(flow, flow_run, state) -> None:
    """Flow state hook: suspend the PC once the run is terminal, but ONLY when
    called with sleep_after=True (the scheduled nightly run). Manual/ad-hoc runs
    leave the box awake. Fires after retries are exhausted, so a failing run still
    gets its one retry before the box sleeps."""
    if flow_run.parameters.get("sleep_after"):
        _suspend_pc()


@flow(
    name="daily-pipeline",
    retries=1,
    retry_delay_seconds=600,
    on_completion=[_sleep_after_run],
    on_failure=[_sleep_after_run],
)
def daily_pipeline(
    date: str | None = None,
    force: bool = False,
    dry_run: bool = False,
    sleep_after: bool = False,
) -> None:
    """Run the full daily pipeline via its CLI; raise on non-zero exit.

    Idempotency in the orchestrator makes the single retry cheap — already-
    completed phases are skipped, so a retry resumes rather than redoes.
    """
    logger = get_run_logger()

    cmd = [_python(), str(CLI)]
    if date:
        cmd += ["--date", date]
    if force:
        cmd += ["--force"]
    if dry_run:
        cmd += ["--dry-run"]

    logger.info("Launching: %s (cwd=%s)", " ".join(cmd), PROJECT_ROOT)

    # Pin CWD to project root (dotenv + relative paths) and force UTF-8 so the
    # child's emoji/log output streams cleanly into the Prefect run log.
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    proc = subprocess.Popen(
        cmd,
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    for line in proc.stdout:
        logger.info(line.rstrip())
    rc = proc.wait()

    if rc != 0:
        raise RuntimeError(f"daily pipeline CLI exited {rc}")
    logger.info("daily pipeline completed OK")


def _serve() -> None:
    """Register the deployment with a cron schedule and execute scheduled runs.

    This is the long-lived process kept alive at boot on the ITX ops box; it
    plays the worker role for static infra (no separate work pool needed).
    """
    from prefect.schedules import Cron

    daily_pipeline.serve(
        name="daily",
        schedule=Cron(CRON, timezone=CRON_TZ),
        # The scheduled nightly run sleeps the box when done (paired with the
        # 21:55 Task Scheduler wake task). Ad-hoc `python flows/...` runs do not.
        parameters={"sleep_after": True},
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Daily pipeline Prefect flow")
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Run the long-lived scheduler (cron) instead of a single run",
    )
    parser.add_argument("--date", type=str, help="Target date YYYY-MM-DD (one-off run)")
    parser.add_argument("--force", action="store_true", help="Ignore idempotency (one-off run)")
    parser.add_argument("--dry-run", action="store_true", help="Validate only, no writes (one-off run)")
    args = parser.parse_args()

    if args.serve:
        _serve()
    else:
        daily_pipeline(date=args.date, force=args.force, dry_run=args.dry_run)
