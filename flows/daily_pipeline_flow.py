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
import ctypes
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


_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001


def _set_keep_awake(on: bool) -> None:
    """Hold/release a system-required lock for the duration of the run (~30 min).
    Windows' idle-sleep timer is driven by USER INPUT, not CPU load — so an
    unattended long run would otherwise be at the mercy of the sleep timeout.
    No-ops off Windows. Released so the box can sleep again when the run ends."""
    try:
        flags = _ES_CONTINUOUS | (_ES_SYSTEM_REQUIRED if on else 0)
        ctypes.windll.kernel32.SetThreadExecutionState(flags)
    except Exception:
        pass


def _discord_send(content: str) -> None:
    """Best-effort Discord notify via the Prefect block. Loading the block needs
    the API, so this is only safe while the server is up — true for in-flow hooks
    (the wake script, where the server is down, uses a raw webhook instead)."""
    try:
        from prefect.blocks.notifications import DiscordWebhook
        DiscordWebhook.load("daily-pipeline-discord").notify(content)
    except Exception:
        pass


def _notify_discord(flow, flow_run, state) -> None:
    """Send a Discord message on terminal state. Done IN-FLOW (not via a server
    automation) so it delivers while the server is up. Best-effort — never affects
    the run. Crashed runs (process death) can't run this hook; the server-side
    automation covers that case."""
    emoji = {"Completed": "✅", "Failed": "❌", "Crashed": "🛑"}.get(state.name, "ℹ️")
    _discord_send(f"{emoji} daily-pipeline `{flow_run.name}` → **{state.name}**")


# NOTE: the box is NOT script-slept after a run. On this hardware a programmatic
# SetSuspendState (Kernel-Power Reason 4) leaves the RTC wake timer firing only
# intermittently (~50%), while a genuine idle-triggered sleep (Reason 7) wakes
# reliably. So the run only HOLDS the box awake (see _set_keep_awake); the OS idle
# timeout puts it to sleep afterward, and the Task Scheduler wake task brings it back.


@flow(
    name="daily-pipeline",
    retries=1,
    retry_delay_seconds=600,
    on_completion=[_notify_discord],
    on_failure=[_notify_discord],
)
def daily_pipeline(
    date: str | None = None,
    force: bool = False,
    dry_run: bool = False,
    selftest: bool = False,
) -> None:
    """Run the full daily pipeline via its CLI; raise on non-zero exit.

    Idempotency in the orchestrator makes the single retry cheap — already-
    completed phases are skipped, so a retry resumes rather than redoes.

    `selftest=True` skips the pipeline entirely and returns at once: it exercises
    only the scheduling path + terminal-state hooks (Discord + power-cycle sleep),
    so the sleep/wake cycle can be tested without a ~35-min pipeline run.
    """
    logger = get_run_logger()

    if selftest:
        logger.info("selftest: skipping pipeline body; exercising scheduling + completion hooks only")
        return

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

    # Keep the box awake for the whole ~30-min run, then let it sleep again.
    _set_keep_awake(True)
    try:
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
    finally:
        _set_keep_awake(False)

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
        limit=1,  # single-writer DuckDB: runner executes one run at a time, never fan out catch-up
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
