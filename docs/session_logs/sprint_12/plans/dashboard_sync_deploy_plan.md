# Dashboard Remote Sync + Deploy Plan

**Date:** 2026-06-11
**Sprint:** 12 (infra_uplift), T1 follow-up
**Status:** PLAN — not yet executed

---

## Goal (user's vision)

1. Dashboard runs on a cloud host (Google Cloud-style), codebase deployed there.
2. Reachable from the phone via a public URL with simple auth.
3. **Next phase:** daily pipeline runs automatically (cron) on the dev box, rebuilds the
   783 MB slim DB, syncs it to the cloud, and the remote dashboard reflects the new data.

## Constraints chosen (2026-06-11)

| Decision | Choice | Implication |
|---|---|---|
| Pipeline host | **Dev box builds, cloud serves** | 67 GB full DB + API keys stay local. Only the 783 MB slim DB travels. Dev box must be on for the nightly run. |
| Phone access | **Public URL + simple auth** | Need an auth layer — the app today is explicitly localhost-only, no login. |
| Budget | **Near-free / cheapest** | Free tiers + object-storage cents. Accept some setup friction. |

---

## The architecture

```
┌─────────────────── DEV BOX (your PC) ───────────────────┐
│  full market_data.duckdb (67 GB)                        │
│  daily pipeline (cron)  ──►  build_dashboard_db.py       │
│                              dashboard.duckdb (783 MB)   │
│                                     │                    │
│                                     ▼  upload nightly    │
└─────────────────────────────────────┼───────────────────┘
                                       │
                            ┌──────────▼──────────┐
                            │  OBJECT STORAGE     │   GCS bucket / Cloudflare R2
                            │  dashboard.duckdb    │   (versioned, ~cents/mo)
                            └──────────┬──────────┘
                                       │ pull-on-boot / refresh
┌──────────────────── CLOUD HOST ──────▼──────────────────┐
│  Streamlit app (codebase from GitHub)                   │
│  DASHBOARD_DB_PATH → local copy of pulled slim DB        │
│  behind auth  ──►  public HTTPS URL  ──►  📱 phone       │
└─────────────────────────────────────────────────────────┘
```

The `DASHBOARD_DB_PATH` env var (already shipped) is the seam that makes this work: the
cloud host sets it to wherever it drops the pulled slim DB.

---

## The tension to resolve: "public URL" vs "near-free"

A public URL needs an always-on HTTPS listener. Two ways to get one cheaply:

### Option A — Streamlit Community Cloud (recommended for near-free)
- **Host:** free. Deploys straight from the GitHub repo. Gives a public `*.streamlit.app` URL.
- **Auth:** built-in viewer allowlist by Google email (you add your own Google account) —
  satisfies "simple auth" with zero auth code.
- **Slim DB delivery:** the app pulls `dashboard.duckdb` from object storage on boot
  (and on a refresh button / TTL). Needs a public-read or signed-URL bucket.
- **Cost:** $0 host + object storage (~$0.02/GB/mo for <1 GB = cents).
- **Caveat:** app sleeps when idle, cold-start on first hit (~30s). Fine for personal use.
- **Caveat:** repo must be pushable to GitHub (T1's "upload to GitHub" sub-task) — code only,
  data already gitignored.

### Option B — Cheap always-on micro VM (GCP e2-micro free tier)
- **Host:** GCP `e2-micro` is in the always-free tier (1 region). Runs Streamlit as a service.
- **Auth:** add an auth layer (see below) OR put Cloudflare Access / oauth2-proxy in front.
- **Slim DB delivery:** dev box `scp`/`rsync` pushes `dashboard.duckdb` to the VM nightly,
  OR the VM pulls from object storage. No cold starts.
- **Cost:** $0 VM (free tier) + egress cents. Slightly more setup (firewall, systemd, HTTPS via Caddy).
- **Caveat:** e2-micro is small (1 vCPU, 1 GB RAM) — fine to *serve* the slim DB, not to run the pipeline.

**Recommendation:** start with **Option A (Streamlit Community Cloud + object storage)** — it's
the genuinely-near-free path that gives a public URL + auth with the least new code. Move to a VM
only if cold starts annoy you or you later want the pipeline in the cloud too.

---

## Auth — what "simple auth" means per option

- **Streamlit Community Cloud:** viewer allowlist by Google email. Zero code. ✅ simplest.
- **VM path:** either
  - `streamlit-authenticator` (password hash in secrets) — a few lines, OR
  - Cloudflare Tunnel + Cloudflare Access (Google login, free tier) in front of the VM — no app code,
    and also gives free HTTPS + hides the VM IP.

The app header currently says *"NEVER expose --server.address 0.0.0.0 ... localhost-only single-user
UI with no auth."* — that comment must be revisited; whichever auth path we pick, document it there.

---

## Object storage choice

| Option | Near-free? | Notes |
|---|---|---|
| **Cloudflare R2** | ✅ 10 GB free, **zero egress fees** | Best for pull-on-boot (no egress surprises). S3-compatible. |
| **Google Cloud Storage** | ✅ 5 GB free tier | Natural if the rest is GCP. Egress beyond free tier costs. |
| **Backblaze B2** | ✅ 10 GB free | Cheap, S3-compatible. |

**Recommendation:** **Cloudflare R2** — zero egress means the cloud host can re-pull the 783 MB
freely without bill creep. DuckDB can even read it directly via `httpfs` + signed URL if we want to
skip the local-copy step.

---

## Phased execution plan

### Phase S1 — GitHub push (prereq, from T1 §4.2)
- [ ] Confirm `data/*.duckdb` never committed: `git log --all --oneline -- data/market_data.duckdb` (must be empty).
- [ ] Scan for secrets: ensure `.env` is gitignored (it is), add `.env.example` with key NAMES only.
- [ ] Decide model-artifact policy: `models/*/v2/model.json` (small XGBoost JSON) — keep in git or Git LFS.
- [ ] First push of `infra_uplift` (code only).

### Phase S2 — Object storage + upload step
- [ ] Create R2 bucket `quantamental-dashboard`.
- [ ] Add `scripts/sync_dashboard_db.py` — uploads `data/dashboard.duckdb` to the bucket
      (boto3 / S3-compatible). Idempotent, overwrites `latest/dashboard.duckdb`, optionally keeps a
      dated copy.
- [ ] Wire it as **Phase 7.6** in the orchestrator (right after 7.5 build), best-effort like 7.5 —
      OR call it from the same cron after the pipeline. Credentials from `.env` (R2 keys), never committed.

### Phase S3 — Cloud serve + auth
- [ ] Streamlit Community Cloud: connect the GitHub repo, set `DASHBOARD_DB_PATH` + R2 creds as
      Streamlit secrets.
- [ ] Add a small DB-fetch shim: on boot, if `DASHBOARD_DB_PATH` points at a remote/missing local file,
      download from R2 to a temp path first. (Keep `dashboard_utils.DB_PATH` logic; add a `_ensure_local_db()`.)
- [ ] Set the viewer allowlist to your Google email.
- [ ] Revisit the localhost-only header comment; document the deployed auth model.
- [ ] Verify from phone browser.

### Phase S4 — Daily automation (the "next phase" you asked for)
- [ ] Windows Task Scheduler entry on the dev box: nightly `run_daily_pipeline.py` (which now ends
      with Phase 7.5 build + Phase 7.6 upload). This is the cron equivalent on Windows.
- [ ] Confirm end-to-end: pipeline runs → slim DB rebuilt → uploaded to R2 → remote dashboard shows
      fresh data on next load.
- [ ] Alerting: pipeline/upload failure should notify (reuse existing Phase 8 alert path or a simple
      log-watch).

---

## Resolved decisions (2026-06-11)

1. **GitHub repo:** use the **existing** repo `github.com/Nanorice/mm-strat` (current `origin`).
   ✅ **Verified safe to push:** no `.duckdb` database file was ever committed (the `bad8ba6` hit was
   filenames *containing* "duckdb" — Python scripts/docs, not a DB). Largest blob ever = 12 MB
   (`repomix-output.md`). No history rewrite needed.
2. **Object storage:** **Cloudflare R2** (zero egress, 10 GB free).
3. **Cloud host:** **Streamlit Community Cloud** — cold starts accepted.
4. **Nightly job host:** a **spare PC** (not the current dev box) that gets woken and runs the job.
   Needs a wake + scheduled-run runbook → written in **Phase S4** below. Implication: the slim DB +
   the pipeline must be runnable on that spare PC (it needs the full 67 GB DB + `.env` keys locally,
   OR the spare PC pulls/holds its own copy — decide in S4).

## Spare-PC nightly job — what S4 must cover

- **Wake:** Wake-on-LAN (BIOS + NIC enabled) or BIOS "wake at time" / Task Scheduler "wake the computer
  to run this task" flag.
- **Run:** Windows Task Scheduler job → `run_daily_pipeline.py` (ends with Phase 7.5 build + 7.6 upload).
- **Prereq on spare PC:** the full `market_data.duckdb` + `.env` (FMP/FRED/EDGAR/R2 keys) must live there,
  since "dev box builds" means *that* box is now the builder. Either migrate the 67 GB DB to it, or
  keep the builder = current PC and let the spare PC be a *different* role. **Clarify in S4 which PC is
  the builder** — this slightly reopens the "which box runs the pipeline" question for the spare-PC case.
- **Sleep:** optional `psshutdown`/`shutdown /h` at job end to return the spare PC to sleep.
