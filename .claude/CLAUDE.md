# Claude Code Rules

## Environment (verify before running anything)
- **Python / venv**: always use the project-local `.venv` — `.venv/Scripts/python.exe`
  (activate: `.venv/Scripts/Activate.ps1`). The relative path works on every machine; do
  NOT hardcode an absolute user path.
- **Which machine am I on?** Check `$USERNAME` / `$COMPUTERNAME`:
  - `Hang` (DESKTOP-MTF20CI) → **research/dev box** (EDA, modelling, backtests). Default context.
  - `sh019` → **infra/ops box** — the self-hosted **Prefect** server + nightly scheduler run
    here (`flows/daily_pipeline_flow.py`). Treat ops/scheduling work as live on this machine;
    be cautious with anything that touches the running Prefect server or the nightly task.
  Both machines have their own project-local `.venv`, so the relative path resolves correctly on each.
- **Main DB**: `data/market_data.duckdb`. Notebook/interactive connections **MUST** be `read_only=True` (an open kernel locks the DB against all writers).
- **Tests**: `.venv/Scripts/python.exe -m pytest tests/` (dir is `tests/`, not `test/`).
- **Shell**: PowerShell primary. Bash tool available for POSIX scripts.

## Codebase Map (where things live)
Read the deep docs (below) for *why*; this is *where*.

- **Engines (data I/O)** → `src/*_engine.py` (data, fundamental, shares, macro, edgar, earnings, company_profile). Each fetches and writes one raw table.
- **Pipelines (compute)** → `src/feature_pipeline.py` (daily_features T1→T3), `src/regime_pipeline.py` (M03 regime).
- **Managers (state/lifecycle)** → `src/managers/`: `view_manager.py` (DuckDB views), `screener_manager.py`, `sepa_watchlist_manager.py`, `pipeline_run_manager.py`.
- **Orchestrator (workflow)** → `src/orchestrators/daily_pipeline_orchestrator.py` + `phase_registry.py` (stable phase IDs).
- **Model registry** → `src/model_registry.py` (feature_catalog, model_feature_sets). NOT ViewManager.
- **Backtest** → `src/backtest/` (`runner.py`, `sepa_strategy.py`, `universe_scorer.py`, `vectorized_backtest.py`).
- **Data loaders** → `src/data_loader_duckdb.py` (`load_training_data_from_db`).
- **CLI entrypoints** → `scripts/` (e.g. `run_daily_pipeline.py`, `create_duckdb_views.py`, `refresh_training_cache.py`, `build_model_card.py`).

## Deep docs — read on demand (progressive disclosure)
- **Terminology → `docs/architecture/glossary.md`** (SHORT, ~120 lines — read it whole).
  The definition of record for ambiguous terms. **Check it before naming anything or
  before reading a term you're not certain of**: several live names are ambiguous
  (`cone` = label vs strategy), uninformative (`sepa_watchlist` = trade sessions), or
  false (`prob_elite` is not always a probability; `trend_c8` computes C1+C2+C6).
  If code and the glossary disagree, one is a bug — say which.

These are large (~1k–1.5k lines each). Do NOT read whole; jump to the named section.
- **Full methodology / replication** → `docs/architecture/comprehensive_methodology.md`
  (sections: Feature Engineering, Market Regime M03, SEPA Session Mgmt, ML Methodology, Backtesting, Ops).
- **Ops quick-reference / runbooks** → `docs/architecture/manual_for_me.md`
  (sections: Phase Map, Key Tables, Audit System, Ticker Lifecycle, Model Training, Backtesting, Runbooks, Open TODOs).
- **Pipeline diagram (source of truth)** → `docs/architecture/data_flow.mmd`
- **Active research** → `docs/research/`, **session logs** → `docs/session_logs/sprint_N/`.

When a fact about schema/phases/tables is needed and not in the loaded memory index, grep these docs before re-deriving from code.

## File Structure Rules (where new files go)
- `src/` → core logic, reusable classes, production modules (`snake_case.py`).
- `scripts/` → human-run executables (`verb_noun.py`).
- `tools/` → one-off debug / maintenance tools.
- `tests/` → unit tests matching `src` modules.
- `docs/` → research, session logs, architecture. **Do NOT author prose docs proactively** — confirm scope/location with the user first, then place under the right subfolder.
- `scratch/` or the session scratchpad → throwaway exploration. Delete debug files at session end.

## Critical Thinking Protocol (PRIORITY)
You are a Senior Engineer, not a text generator.
1. **Challenge weak logic** — if a request introduces coupling, a God Class, or breaks the MECE layer design, STOP and propose a refactor first.
2. **Simplify** — before writing a new script, ask "can this reuse an existing `src/` class?"
3. **No yes-man behavior** — point out flaws directly; don't apologize for it.

## First Principles (MANDATORY)
1. **No band-aids** — don't silence a bug with `try/except` or `if x is not None`. Identify the *structural flaw* (wrong data flow? unclear class responsibility?) and fix the design.
2. **Conciseness > compatibility** — prefer deleting code over adding it. Break up complex functions instead of adding edge-case flags.
3. **Logic review** — when fixing, first summarize the component's high-level logic to confirm it makes sense.
4. **Reproduce → fix → verify** — for a "fix X" request, run the relevant test first to reproduce, then fix, then re-run.

## Smart Confirmation
- **Complex/ambiguous/refactor** → restate the plan, ask "Shall I proceed?"
- **Standard task with a clear path** → execute immediately, no permission-seeking.

## Coding Standards
- **Naming**: `snake_case` for vars/functions, `PascalCase` for classes.
- **Typing**: type hints required on all function signatures.
- **Docs/comments**: terse. No module docstrings or verbose comments unless logic is genuinely complex.
- **Errors**: specific exceptions, never bare `except:`.

## Data Query Safety (DuckDB)
- Scope queries to views (`v_d2_training`, `v_d3_deployment`, `daily_features`, `price_data`). Bare `SELECT *` or `COUNT(DISTINCT (ticker,date))` on raw tables OOMs the session.
- `price_data.volume` is `UBIGINT` — `CAST(volume AS BIGINT)` before any subtraction.
- `adj_close`/`adj_factor`/`vwap` are 100% NULL — compute returns from `close`.

## Notebooks
- **Never edit `.ipynb` directly** (default). Write intended cell changes to a markdown artifact (e.g. `docs/session_logs/.../<topic>_cells.md`); the user applies them. A PreToolUse hook (`block_ipynb_edit.py`) enforces this.
- **Escape hatch (user-approved):** set `ALLOW_IPYNB_EDIT=1` in the environment to permit direct `.ipynb` edits for that session. Only use with explicit user approval; still smoke-test cell logic before writing.

## Long Runs
- Before any long run, CHECK WITH THE USER to run a small smoke-test batch first. Require progress logging (`flush=True`) + checkpoint/resume.

## Emoji / Console Output (Windows encoding)
Only use these tested glyphs; copy-paste them, never `\U…` escapes:
- Status: ✅ ❌ ⚠️ 🛑 🔒 🔓   ·  Progress: ⏳ 🔄 1️⃣ 2️⃣ 3️⃣   ·  Actions: 📋 📅 📊 🔧 🚀 💾 📁 🔍 🧹 💡 ⚙️ 🔔 📝 📦 🔗 📈 📉
- When unsure, use ASCII `[OK]` / `[WARN]` / `[ERR]`.

## Session End
- When the user says "Wrap up", trigger the **handover** skill.
