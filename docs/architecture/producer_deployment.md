# The Producer — identity, naming, and deployment

> The TradingAgents fork that writes the report trees `research_report_engine.py`
> ingests. Written 2026-07-20, sprint 15, against the real checkout on `sh019`.

---

## 1. What to call it

**In prose, call it "the producer."** Not "TradingAgents" — that name belongs to
upstream, and the distinction is the whole point: the business analyst, the EDGAR
retrieval layer and the sidecar emitter do not exist upstream. When mm-strat docs
say "the producer changed", they mean this fork, and a reader must not go looking
in Tauric's repo for the commit.

Full identity:

| | |
|---|---|
| Fork | `github.com/Nanorice/TradingAgents` (remote `origin`) |
| Upstream | `github.com/TauricResearch/TradingAgents` (remote `upstream`) |
| Branch | `mm-strat-report` |
| Local checkout (`sh019`) | `C:\Users\sh019\Documents\projects\TradingAgents` |
| Forked from | `01477f9` — upstream `chore: release v0.3.1` |

**Cite a SHA, never a description.** mm-strat handovers that say "fixed the
structured-output retry" are unresolvable six weeks later. `producer @ 67285f3`
is not. When a session changes both repos, the mm-strat handover's *Files
Changed* gets a `### Producer (mm-strat-report)` heading listing SHAs.

**The pin lives in `config.py`,** next to the paths that read its output — a
comment naming the SHA the current ingest schema was written against. When the
version gate in `research_report_engine.py` fires, that comment is the first
thing to check.

---

## 2. Before you deploy anywhere: decide where the reports land

**This is the actual decision, and it is not a deployment detail.** The producer
writes report trees to local disk. The ingest engine reads them from local disk.
Today both are `sh019`, so the question has never been forced.

Run the producer on the research box (`Hang` / `DESKTOP-MTF20CI`) and it is
forced immediately: reports accumulate on `Hang`, `market_data.duckdb` (88 GB)
sits on `sh019`, and nothing connects them.

Three options, in order of preference:

**(a) Producer on `Hang`, drop dir synced to `sh019`, ingest stays on `sh019`.**
Recommended. The DB never moves, single-writer discipline is untouched, and the
engine needs no code change — it takes the drop root as a config-defaulted
parameter, so `RESEARCH_REPORTS_DIR` pointed at the synced folder is the entire
change. A report tree is ~100 KB; a scheduled `robocopy /MIR` or any file-sync
tool covers it.

**(b) Producer on `Hang`, ingest on `Hang`, against a copy of the DB.** Rejected.
An 88 GB copy per sync, and you now have two DBs that disagree.

**(c) Producer on `Hang` writing directly to the DB over a share.** Rejected
outright — see `duckdb-single-writer-discipline`. DuckDB tolerates one writer;
the producer runs unattended and would overlap the nightly Prefect pipeline. This
is settled in the design doc and is not reopenable as a convenience.

Whichever you pick, the filing cache matters too. `research_quote_fidelity.py`
checks quotes against `EDGAR_CACHE_DIR`. **A report ingested on a box without the
filing cache cannot be quote-scored** — the verification gate silently has
nothing to verify. If you sync the reports, sync `~/.tradingagents/cache/edgar/`
with them.

---

## 3. Deploying the producer on a second box

Assumes Python ≥3.10 and git. On `Hang`, the research box.

### 3.1 Clone the fork

```powershell
cd $HOME\Documents\projects
git clone https://github.com/Nanorice/TradingAgents.git
cd TradingAgents
git remote add upstream https://github.com/TauricResearch/TradingAgents.git
git checkout mm-strat-report
```

`origin` is the fork, `upstream` is Tauric. Getting these backwards means a
`git push` attempt against a repo you don't own — it fails, but confusingly.

### 3.2 Its own venv — never mm-strat's

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

The producer pulls the whole LangChain/LangGraph stack; mm-strat pulls DuckDB,
Streamlit and the modelling stack. They are separate dependency trees and share
nothing. Installing one into the other's venv is how you break both.

### 3.3 Credentials and config

Copy `.env` from the `sh019` checkout — it is gitignored and not in the fork.
Required:

```
TRADINGAGENTS_LLM_PROVIDER=openrouter
TRADINGAGENTS_DEEP_THINK_LLM=<model>
TRADINGAGENTS_QUICK_THINK_LLM=<model>
OPENROUTER_API_KEY=...          # or the provider key matching the line above
TRADINGAGENTS_SEC_USER_AGENT=<name> <email>   # SEC blocks unidentified clients
```

`TRADINGAGENTS_SEC_CIK_OVERRIDES` and `FRED_API_KEY` are optional; the remaining
provider keys in the file are only needed if you switch providers.

Optional path overrides, if the defaults under `~/.tradingagents/` don't suit:
`TRADINGAGENTS_RESULTS_DIR`, `TRADINGAGENTS_CACHE_DIR`.

**Move the `.env` by hand.** Do not commit it, do not paste keys into a chat or a
doc, and do not let a sync job that mirrors the drop dir also mirror the repo.

### 3.4 Smoke test before spending

```powershell
.venv\Scripts\python.exe -m pytest        # expect ~613 passed, 2 skipped
```

The 2 skips are `langchain_aws` and `DEEPSEEK_API_KEY`, both unrelated.

Then one real run — a name with a US 10-K:

```powershell
.venv\Scripts\python.exe run_unattended.py RKLB
```

**Check three things before running a batch:**

1. `<results>/reports/RKLB_<stamp>/` has `complete_report.md`, `report.json`
   *and* `manifest.json`. Missing sidecars make the run un-ingestable —
   `NVDA_20260714_135243` on `sh019` is the cautionary example.
2. `report.json → agents.business_analyst` is **not null**. Null means the
   structured call fell back to free text; the run is unscoreable and the
   dashboard now flags it as such. Two producer bugs causing this were fixed in
   `67285f3` — a null here on a fresh checkout means the fix isn't present.
3. `manifest.usage.reported_cost_usd` is roughly $0.07–0.15. Wildly higher means
   a model override didn't take.

**Foreign private issuers have no 10-K and will fail pre-flight** — NOK, ARM
(20-F), Canadian 40-F filers. Not a bug; check before spending a run.

### 3.5 Wire the transport (option (a))

Sync both directories from `Hang` to `sh019`:

```
<results>/reports/          ->  %USERPROFILE%\.tradingagents\logs\reports\
<cache>/edgar/              ->  %USERPROFILE%\.tradingagents\cache\edgar\
```

Then on `sh019`, point the engine at the landing spot if it differs from the
default, and ingest:

```powershell
# mm-strat, sh019
.venv\Scripts\python.exe -c "from src.research_report_engine import ResearchReportEngine; print(ResearchReportEngine().ingest_drop_dir())"
```

Re-running is a no-op — already-seen `run_id`s are skipped, so a repeated sync
plus a repeated ingest returns `(0, n)`. Ingest is safe to schedule.

⚠️ **Ingest has no orchestrator phase yet.** `phase_registry.py` contains no
research entries, so this is a manual step and a sync that silently stops will
not show up in the pipeline heatmap. Adding a phase is open work.

---

## 4. Staying current with upstream

```powershell
git fetch upstream
git rebase upstream/main        # on mm-strat-report
.venv\Scripts\python.exe -m pytest
```

Rebase rather than merge — the fork should stay a readable stack of "what we
added", not a thicket of merges. If a rebase touches `reporting.py` (the sidecar
emitter) or `schemas.py`, **re-run one name and diff `report.json` against a
known-good run before trusting it.** Those two files are the contract mm-strat
ingests; the version gate catches a declared major bump, not a quiet field
rename.

---

## 5. The failure this setup is designed to prevent

Before 2026-07-20 the producer's entire mm-strat-specific layer — business
analyst, EDGAR retrieval, usage tracking, sidecar emission, ~1000 insertions
across 26 modified and 10 untracked files — sat **uncommitted** on a pristine
upstream release checkout. No branch, no remote, no backup. A single
`git checkout .` would have deleted the thing all of sprint 15 was built on, and
mm-strat's session logs recorded the changes only as prose.

The fork exists so that state cannot recur. The rule that follows from it:
**producer work is not done until it is committed and pushed to the fork.** An
mm-strat handover that describes a producer change without a SHA is describing
something that may not exist tomorrow.
