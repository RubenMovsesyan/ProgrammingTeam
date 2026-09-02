#!/usr/bin/env python3
"""Inject the team constitution plus live .team/ state into the agent's context.

Runs as a UserPromptSubmit / PostCompaction / SessionStart hook in both Devin CLI
and Claude Code. Reads the hook payload on stdin, finds the nearest .team/
directory at or above the working directory, and prints a hookSpecificOutput
JSON object with additionalContext. Prints nothing (and exits 0) when no team is
active, so installing the plugin has no effect on ordinary projects.

Never blocks and never exits non-zero: this is context, not a gate.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import teamlib  # noqa: E402

CONSTITUTION = Path(__file__).resolve().parent / "constitution.md"


def live_state(team):
    lines = ["## Live team state (generated)", f"Team directory: {team}"]
    locks = teamlib.held_locks(team)
    if locks:
        lines.append("Held locks (do NOT edit these files):")
        for l in locks:
            if l.error:
                lines.append(f"- {l.unit}: {l.error}")
            else:
                lines.append(f"- {l.unit} [{l.stage}]: {', '.join(l.files) or '<no files>'} — waiting on {', '.join(l.waiting)}")
    else:
        lines.append("Held locks: none")
    unread = teamlib.unread_findings(team)
    lines.append("Unread findings (no status line): " + (", ".join(unread) if unread else "none"))
    plan = teamlib.plan_counts(team)
    if plan:
        lines.append("Plan: " + ", ".join(f"{n} {s}" for s, n in plan.items()))
    crit = teamlib.criteria_counts(team)
    if crit:
        lines.append("Criteria: " + ", ".join(f"{n} {s}" for s, n in crit.items()))
    return "\n".join(lines)


def main():
    payload = teamlib.read_payload()
    cwd = Path(payload.get("cwd") or os.getcwd())
    team = teamlib.find_team_dir(cwd)
    if team is None:
        return
    try:
        constitution = CONSTITUTION.read_text()
    except OSError:
        constitution = "(constitution.md missing from plugin; rules unavailable)"
    event = (
        (sys.argv[1] if len(sys.argv) > 1 else None)
        or payload.get("hook_event_name")
        or ("PostCompaction" if "summary" in payload else "SessionStart" if "source" in payload else "UserPromptSubmit")
    )
    context = constitution.rstrip() + "\n\n" + live_state(team)
    print(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": context}}))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # never break the user's session over a context hook
        print(f"team-context: {exc}", file=sys.stderr)
    sys.exit(0)
