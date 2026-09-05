#!/usr/bin/env python3
"""Inject the team constitution plus live .team/ state into the agent's context.

Runs as a UserPromptSubmit / PostCompaction / SessionStart hook in both Devin CLI
and Claude Code. Reads the hook payload on stdin, finds the nearest .team/
directory at or above the working directory, and prints a hookSpecificOutput
JSON object with additionalContext. Prints nothing (and exits 0) when no team is
active, so installing the plugin has no effect on ordinary projects.

What it injects depends on the mode in .team/state.json: `build` and `audit` get
the constitution plus live state; `dormant` gets a few lines saying how much work
is waiting to be audited and nothing else. A finished team must not keep pulling
the loop into unrelated prompts.

Never blocks and never exits non-zero: this is context, not a gate.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import teamlib  # noqa: E402

CONSTITUTION = Path(__file__).resolve().parent / "constitution.md"
JOURNAL_SCRIPT = Path(__file__).resolve().parent / "team-journal.py"


def dormant_state(team):
    """The whole footprint of a finished team: a count, and how to record intent.

    No constitution, no rules, no loop — the engineer is meant to behave like any
    other session until the user asks for an audit."""
    try:
        p = teamlib.pending(team, sync=True)
    except Exception:
        p = teamlib.pending(team)
    if not p["commits"]:
        return ("## Team (dormant)\nNo unaudited commits. The team loop is off: work normally, "
                "do not write locks or dispatch specialists. `/team:build <goal>` starts new work.")
    urgency = (" — **audit recommended**" if p["pressure"] >= 1.0 else "")
    return "\n".join([
        "## Team (dormant)",
        f"{p['units']} unit(s) / {p['commits']} commit(s) / {p['churn']} lines unaudited "
        f"in `{p['range']}`{urgency}. Run `/team:audit` to verify them.",
        "The team loop is off: work normally, do not write locks or dispatch specialists.",
        "After you commit, record why in one line (cheap, and the audit reads it):",
        f'`python3 "{JOURNAL_SCRIPT}" intent <sha> "<why this change>"`',
    ])


def live_state(team):
    lines = ["## Live team state (generated)", f"Team directory: {team}",
             f"Mode: {teamlib.mode(team)}"]
    locks = teamlib.held_locks(team)
    if locks:
        lines.append("Held locks (do NOT edit these files):")
        for l in locks:
            if l.error:
                lines.append(f"- {l.unit}: {l.error}")
            else:
                age = l.age_minutes()
                age_s = f", {int(age)}m" if age is not None else ""
                stale = " STALE — check the subagent panel, re-dispatch, or release" if l.stale() else ""
                lines.append(f"- {l.unit} [{l.stage}{age_s}]: {', '.join(l.files) or '<no files>'} — waiting on {', '.join(l.waiting)}{stale}")
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
    event = (
        (sys.argv[1] if len(sys.argv) > 1 else None)
        or payload.get("hook_event_name")
        or ("PostCompaction" if "summary" in payload else "SessionStart" if "source" in payload else "UserPromptSubmit")
    )
    if teamlib.mode(team) == "dormant":
        context = dormant_state(team)
    else:
        try:
            constitution = CONSTITUTION.read_text()
        except OSError:
            constitution = "(constitution.md missing from plugin; rules unavailable)"
        context = constitution.rstrip() + "\n\n" + live_state(team)
    print(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": context}}))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # never break the user's session over a context hook
        print(f"team-context: {exc}", file=sys.stderr)
    sys.exit(0)
