#!/usr/bin/env python
"""PostToolUse hook: warn when a research cells/*.md artifact is not notebook-grade.

Companion to block_ipynb_edit.py. That hook enforces the WHERE (don't edit .ipynb,
write a markdown artifact). This one guards the WHAT: a `cells/*.md` deliverable must
be notebook-GRADE, not a flat prose report — the regression on 2026-07-08 was a
`cells` file with text tables and no visuals (see feedback_no_direct_notebook_edits).

SCOPE (user, 2026-07-08): RESEARCH artifacts only — this fires solely on paths under a
`cells/` dir (session-log deliverables), never on src/scripts/production code. It's a
fast local file read (exits silently on any non-cells path), so it never becomes a long
job that would need its own permission prompt.

Missing any notebook-grade marker -> NON-blocking warning back to the model (exit 2 =
feedback, not deny). It never blocks: a legitimately chart-free cells file can proceed.
"""
import json
import re
import sys
from pathlib import Path

CODE_FENCE = re.compile(r"```(?:python|py)\b", re.I)
EMBED_IMG = re.compile(r"!\[[^\]]*\]\([^)]+\.png\)", re.I)
ASSERT = re.compile(r"\bassert\b")


def main() -> None:
    try:
        data = json.loads(sys.stdin.read())
        path = (data.get("tool_input", {}) or {}).get("file_path", "") or ""
    except (ValueError, AttributeError):
        return  # can't parse -> stay silent, this is only a quality nudge

    p = Path(path)
    # RESEARCH scope: only cells/*.md deliverables — not scripts, not production, not other docs
    if p.suffix.lower() != ".md" or "cells" not in {part.lower() for part in p.parts}:
        return
    try:
        text = p.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return

    missing = []
    if not CODE_FENCE.search(text):
        missing.append("runnable ```python code cells")
    if not ASSERT.search(text):
        missing.append("at least one `assert` self-check on real logic")
    if not EMBED_IMG.search(text):
        missing.append("an embedded matplotlib figure  ![](../../../../data/...png)")
    # name convention: exemplars are <topic>_cells.md, not *_review.md / *_report.md
    if not p.stem.lower().endswith("_cells") and not p.stem.lower().endswith("-eda"):
        missing.append(f"the *_cells.md name convention (got '{p.name}')")

    if missing:
        bullets = "\n".join(f"  - {m}" for m in missing)
        print(
            f"[cells-quality] {p.name} may not be notebook-grade. Missing:\n{bullets}\n"
            "A cells/*.md must match the exemplars (e.g. "
            "docs/session_logs/sprint_14/cells/m1_tail_magnitude_cells.md): runnable "
            "code + self-check asserts + embedded charts. If this file is intentionally "
            "chart-free, proceed — this is a nudge, not a block.",
            file=sys.stderr,
        )
        sys.exit(2)  # PostToolUse exit 2 -> stderr is surfaced to the model as feedback


if __name__ == "__main__":
    main()
