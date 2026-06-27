# Prefect Power-Cycle Incident Log & Fix Record (2026-06-22 → 2026-06-27)

> **Purpose:** self-contained handover for a fresh session. Captures every failure of the
> nightly Prefect run on the ITX box since the port, the root cause of each, the fix applied
> (with commit), the current system state, and the open issues. You should NOT need the prior
> chat to continue from here.
>
> **Branch:** `infra` (10 commits ahead of `main`, **unpushed**). Continues
> [2026-06-22_prefect.md](2026-06-22_prefect.md).

---

## 1. System under test
- **Box:** ITX, Windows 11, 16 GB RAM. Ported from another dev box (`data/` is gitignored / was empty after the port).
- **Goal:** a nightly Prefect pipeline (`daily-pipeline/daily`, deployment id `feec9365-6303-4a6c-824f-c89859db42d8`) runs on a **power-cycle**: box sleeps between runs, a Task Scheduler `-WakeToRun` task wakes it ~15 min before the 22:00 cron, the flow runs, then the flow's completion hook sleeps the box again.
- **Key pieces:**
  - `flows/daily_pipeline_flow.py` — the flow. Hooks (on_completion + on_failure): `_notify_discord` then `_sleep_after_run`. `_sleep_after_run` gates on `flow_run.auto_scheduled AND parameters['sleep_after']` and calls `_suspend_pc()` = `rundll32 powrprof.dll,SetSuspendState 0,1,0`.
  - `scripts/start_prefect_server.ps1` — launches `prefect server start` (SQLite backend, `~/.prefect/prefect.db`).
  - `scripts/start_prefect_serve.ps1` — waits for server health, then `daily_pipeline_flow.py --serve`.
  - `scripts/wake_for_pipeline.ps1` — the wake-task action: kill stale Prefect, restart server+serve, hold the box awake across the run window.
  - `scripts/register_prefect_wake_task.ps1` — **elevated** setup: registers `PrefectPipelineWake` (Mon–Fri 21:45, `-WakeToRun`, `StartWhenAvailable`) + sets power prerequisites.
  - Scheduled tasks: `PrefectServer`, `PrefectDailyPipelineServe` (AtLogon), `PrefectPipelineWake` (the wake).
- **Single-writer constraints:**
  - `~/.prefect/prefect.db` (SQLite) — touched ONLY by the Prefect server (grep-verified: zero Python refs). Any "database is locked" is always a Prefect process, never a notebook.
  - `data/market_data.duckdb` (~84 GB, DuckDB) — single read-write. The pipeline is the sole writer; analysis notebooks must open `read_only=True` (`notebooks/model_proto.py:39` still opens RW — deferred, not yet fixed).

---

## 2. Failure timeline (one root cause per night)

| Date | Symptom | Root cause | Fix (commit) |
|---|---|---|---|
| 06-22 | Server crash-loop; manual run slept the box 22h | Duplicate server instances racing the SQLite lock (`RestartCount=3` on the task); sleep hook fired on manual runs | Drop `RestartCount`, `MultipleInstances=IgnoreNew`; gate sleep on `auto_scheduled` (pre-session, see 06-22 doc) |
| 06-23 | Server down, 22:00 run missed | **SQLite WAL-lock race on wake-restart:** wake script force-killed the server then waited a blind 3 s; the killed child's WAL handle hadn't released → new server hit `database is locked` on startup state-validation, never healthy, serve timed out | `9dd9453` — active teardown barrier (wait until procs gone AND :4200 free), broaden kill set to include `run_daily_pipeline.py`, `PREFECT_SERVER_DATABASE_TIMEOUT=30`. Plus `55f58c0` (pre-flight DuckDB lock check), `669f54e` (Discord alert on wake health-fail, via raw webhook in `.env` since the server—and thus the block—is down), `ae423ad` (atomic dashboard DB build) |
| 06-24 | Box woke ~22:01 (6 min late) then re-slept 22:03 → run missed | **`UNATTENDSLEEP` = 120 s:** a wake-timer wake is "unattended"; Windows re-sleeps after the unattended-sleep timeout before `StartWhenAvailable` could fire the wake task | `a9d8a1c` — `powercfg` set `UNATTENDSLEEP` (AC) = 900 s; move wake 21:55 → 21:45 for margin |
| 06-25 | Box woke, server healthy for ~2 s then died, serve couldn't attach, run lost | **Single health check passed during the fragile startup window** (server answers `/api/health` then dies on the lock); the one passing check also suppressed the alert | `55f2969` — require 6 consecutive healthy checks (~12 s) before handing off to serve. Also: server hung under pipeline write-load at completion (run nearly zombied); the 06-24 run sat stuck "Running" and was reconciled to Crashed by hand |
| 06-26 | **Box never woke** | **Flow hook hibernated the box (S4):** `rundll32 SetSuspendState 0,1,0` hibernates whenever hibernation is enabled (documented gotcha; `Fast Startup=1` confirmed it on); this box's RTC wake timer does not fire from S4. Kernel-Power event 42 `TargetState` proves it (state = Sx+1): every S3 sleep (state 4) woke on the timer, the one S4 hibernate (state 5) did not | `017f7e2` — `powercfg /hibernate off` (elevated) so every suspend is S3. Plus `cedd3a4` (zombie-run heartbeat automation), `381ee6e` (log pre-flight check on success) |
| 06-27 01:40 (test 1) | Box **woke from S3 ✓** (hibernate fix worked!) but server failed `sustained: False after 120 s`, run lost; Discord alert **did** fire | **Server flaky for ~1–2 min right after wake-from-sleep** (system + SQLite settling on resume): banner prints, `/api/health` answers briefly, then dies on `database is locked`. Starting it minutes later → healthy in ~6 s and stable. Wake script made a single attempt | `53d46b1` — wake script retries the server start up to 3× (teardown + ~20 s settle + port-free wait between tries); alert only if all 3 fail |
| 06-27 10:00 (test 2) | **Box did NOT wake from a clean S3 sleep** | **RTC wake timer is INTERMITTENT on this hardware.** This sleep was confirmed S3 (event 42 state 4; `powercfg /a` shows only S3), wake timers enabled (AC=1), `PrefectWakeTest` armed & enabled for 10:00 — yet the box stayed asleep 09:31→15:55 (woke only by power button). The *same* task woke the box from S3 at 01:40 the same day. Not S3/S4 related; the timer simply doesn't fire reliably | **UNRESOLVED** — see Open Issues. Points to always-on. |

---

## 3. All `infra` commits (this saga)
```
53d46b1 fix(ops): retry server start on wake (post-resume instability)      [06-27]
017f7e2 fix(ops): disable hibernation so the box wakes for the nightly run  [06-26/27]
cedd3a4 feat(ops): auto-detect zombie flow runs via heartbeat automation    [06-26]
381ee6e feat(ops): log pre-flight DuckDB lock check on success              [06-26]
55f2969 fix(ops): gate wake handoff on SUSTAINED server health             [06-25]
a9d8a1c fix(ops): widen unattended sleep timeout so wake task can run       [06-24]
ae423ad fix(ops): atomic dashboard DB build so timeouts cant publish partial [06-23/24]
669f54e feat(ops): alert on Discord when wake health check finds server down [06-23]
55f58c0 feat(ops): pre-flight DuckDB write-lock check before pipeline run    [06-23]
9dd9453 fix(ops): harden Prefect wake restart against SQLite WAL lock race   [06-23]
```
All committed, **not pushed**. Real nightly config (`PrefectPipelineWake`, the `0 22 * * 1-5` schedule) is untouched by the test scaffolding below.

---

## 4. Current system state (as of 06-27 ~16:00)
- **Power settings (applied live, elevated):** hibernation OFF (`powercfg /a` = only Standby S3; no `hiberfil.sys`); `UNATTENDSLEEP` (AC) = 900 s; "Allow wake timers" AC = 1 (enabled). Wake task `PrefectPipelineWake` now fires 21:45.
- **Prefect server:** was DOWN at last check (needs a recovery start — see §6 commands). Data is current **through 06-26**.
- **Working tree:** `tools/_wake_test_setup.ps1`, `tools/_sleep_if_idle.ps1` are **untracked test scaffolding** (delete after testing). `notebooks/sings_of_tail.ipynb` and `.claude/settings.local.json` have unrelated local edits.
- **Test scaffolding still registered:** `PrefectWakeTest` (one-off, already fired its trigger). `PrefectSleepTest` was removed. The temp 00:40 deployment schedule + the `secret-orca` test run were cleaned up.

---

## 5. Open issues (unresolved)
1. **RTC wake timer is intermittent even from S3 (the blocker).** 06-27 10:00 failed to wake from a verified S3 sleep with the timer armed and enabled — but woke fine from S3 at 01:40. The hibernate fix removed the S4 failure mode but did NOT make wake reliable. This is firmware/hardware-level (likely BIOS RTC-alarm behavior); cannot be fully fixed in software. **`powercfg /waketimers` (elevated) at sleep time would confirm whether the timer is even armed** — not yet checked.
2. **SQLite server hangs under the pipeline's write-load** (seen 06-25 at run completion) — can leave the run unable to record completion (zombie). The `crash-zombie-flow-runs` automation (cedd3a4) + `PREFECT_FLOWS_HEARTBEAT_FREQUENCY=30` mitigate the zombie symptom but not the hang.
3. **Server post-resume instability** — mitigated by the 3× retry (53d46b1) but not eliminated.
4. **`model_proto.py:39`** opens `market_data.duckdb` read-write (should be `read_only=True`).

## 5a. RECOMMENDATION
**Go always-on** (disable the sleep hook + idle sleep; keep server+serve running 24/7; repurpose the wake task into a periodic "restart-if-down + Discord" health check). This eliminates the entire wake-timer and post-resume-server failure class at once. The only cost is ~10–20 W idle on a 16 GB box. This was first proposed 06-24 and deferred in favour of hardening the power-cycle; the 06-27 S3-wake failure is decisive evidence that the power-cycle is not reliable on this hardware. Alternative durable fix for issue #2: Postgres backend for Prefect (removes SQLite lock/hang class).

---

## 6. Useful diagnostic commands
```powershell
# Recover Prefect (hardened single start)
foreach($t in 'PrefectServer','PrefectDailyPipelineServe'){ Stop-ScheduledTask -TaskName $t }
# kill stale: python procs matching 'prefect server start|daily_pipeline_flow|run_daily_pipeline', wait :4200 free
Start-ScheduledTask -TaskName 'PrefectServer'   # wait sustained health, then:
Start-ScheduledTask -TaskName 'PrefectDailyPipelineServe'

# Why didn't it wake? Sleep STATE (state = Sx+1: 4=S3, 5=S4 hibernate):
Get-WinEvent -FilterHashtable @{LogName='System';ProviderName='Microsoft-Windows-Kernel-Power';Id=42} |
  Select TimeCreated, @{N='state';E={([xml]$_.ToXml()).Event.EventData.Data|?{$_.Name -eq 'TargetState'}|%{$_.'#text'}}}
# Sleep/wake sessions + source:
Get-WinEvent -FilterHashtable @{LogName='System';ProviderName='Microsoft-Windows-Power-Troubleshooter'}
powercfg /a                  # available sleep states (confirm hibernate off)
powercfg /lastwake           # what woke it last
powercfg /waketimers         # ELEVATED — is a wake timer actually armed?

# Server death root cause (the launcher Tee loses it): run in FOREGROUND
python -m prefect server start            # captures the real 'database is locked' traceback

# Zombie / stuck-Running flow runs: read_flow_runs filtered to RUNNING; set_flow_run_state(force=True) -> Crashed
```

## 7. Cleanup checklist (when the power-cycle work concludes)
- `Unregister-ScheduledTask PrefectWakeTest -Confirm:$false` (elevated)
- Delete `tools/_wake_test_setup.ps1`, `tools/_sleep_if_idle.ps1`
- Push `infra` and open a PR (10 commits)
