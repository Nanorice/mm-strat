---
name: Session Handover
description: Generates a structured handover document to preserve context for the next session or developer.
---

# Instructions

When the user says "Wrap up", "End session", or "Generate handover":

1.  **Analyze** the current session history and file modifications.
2.  **Create/Update** a file named `docs/session_logs/sprint_N/logs/YYYY-MM-DD.md` in the **current sprint's `logs/` subfolder** (highest-numbered `sprint_N/`, today's date). When there's an existing file for today, update if the content builds on it; create a new one with a session-id suffix if the new session is very different.
    - Plan docs → `plans/`, findings/reports/issues → `verdicts/`, notebook-cell artifacts → `cells/`. See the sprint folder taxonomy in [session_logs/README.md](../../../docs/session_logs/README.md).
    - At **sprint end**, use the **`sprint-wrap-up`** skill (the zoom-out counterpart) to roll these daily logs into the sprint README and transition to the next sprint.
3.  **Format** the content exactly like this template:

    # Session Handover: [Date]

    ## 🎯 Goal
    [One sentence on what we tried to achieve today]

    ## ✅ Accomplished
    - [Specific Task 1]
    - [Specific Task 2]

    ## 📝 Files Changed
    - `src/changed_file.py`: [Brief reason for change]
    - `test/test_file.py`: [What was tested]

    ## 🚧 Work in Progress (CRITICAL)
    [List any logic that is half-finished, any bugs currently triggering, or unverified changes]

    ## ⏭️ Next Steps
    1. [Immediate action for the next session]
    2. [Secondary action]

    ## 💡 Context/Memory
    [Any specific "Aha!" moments, decisions made, or architectural constraints discovered that aren't obvious in the code]

4.  **Action**: After creating the file, ask the user if they want to `git add` and `git commit` it immediately.