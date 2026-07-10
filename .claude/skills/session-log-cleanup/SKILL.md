---
name: session-log-cleanup
description: Clean up session log folders by automating taxonomy enforcement and file migration. Use this whenever the user wants to restructure, format, or clean up an older sprint folder (e.g. docs/session_logs/sprint_11) into the structured taxonomy (logs/, plans/, verdicts/, cells/). This automates the heavy lifting of sprint-wrap-up.
---

# session-log-cleanup

This skill automates the folder restructuring of sprint folders according to the `docs/session_logs` taxonomy. It bundles a Python script that automatically handles folder creation, `git mv` file migration, and generating `YYYY-MM-DD_index.md` daily session summaries.

## Instructions

1. **Verify the target sprint folder:** Ask the user which sprint folder they want to clean up if it's not clear (e.g., `sprint_11`, `sprint_10`).
2. **Run the cleanup script:**
   Run the bundled Python script on the target folder:
   ```bash
   python .claude/skills/session-log-cleanup/scripts/restructure_sprint.py <path_to_sprint_folder>
   ```
   *Note*: The `<path_to_sprint_folder>` should be the path to the sprint, like `docs/session_logs/sprint_11`.

3. **Check the Output:**
   The script will:
   - Create `logs/`, `plans/`, `verdicts/`, `cells/`
   - Move dated logs (`YYYY-MM-DD*.md`) into `logs/`
   - Move non-dated logs into `verdicts/` by default (some may need to be manually moved to `plans/` if they are forward-looking).
   - Generate `_index.md` files for days with multiple sessions.

4. **AI Summarization & Completion (MANDATORY):**
   - The Python script only generates *skeleton* `README.md` and `RESEARCH_LOG.md` files.
   - You MUST read the contents of the newly moved `logs/` and `verdicts/`.
   - Synthesize the findings, and use your code editing tools to fill in the `README.md` (Headline outcomes, Roadmap) and `RESEARCH_LOG.md` (sequenced research threads).
   - This must be done automatically without asking the user to do it.
