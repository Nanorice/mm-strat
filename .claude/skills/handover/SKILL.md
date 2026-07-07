---
name: Session Handover
description: Generates a structured handover document to preserve context for the next session or developer.
---

# Instructions

When the user says "Wrap up", "End session", or "Generate handover":

1.  **Analyze** the current session history and file modifications.

2.  **Name the file** in the **current sprint's `logs/`** (highest-numbered `sprint_N/`, today's date):
    - **First session of the day** → `logs/YYYY-MM-DD.md`.
    - **Second+ session of the day** → the day has multiple sessions. Do this:
      1. Rename the existing single file to `logs/YYYY-MM-DD_01_<slug>.md` (slug = 2–4 word topic) if it isn't already suffixed. Use `git mv` if tracked.
      2. Write the new one as `logs/YYYY-MM-DD_02_<slug>.md` (increment the number, own slug).
      3. Create/update a **day meta file** `logs/YYYY-MM-DD_index.md` — a thin pointer listing each session that day with a one-line summary and link (template below). This is the per-day reference so `YYYY-MM-DD` resolves to a table of contents, not one file.
    - If today's new session simply *continues* the same topic as the existing single file, update it in place instead of splitting (judgement call — split when the topics differ, continue when they build).
    - Plan docs → `plans/`, findings/reports/issues → `verdicts/`, notebook-cell artifacts → `cells/`. See the taxonomy in [session_logs/README.md](../../../docs/session_logs/README.md).

3.  **Format** the handover exactly like this template:

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

4.  **Update the RESEARCH_LOG** (the sprint's question ledger, `sprint_N/RESEARCH_LOG.md`) — this is
    the linear train-of-thought that survives across sessions. If the sprint has one:
    - Append one line **per key question/topic** the session opened or resolved, in sequence, to the
      relevant Thread (or a new Thread). Format: `N. **Question?** → one-line outcome. link` — using
      `→` for outcome, `⟳` for "a later finding revised this", `?` for still-open.
    - Move any question that became a cross-session fact into **memory** and mark the ledger line
      resolved; leave open questions in the "Open meta-questions" block.
    - Keep it TERSE — one line each, no prose. If the sprint has no `RESEARCH_LOG.md` yet and the
      session produced ≥2 linked research questions, create one (header block + Thread A).
    - Skip entirely for pure ops/infra sessions with no research questions.

5.  **Action**: After writing, ask the user whether to `git add` + commit the handover (+ RESEARCH_LOG).

6.  **Resume prompt**: After the doc is written (and after the commit, if the user commits), output a
    ready-to-paste **resume prompt for the next session** in a fenced code block. It must be
    self-contained — the next session starts cold. Include:
    - which files to read first, in order (this handover; the sprint `RESEARCH_LOG.md`; the 1–3 most
      relevant memory files by name);
    - a one-line state-of-play (where we are / what's settled vs open);
    - the concrete next steps in dependency order (from ⏭️ Next Steps / the ledger's open questions);
    - any hard caveat the next session must not violate (e.g. "don't act on a single-horizon result").
    Keep it tight — a prompt, not a duplicate of the handover. End by telling the next session to
    confirm scope with the user before large work.

## Day meta-file template (`logs/YYYY-MM-DD_index.md`, only when >1 session that day)
```markdown
# Sessions — YYYY-MM-DD

Multiple sessions this day. Each is a separate handover; this is the index.

1. [01 — <slug>](YYYY-MM-DD_01_<slug>.md) — <one-line what it did>
2. [02 — <slug>](YYYY-MM-DD_02_<slug>.md) — <one-line what it did>
```

- At **sprint end**, the **`sprint-wrap-up`** skill (the zoom-out counterpart) rolls these daily logs
  + the RESEARCH_LOG into the sprint README. handover zooms in on one session; sprint-wrap-up zooms out.
