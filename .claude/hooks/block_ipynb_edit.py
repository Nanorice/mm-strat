#!/usr/bin/env python
"""PreToolUse hook: block direct edits to .ipynb files.

Enforces the 'no direct notebook edits' rule — intended cell changes should be
written to a markdown artifact for the user to apply, never to the .ipynb.
Reads the tool-call JSON on stdin; emits a PreToolUse deny decision for any
path ending in .ipynb. Fails closed: on any parse error it denies rather than
silently allowing the edit through.

Escape hatch: set ALLOW_IPYNB_EDIT=1 in the environment to permit direct edits
for that session (user-approved override).
"""
import json
import os
import sys


def main() -> None:
    if os.getenv("ALLOW_IPYNB_EDIT") == "1":
        return  # user-approved override — allow the edit through
    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
        tool_input = data.get("tool_input", {}) or {}
        path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    except (ValueError, AttributeError):
        # Malformed input — fail closed only if it smells like a notebook edit.
        path = raw

    if str(path).lower().endswith(".ipynb"):
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    f"Direct .ipynb edits are blocked ({path}). Write intended "
                    "cell changes to a markdown artifact (e.g. "
                    "docs/session_logs/.../<topic>_cells.md) for the user to apply."
                ),
            }
        }))
    # Non-notebook path: no output, exit 0 = no decision (normal flow).


if __name__ == "__main__":
    main()
