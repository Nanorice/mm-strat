# S4 — Task Scheduler Automation Runbook

*Sprint 12. Automates the nightly `run_daily_pipeline.py` (which includes Phase
7.5 slim-DB build + Phase 7.6 R2 sync) on the dev box, fixing the stale remote
dashboard.*

## Root cause of the staleness (corrected)

The Sprint 12 progress summary guessed the nightly job "ran without loading the
`.env` file" and proposed loading dotenv inside the scheduler script. That was
the right symptom, wrong mechanism.

The actual structural flaw: `config.py` called `load_dotenv()` **with no path**.
`python-dotenv` resolves a bare call by walking **up from the current working
directory**. PyCharm and an activated shell both run with CWD = project root, so
`.env` is found and `R2_ACCOUNT_ID` loads. **Task Scheduler launches with
CWD = `C:\Windows\System32`**, where the upward walk finds no `.env`, so every R2
key stays unset. Phase 7.6's `if not os.environ.get("R2_ACCOUNT_ID")` guard then
short-circuits and skips the upload **silently** — the slim DB is rebuilt locally
but never pushed, so the remote dashboard freezes a day behind.

### The fix (code, not scheduler config)

Anchor dotenv to the project root so it is CWD-independent — fixes every
entrypoint at once, not just the scheduled task:

- `config.py`: `load_dotenv(Path(__file__).resolve().parent / ".env")`
- `scripts/sync_dashboard_db.py`: `load_dotenv(PROJECT_ROOT / ".env")`
- `daily_pipeline_orchestrator._run_phase_7_6_r2_sync`: the missing-cred skip now
  logs a **WARNING** ("Remote dashboard will go stale. Check .env at project
  root.") instead of a silent INFO — a miss now signals real misconfig, since
  `.env` loads regardless of CWD.

Verification that the fix holds from a Task-Scheduler-like CWD:

```
PS C:\Windows\System32> .venv\...\python.exe -c "...import orchestrator; print(R2_ACCOUNT_ID present)"
# BEFORE: R2_ACCOUNT_ID present: False
# AFTER:  R2_ACCOUNT_ID present: True
```

## Components

| File | Role |
|------|------|
| `scripts/run_nightly_pipeline.ps1` | Self-anchored launcher. Resolves project root from its own path, calls venv Python by absolute path, pins CWD, forwards args, writes a UTF-8 log to `logs/scheduler/`, prunes logs >30 days. |
| `scripts/register_nightly_task.ps1` | Idempotent registration of the scheduled task (unregisters first, then recreates). Params: `-TaskName`, `-At "HH:mm"`, `-CurrentUser`. |

The launcher is deliberately independent of an activated venv and of CWD — Task
Scheduler can provide neither.

## Install

From an **elevated** PowerShell (registration with `S4U` logon needs admin):

```powershell
cd C:\Users\Hang\PycharmProjects\quantamental
powershell -ExecutionPolicy Bypass -File scripts\register_nightly_task.ps1 -At "06:00"
```

Default schedule: daily at 06:00 local. Prior-close market data is settled well
before then; the pipeline targets "yesterday" by default. The task is registered
with `S4U` logon (runs whether or not you're logged on, no stored password) and
`-WakeToRun` / `-StartWhenAvailable` so a missed slot (box asleep/off) runs at
next wake.

To run **only while logged on** (no admin, no S4U):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\register_nightly_task.ps1 -CurrentUser
```

### Equivalent schtasks (if you prefer the legacy CLI)

```cmd
schtasks /Create /TN "QuantamentalNightlyPipeline" /SC DAILY /ST 06:00 ^
  /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"C:\Users\Hang\PycharmProjects\quantamental\scripts\run_nightly_pipeline.ps1\"" ^
  /RL HIGHEST /F
```

`register_nightly_task.ps1` is preferred — it sets wake/battery/idle behavior
that the bare `schtasks` line above does not.

## Verify

```powershell
# Task is registered and shows Next Run Time
Get-ScheduledTask -TaskName "QuantamentalNightlyPipeline" | Get-ScheduledTaskInfo

# Fire it now (full pipeline run — takes minutes)
Start-ScheduledTask -TaskName "QuantamentalNightlyPipeline"

# Watch the launcher log
Get-Content (Get-ChildItem logs\scheduler\nightly_*.log | Sort LastWriteTime | Select -Last 1) -Wait
```

Confirm Phase 7.6 actually uploaded (not skipped) in the per-run pipeline log
`logs/daily_pipeline_<ts>.log`:

```
[Phase 7.6] dashboard.duckdb uploaded to R2 (latest/)   <- success
[Phase 7.6] R2_ACCOUNT_ID not set; skipping upload ...   <- misconfig, investigate .env
```

Quick standalone sync check (proven to work from `C:\Windows\System32`):

```powershell
.venv\Scripts\python.exe scripts\sync_dashboard_db.py --dry-run
# [SYNC] -> R2 bucket 'quantamental'
#   [DRY-RUN] upload dashboard.duckdb (778 MB) -> s3://quantamental/latest/dashboard.duckdb
#   ... asset dirs ...
# [OK] Sync complete
```

## End-to-end (Streamlit Community Cloud)

After a real nightly run, the cloud app's `dashboard_utils._ensure_local_db()`
re-pulls the slim DB from R2 when the R2 ETag differs from the local copy (see
commit `995d130` — the trigger is ETag change, not file-size diff). Confirm the
public URL shows the new trading day's data and Google-email auth still gates
access.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Remote dashboard a day behind | Phase 7.6 skipped (creds unset) | Check launcher log for the WARNING; confirm `.env` exists at project root with all 4 R2 keys. |
| Task "did not run" / 0x41303 | No next-run because trigger time passed while box off | `-StartWhenAvailable` handles this; ensure box wakes (`-WakeToRun`) or run at a time the box is on. |
| `ExecutionPolicy` blocks launcher | Machine policy | Launcher is invoked with `-ExecutionPolicy Bypass`; don't strip that from the action. |
| Garbled UTF-16 log | Old launcher | Fixed: launcher forces `PYTHONIOENCODING=utf-8` + `Out-File -Encoding utf8`. |
