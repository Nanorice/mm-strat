# Session Handover: 2026-06-12

## 🎯 Goal
Ship the remote dashboard: carve out a slim DB, upload to Cloudflare R2, and serve via Streamlit Community Cloud with Google-email auth.

## ✅ Accomplished

- **S1 — GitHub push**: added `.env.example` (all key names: FMP, FRED, EDGAR, dashboard, R2), gitignored `.claude/scheduled_tasks.lock`, pushed `infra_uplift` to `Nanorice/mm-strat` (repo made public).
- **S2 — R2 sync script**: `scripts/sync_dashboard_db.py` uploads `dashboard.duckdb` to `R2: latest/dashboard.duckdb` (overwrites; no archive — 782 MB/day would exhaust free tier). Wired as **orchestrator Phase 7.6** (best-effort, skipped if `R2_ACCOUNT_ID` absent). `boto3` added to `requirements.txt`. First live upload succeeded: **782 MB in R2**.
- **S3 — Pull-on-boot shim**: `dashboard_utils._ensure_local_db()` downloads from R2 to `DASHBOARD_DB_PATH` on cold start or when local file size differs from R2. Atomic: downloads to `.tmp` then renames. No-op when R2 creds absent (local runs unaffected).
- **Streamlit Cloud**: bridged `st.secrets` → `os.environ` explicitly by key name before `DB_PATH` resolution. Added `duckdb` to `requirements.txt` (was missing). App now boots and the macro/regime section renders correctly.
- **Watchlist fix**: replaced live `load_prod_model()` + `score_features_df()` with `load_scored_watchlist()` — a pure SQL join of `screener_watchlist` + `daily_predictions`. No model file needed on the cloud host.

## 📝 Files Changed

- `scripts/sync_dashboard_db.py` *(new)*: R2 upload script; `--dry-run` flag; no archive.
- `scripts/dashboard_utils.py`: `_ensure_local_db()` shim; `st.secrets` bridge; `load_scored_watchlist()` loader; debug lines (temporary).
- `scripts/dashboard.py`: import `load_scored_watchlist`; replace `score_active_trades` call with it; debug caption (temporary); auth model docstring.
- `src/orchestrators/daily_pipeline_orchestrator.py`: Phase 7.6 `_run_phase_7_6_r2_sync()` wired after Phase 7.5.
- `requirements.txt`: added `duckdb>=0.10.0`, `boto3>=1.34.0`.
- `.env.example` *(new)*: all env var keys with R2 naming (`R2_ACCESS_KEY`, `R2_SECRET_KEY`, `R2_BUCKET_NAME=quantamental`).
- `.gitignore`: ignore `.claude/scheduled_tasks.lock`.

## 🚧 Work in Progress (CRITICAL)

- **Pre-breakout section still broken on cloud**: `render_pre_breakout()` at `dashboard.py:334` calls `score_features_df(pre)` which loads the prod model from disk — same `FileNotFoundError` as the watchlist had. Fix: either cache pre-breakout scores nightly into `daily_predictions` (universe scorer already covers these tickers), or hide the section when model file is absent.
- **Debug lines still in code**: `dashboard.py:712` has a `st.caption(f"DB: ...")` debug banner. `dashboard_utils.py` has `st.write(f"[DEBUG] DASHBOARD_DB_PATH...")` and a `st.warning` in the secrets bridge exception handler. Remove before treating as production.
- **Branch not merged to main**: `infra_uplift` is ahead of `main`. All commits are on `infra_uplift` only. Needs a PR + merge.

## ⏭️ Next Steps

1. **Fix pre-breakout live scoring**: make `render_pre_breakout` gracefully degrade (show table without scores) when model file absent, OR join `daily_predictions` same as watchlist — pre-breakout tickers are scored nightly by the universe scorer already.
2. **Remove debug lines**: `dashboard.py:712` caption + `dashboard_utils.py` `st.write`/`st.warning` debug output.
3. **Merge `infra_uplift` → `main`**: once pre-breakout is fixed and debug lines removed.
4. **S4 — Task Scheduler runbook**: nightly job on dev box (pipeline → Phase 7.5 build → Phase 7.6 R2 upload). Decide: builder = current dev box (simpler) or spare PC (needs full 67 GB DB migrated).
5. **Verify from phone**: confirm public URL + Google-email auth works end-to-end.

## 💡 Context/Memory

- **R2 env var names** are non-standard: Cloudflare issued `R2_ACCESS_KEY` / `R2_SECRET_KEY` (not AWS-style `_ACCESS_KEY_ID` / `_SECRET_ACCESS_KEY`). Endpoint is in `R2_JURI_ENDPOINT_URL`. Bucket name is `quantamental` (not `quantamental-dashboard` as originally planned).
- **Streamlit secrets are NOT in `os.environ`**: they live in `st.secrets` and must be explicitly pulled before any module-level `os.environ.get()` call. The bridge must enumerate keys by name — `st.secrets.items()` iteration is unreliable with nested TOML.
- **`daily_predictions` already in slim DB**: copied in full by `build_dashboard_db.py` manifest. Scores are fresh as of the last nightly pipeline run — no model file needed for read-only display.
- **`artifacts_path` in `models` table is a Windows absolute path**: `C:\Users\Hang\...` — meaningless on Streamlit Cloud. Any code that reads `row["artifacts_path"]` from the DB and tries to open it will break on cloud. `load_prod_model()` in `dashboard_utils.py` does this — it's now unused for the watchlist but still imported.
