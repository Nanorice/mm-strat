"""Temp-schedule helper for the sleep/wake hook test (one-off scaffolding).

The sleep hook only fires for an auto_scheduled run, which ONLY the scheduler can
mint. So we add a short-lived schedule (dry_run=True, max 1 run) ~run_min ahead and
let the scheduler create the run. The generated cron matches a single date and is
beyond the scheduler horizon, so it won't re-fire — cleanup deletes it afterward.
(Deleting the schedule BEFORE the run starts cascade-deletes the run, so we keep
the schedule until the cycle is done.) Never touches the real 0 22 * * 1-5 schedule.

    arm --sleep-after 0|1 [--run-min N]   mint one auto_scheduled dry-run
    wait <run_id> [--timeout S]           poll a run until terminal
    cleanup                               delete any leftover hook-test schedule(s)
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta

from prefect.client.orchestration import get_client
from prefect.client.schemas.actions import DeploymentScheduleCreate
from prefect.client.schemas.filters import FlowRunFilter, FlowRunFilterDeploymentId
from prefect.client.schemas.schedules import CronSchedule
from prefect.client.schemas.sorting import FlowRunSort

DEPLOYMENT = "daily-pipeline/daily"
SLUG = "hook-test"


def _tz() -> str:
    try:
        import tzlocal

        return tzlocal.get_localzone_name() or "Europe/London"
    except Exception:
        return "Europe/London"


async def _recent_run_ids(client, deployment_id) -> set[str]:
    runs = await client.read_flow_runs(
        flow_run_filter=FlowRunFilter(deployment_id=FlowRunFilterDeploymentId(any_=[deployment_id])),
        sort=FlowRunSort.EXPECTED_START_TIME_DESC,
        limit=20,
    )
    return {str(r.id) for r in runs}


async def arm(run_min: int, date: str | None, dry_run: bool, selftest: bool) -> int:
    tz = _tz()
    params: dict = {}
    if date:
        params["date"] = date
    if dry_run:
        params["dry_run"] = True
    if selftest:
        params["selftest"] = True
    async with get_client() as client:
        dep = await client.read_deployment_by_name(DEPLOYMENT)
        before = await _recent_run_ids(client, dep.id)

        fire = datetime.now().astimezone() + timedelta(minutes=run_min)
        cron = f"{fire.minute} {fire.hour} {fire.day} {fire.month} *"  # fires once (next match is +1yr)
        sched = DeploymentScheduleCreate(
            schedule=CronSchedule(cron=cron, timezone=tz),
            active=True,
            parameters=params,
            max_scheduled_runs=1,
            slug=SLUG,
        )
        created = await client.create_deployment_schedules(dep.id, [sched])
        sid = created[0].id
        print(f"[OK] temp schedule {sid} armed: cron='{cron}' tz={tz} params={params}")

        # Wait for the scheduler to mint the run.
        new_run = None
        for _ in range(60):  # up to ~120s
            await asyncio.sleep(2)
            runs = await client.read_flow_runs(
                flow_run_filter=FlowRunFilter(deployment_id=FlowRunFilterDeploymentId(any_=[dep.id])),
                sort=FlowRunSort.EXPECTED_START_TIME_DESC,
                limit=20,
            )
            fresh = [r for r in runs if str(r.id) not in before]
            if fresh:
                new_run = fresh[0]
                break

        if new_run is None:
            print("[ERR] scheduler did not mint a run within timeout; deleting schedule")
            await client.delete_deployment_schedule(dep.id, sid)
            return 1

        print(f"[OK] run minted: {new_run.id} name='{new_run.name}' "
              f"auto_scheduled={new_run.auto_scheduled} start={new_run.expected_start_time}")
        if not new_run.auto_scheduled:
            print("[WARN] run is NOT auto_scheduled — sleep hook would NOT fire")
            return 2
        print(f"[..] schedule {sid} (slug={SLUG}) left in place; run cascade-deletes if "
              "schedule removed early. Run `cleanup` AFTER the cycle.")
        print(f"RUN_ID={new_run.id}")
        return 0


async def wait(run_id: str, timeout: int) -> int:
    last = None
    async with get_client() as client:
        for _ in range(max(1, timeout // 5)):
            run = await client.read_flow_run(run_id)
            st = getattr(run.state_type, "name", str(run.state_type))
            if st != last:  # only log transitions to keep output quiet
                print(f"[{datetime.now():%H:%M:%S}] run state -> {st}")
                last = st
            if st in ("COMPLETED", "FAILED", "CRASHED", "CANCELLED"):
                return 0 if st == "COMPLETED" else 1
            await asyncio.sleep(5)
        print("[ERR] run did not reach terminal state within timeout")
        return 1


async def cleanup() -> int:
    async with get_client() as client:
        dep = await client.read_deployment_by_name(DEPLOYMENT)
        scheds = await client.read_deployment_schedules(dep.id)
        removed = 0
        for s in scheds:
            if getattr(s, "slug", None) == SLUG:
                await client.delete_deployment_schedule(dep.id, s.id)
                print(f"[OK] removed leftover schedule {s.id}")
                removed += 1
        if not removed:
            print("[OK] no hook-test schedule to remove")
        return 0


def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("arm")
    a.add_argument("--run-min", type=int, default=3)
    a.add_argument("--date", type=str, default=None, help="target date YYYY-MM-DD")
    a.add_argument("--dry-run", action="store_true", help="pass dry_run=True (note: not currently writeless)")
    a.add_argument("--selftest", action="store_true", help="skip pipeline body; exercise hooks only")
    w = sub.add_parser("wait")
    w.add_argument("run_id")
    w.add_argument("--timeout", type=int, default=300)
    sub.add_parser("cleanup")
    args = p.parse_args()

    if args.cmd == "arm":
        return asyncio.run(arm(args.run_min, args.date, args.dry_run, args.selftest))
    if args.cmd == "wait":
        return asyncio.run(wait(args.run_id, args.timeout))
    return asyncio.run(cleanup())


if __name__ == "__main__":
    raise SystemExit(main())
