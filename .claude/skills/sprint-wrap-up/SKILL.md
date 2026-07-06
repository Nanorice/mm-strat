---
name: sprint-wrap-up
description: >
  Close out a research sprint: roll the daily session handovers up into the sprint's
  README front page, enforce the docs/session_logs/sprint_N folder taxonomy
  (logs/plans/verdicts/cells), clean scratch (caches/parquets out of docs/), update the
  session_logs index, and seed the next sprint's README from carried-over TODOs. Use when
  the user says "wrap up the sprint", "close sprint N", "sprint retro", "start sprint N+1",
  or is otherwise finishing one sprint and transitioning to the next. This is the
  SPRINT-level counterpart to the per-session `handover` skill — handover zooms in on one
  day, this zooms out over the whole sprint. Trigger even if "skill" isn't said, whenever
  the subject is finalising a sprint's docs and rolling into the next.
---

# sprint-wrap-up

Zoom-out counterpart to `handover`. `handover` writes one `logs/YYYY-MM-DD.md` per session;
this consumes a sprint's worth of those into a front page and rolls into the next sprint.

**Do not re-derive what the daily logs already say.** The logs ARE the record — this skill
*organises and rolls them up*, it does not re-investigate the work. Read them, summarise, move
files, seed the next sprint. That's it.

## When to run
End of a sprint / start of the next. If the user names the sprint ("close sprint 13"), use that;
else infer the current sprint = highest-numbered `docs/session_logs/sprint_N/`.

## The taxonomy (enforce this)
```
sprint_N/
  README.md      front page (see template below)
  logs/          dated session handovers  YYYY-MM-DD.md
  plans/         forward-looking design/plan docs (written BEFORE the work)
  verdicts/      findings / reports / issues / playbooks (what we CONCLUDED)
  cells/         notebook-cell artifacts (no-direct-.ipynb-edit rule); scratch once applied
```
Rules:
- Caches, `.parquet`, large `.log`, model outputs → **`data/`** (e.g. `data/backtest_cache/`), NEVER `docs/`. If a script references the old path, patch the script.
- Cross-session facts → **memory** (`MEMORY.md` + a memory file), NOT the sprint doc.
- One `README.md` per sprint is the ONLY root file; everything else lives in a subfolder.
- Prefer `git mv` over `mv` for tracked files (preserves history). Fix intra-doc links after moving.

## Steps

1. **Inventory.** List the sprint folder. Classify each loose root file into logs/plans/verdicts/cells.
   Flag: duplicates ("* copy.md"), files >1MB, `.parquet`/`.log`, anything already superseded.

2. **Verify before deleting.** For any cache/parquet/large file, grep `src/ scripts/ tools/ docs/`
   for its path. If a script uses it as a re-runnable cache → **relocate to `data/` and patch the
   script's path**, don't delete. If it's a genuine untracked duplicate/draft → delete. Never delete
   a tracked file without confirming it's superseded.

3. **Restructure.** Create `logs/ plans/ verdicts/ cells/`. `git mv` files in by category. Remove
   empty leftover dirs. Rewrite any now-broken relative links inside the README.

4. **Front page.** Rename/promote the sprint's roadmap/summary doc to `README.md` (or create one).
   Add the header block (template below) with dates, status, headline outcomes, folder map. Keep the
   existing roadmap body — don't rewrite it, just top it with the header.

5. **Roll up.** Skim `logs/*.md` — each has ✅ Accomplished / ⏭️ Next Steps. Distil the sprint's
   headline outcomes (5–8 bullets, verdict-first: what got banked, what got falsified) into the
   README header. This is the one place a human reads to know what the sprint achieved.

6. **Carryover → next sprint.** Grep the sprint for unchecked TODOs and "deferred / next sprint /
   remaining / optional" notes. Create `sprint_{N+1}/README.md` from the template, pre-filled with a
   **## Carried over from sprint N** checklist. Leave a **## New goals (sprint N+1)** section for the
   user to fill. Ask the user to confirm/add goals.

7. **Update the index.** Add/refresh the sprint's row in `docs/session_logs/README.md` (dates, theme,
   status Closed). Add the next sprint's row (status Active).

8. **Memory sweep.** Ask: did any cross-session fact surface this sprint that isn't yet in memory?
   If yes, write a memory file + `MEMORY.md` pointer (per the memory protocol) — do NOT put it in the
   sprint doc.

9. **Commit.** Show the diff summary, ask the user whether to `git add` + commit the restructure.
   Suggested message: `docs(sprint N): wrap-up — taxonomy, front page, seed sprint N+1`.

## Sprint README template
```markdown
# Sprint N — <theme>

**Dates:** YYYY-MM-DD → YYYY-MM-DD · **Status:** 🔄 Active | ✅ Closed · **Next:** [sprint_N+1](../sprint_N+1/README.md)

> <one-paragraph framing: the core question / goal of the sprint.>

### Folder map
- **`logs/`** — dated session handovers.
- **`plans/`** — forward-looking design/plan docs.
- **`verdicts/`** — findings, reports, issues, playbooks.
- **`cells/`** — notebook-cell artifacts.

### Headline outcomes
- **<verdict>** — <one line, banked-or-falsified first>.
- ...

## Roadmap & Goals
<the sprint's living goal list — checkboxes, statuses. This is the working body.>

## Carried over from sprint N-1
- [ ] <deferred item> — <why / pointer>

## TODOs
<sprint-local isolated TODOs. Cross-session facts go to memory, not here.>
```

## Guardrails
- **Don't rewrite history.** Preserve the audit trail (even "WRONG diagnosis, later corrected" notes stay — they're the record). Roll up, don't redact.
- **Don't author new prose docs.** This skill *organises* existing docs; the only new files are the two READMEs (index + next-sprint front page).
- **Ponytail.** Moving files and writing two index pages. No script, no tooling — the restructure is a handful of `git mv`s. If the user asks to automate it recurring, then consider a script.
