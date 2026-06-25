"""Idempotently ensure server-side Prefect automations exist.

Run by start_prefect_serve.ps1 AFTER the local server is confirmed healthy.
Best-effort and timeout-bounded: it must never hang or fail serve startup.

Automations declared here:
- crash-zombie-flow-runs: a Proactive trigger that marks a flow run Crashed
  when its heartbeats stop (process died on box-sleep / server loss), so dead
  runs don't sit stuck in Running. Pairs with PREFECT_FLOWS_HEARTBEAT_FREQUENCY
  (30s) set in the serve launcher; window is 90s (3x heartbeat).
"""
import asyncio
import sys
from datetime import timedelta

ZOMBIE_NAME = "crash-zombie-flow-runs"


async def _ensure() -> None:
    from prefect.automations import Automation
    from prefect.client.orchestration import get_client
    from prefect.client.schemas.objects import StateType
    from prefect.events.actions import ChangeFlowRunState
    from prefect.events.schemas.automations import EventTrigger, Posture

    async with get_client() as client:
        existing = await client.read_automations()
        if any(a.name == ZOMBIE_NAME for a in existing):
            print(f"[automations] {ZOMBIE_NAME}: already present")
            return

    automation = Automation(
        name=ZOMBIE_NAME,
        description=(
            "Mark a flow run Crashed when its heartbeats stop, so dead runs "
            "(box sleep / server loss) don't sit stuck in Running."
        ),
        trigger=EventTrigger(
            expect={"prefect.flow-run.heartbeat"},
            after={"prefect.flow-run.heartbeat"},
            for_each={"prefect.resource.id"},
            posture=Posture.Proactive,
            threshold=1,
            within=timedelta(seconds=90),
        ),
        actions=[
            ChangeFlowRunState(
                state=StateType.CRASHED,
                message="No heartbeat for 90s - process died (sleep/server-loss). Auto-reconciled.",
            )
        ],
    )
    created = await automation.acreate()
    print(f"[automations] {ZOMBIE_NAME}: created (id={created.id})")


def main() -> int:
    try:
        asyncio.run(asyncio.wait_for(_ensure(), timeout=30))
    except Exception as e:
        # Never block serve startup on this.
        print(f"[automations] WARN: could not ensure automations: {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
