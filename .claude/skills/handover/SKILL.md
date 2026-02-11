---
name: Session Handover
description: Generates a structured handover document to preserve context for the next session or developer.
---

# Instructions

When the user says "Wrap up", "End session", or "Generate handover":

1.  **Analyze** the current session history and file modifications.
2.  **Create/Update** a file named `docs/session_logs/YYYY-MM-DD.md` (use today's date). If a file with same name exists, check first if content overlap with this session, if so rename the existing file docs `YYYY-MM-DD-Session-n.md`, where n is the index of handover note for the day. Unless user specifies which file to update.
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