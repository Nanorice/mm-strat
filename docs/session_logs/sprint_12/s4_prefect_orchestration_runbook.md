# S4 — Prefect Orchestration Runbook

*Sprint 12, 2026-06-21. Automates the nightly `run_daily_pipeline.py` on the ITX
ops box using a self-hosted Prefect (3.x) server + scheduler. **Supersedes the
Windows Task Scheduler approach** in `s4_task_scheduler_runbook.md` — Prefect now
owns scheduling, outer retry, run history, and the UI.*

## Design — coarse wrap, one execution path

Prefect owns **only** the outer ring: schedule, crash-level retry, run history, UI.
The 9-phase business logic stays inside `DailyPipelineOrchestrator`. The flow
([`flows/daily_pipeline_flow.py`](../../../flows/daily_pipeline_flow.py)) shells
out to the canonical CLI so there is exactly **one** execution path — no
re-modelling of phases as Prefect tasks.

Why coarse, not per-phase: per-phase Prefect tasks would duplicate the existing
phase registry (`src/orchestrators/phase_registry.py`) and the per-phase health
already tracked in `pipeline_runs`. DuckDB is single-writer (no parallel fan-out
to gain), and the orchestrator already has idempotency + an in-run retry
(Phase 1.5). So per-phase Prefect buys little and adds a second source of truth.
If a phase-level retry from the UI is ever genuinely needed, that's a small,
well-scoped follow-up — the coarse flow doesn't block it.

```
Prefect deployment (cron) ─▶ serve ─▶ @flow daily_pipeline ─▶ subprocess
                                                              run_daily_pipeline.py
                                                              └─ 14 phases (orchestrator)
```

## Schedule — 22:00 Europe/London, weekdays

`CRON = "0 22 * * 1-5"`, timezone = local IANA (`Europe/London`, auto-detected via
`tzlocal`). ~1h after the US close (which sits ~21:00 London year-round).

**DST is handled automatically** because the schedule uses the IANA tz name, not a
fixed UTC offset — 22:00 stays 22:00 London across the BST/GMT switch:

| Season | London | UTC |
|--------|--------|-----|
| Summer (BST) | 22:00 | 21:00 |
| Winter (GMT) | 22:00 | 22:00 |

Weekend runs are skipped (Mon-Fri only); the pipeline's idempotency would no-op
them anyway. Both knobs are env-overridable without editing code:
`PIPELINE_CRON`, `PIPELINE_CRON_TZ`.

**The code is the source of truth for the schedule** — `serve` re-registers it
from `CRON` on every startup, so editing the schedule in the UI is transient.
Change `CRON` in the flow, then restart the serve task.

## Components

| File | Role |
|------|------|
| `flows/daily_pipeline_flow.py` | The `@flow` (`retries=1`, 10-min delay; streams child logs into the run log). `--serve` = long-lived scheduler; `--date/--force/--dry-run` = one-off run. |
| `scripts/start_prefect_server.ps1` | Self-anchored launcher for the local server (API + UI at :4200). |
| `scripts/start_prefect_serve.ps1` | Self-anchored launcher for the scheduler. Waits for server health, sets `PREFECT_API_URL`, runs `--serve`. |
| `scripts/register_prefect_tasks.ps1` | Idempotent registration of the two boot tasks (`PrefectServer`, `PrefectDailyPipelineServe`), AtLogOn trigger. |

State lives in `~/.prefect` (SQLite, **outside** the repo). Launcher logs in
`logs/prefect/` (gitignored, pruned >30 days). Per-run pipeline logs remain at
`logs/daily_pipeline_<ts>.log`.

## Install

```powershell
pip install -r requirements.txt   # adds prefect>=3.0.0
```

Registering scheduled tasks writes to the root Task Scheduler library, which
**requires an elevated PowerShell** (Run as administrator):

```powershell
# 1. Register the two boot tasks (AtLogOn)
powershell -ExecutionPolicy Bypass -File scripts\register_prefect_tasks.ps1

# 2. Bring Prefect live now (don't wait for next logon)
Start-ScheduledTask -TaskName 'PrefectServer'
Start-ScheduledTask -TaskName 'PrefectDailyPipelineServe'
```

**AtLogOn** assumes the ITX box auto-logs-in. For true headless (no logon),
re-register with an S4U principal (also needs the elevated shell).

## Operate

**UI**: http://127.0.0.1:4200 — Deployments → `daily-pipeline/daily`.

**Kick off a manual run:**
- UI: Deployments → `daily-pipeline/daily` → **Run ▸ Quick run**.
- CLI: `prefect deployment run 'daily-pipeline/daily'` (needs
  `PREFECT_API_URL=http://127.0.0.1:4200/api`; prefix `$env:PYTHONUTF8=1` to avoid
  a cosmetic `UnicodeEncodeError` on the confirmation banner — the run still fires).

**Change the schedule:** edit `CRON` in `flows/daily_pipeline_flow.py`, then:
```powershell
Stop-ScheduledTask  -TaskName 'PrefectDailyPipelineServe'
Start-ScheduledTask -TaskName 'PrefectDailyPipelineServe'
```
(serve re-registers the new schedule on startup; only serve owns the schedule,
not the server.) If stale future runs from the old schedule linger under
*Scheduled* in the UI, delete them.

## Verify

```powershell
Get-ScheduledTask -TaskName 'PrefectServer','PrefectDailyPipelineServe' | Get-ScheduledTaskInfo
Invoke-WebRequest http://127.0.0.1:4200/api/health   # -> true
```

A real end-to-end run was verified 2026-06-21: deployment trigger → serve → flow
→ CLI → orchestrator, flow run `Completed`, pipeline `DONE | 14 phases | OK |
335s wall`. Idempotency confirmed live (phases already done for the target
trading day were skipped; scoring still wrote predictions).

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Register-ScheduledTask: Access is denied` | Not an elevated shell | Re-run registration from an admin PowerShell. |
| Schedule unchanged after editing `CRON` | serve only reads `CRON` at startup | Stop/Start the `PrefectDailyPipelineServe` task. |
| Run shows two `run_daily_pipeline.py` processes | Not a double run — the orchestrator spawns subprocess phases (dashboard build / model card) + multiprocessing alpha workers as children | None; expected. |
| A child process shows as **system Python** in `ps` | Cosmetic — multiprocessing spawn workers surface under `sys._base_executable`. Phases themselves use `sys.executable` (the `.venv`), confirmed: system Python lacks `duckdb`/`xgboost` yet phases pass. | None; not a misconfiguration. |
| `UnicodeEncodeError` on `prefect deployment run` | rich rendering the banner to a cp1252 pipe | Cosmetic — run still triggers; set `PYTHONUTF8=1`. |
| Remote dashboard a day behind | Phase 7.6 R2 sync skipped (creds) | See `s4_task_scheduler_runbook.md` dotenv section — the `.env`-at-root fix still applies. |
