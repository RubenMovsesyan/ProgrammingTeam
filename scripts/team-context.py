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
import re
import sys
from pathlib import Path

CONSTITUTION = Path(__file__).resolve().parent / "constitution.md"
PLAN_STATUSES = ("todo", "in-progress", "verifying", "verified", "needs-fix")


def read_payload():
    try:
        return json.load(sys.stdin)
    except Exception:
        return {}


def find_team_dir(start):
    for d in [start, *start.parents]:
        if (d / ".team").is_dir():
            return d / ".team"
    return None


def finding_status(path):
    """Return the value after the last 'status:' line, '' if empty or absent."""
    status = ""
    for line in path.read_text(errors="replace").splitlines():
        m = re.match(r"^status:\s*(.*)$", line)
        if m:
            status = m.group(1).strip()
    return status


def held_locks(team):
    findings = team / "findings"
    out = []
    for lock_path in sorted((team / "locks").glob("*.json")):
        try:
            lock = json.loads(lock_path.read_text())
        except Exception:
            out.append((lock_path.stem, ["<unreadable lock file>"], []))
            continue
        unit = lock.get("unit", lock_path.stem)
        waiting = [r for r in lock.get("verifiers", []) if not (findings / f"{r}-{unit}.md").exists()]
        if waiting:
            out.append((unit, lock.get("files", []), waiting))
    return out


def unread_findings(team):
    return sorted(p.name for p in (team / "findings").glob("*.md") if not finding_status(p))


def plan_counts(team):
    plan = team / "plan.md"
    if not plan.exists():
        return None
    counts = {s: 0 for s in PLAN_STATUSES}
    for line in plan.read_text(errors="replace").splitlines():
        if not line.startswith("| U-"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if cells and cells[-1] in counts:
            counts[cells[-1]] += 1
    return counts


def criteria_counts(team):
    spec = team / "spec.md"
    if not spec.exists():
        return None
    text = spec.read_text(errors="replace")
    return {
        s: len(re.findall(rf"^- AC-\d+:.*status:\s*{s}\s*$", text, re.M))
        for s in ("unverified", "verified", "failed")
    }


def live_state(team):
    lines = ["## Live team state (generated)", f"Team directory: {team}"]
    locks = held_locks(team)
    if locks:
        lines.append("Held locks (do NOT edit these files):")
        for unit, files, waiting in locks:
            lines.append(f"- {unit}: {', '.join(files) or '<no files>'} — waiting on {', '.join(waiting)}")
    else:
        lines.append("Held locks: none")
    unread = unread_findings(team)
    lines.append("Unread findings (no status line): " + (", ".join(unread) if unread else "none"))
    plan = plan_counts(team)
    if plan:
        lines.append("Plan: " + ", ".join(f"{n} {s}" for s, n in plan.items()))
    crit = criteria_counts(team)
    if crit:
        lines.append("Criteria: " + ", ".join(f"{n} {s}" for s, n in crit.items()))
    return "\n".join(lines)


def main():
    payload = read_payload()
    cwd = Path(payload.get("cwd") or os.getcwd()).resolve()
    team = find_team_dir(cwd)
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
