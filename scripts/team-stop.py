#!/usr/bin/env python3
"""Stop gate: refuse to let the engineer end its turn while team work is open.

Blocks at most once per turn (passes when `stop_hook_active` is set), so it can
never loop. Passes silently when:

  - there is no .team/ at or above the working directory;
  - the team is dormant (a build or audit finished): the loop is over, and an
    ordinary prompt must not be dragged back into it. Only /team:build or
    /team:audit arms this gate again;
  - .team/paused exists (the user wants to talk; see /team:pause);
  - stop_hook_active is true (we already blocked once this turn);
  - an unread finding was written in the last minute. In Devin the Stop event
    also fires when a *subagent* finishes, with no caller identity; a fresh
    unread finding is the signature of a specialist that has just done its job,
    and blocking it would only cost an extra turn. The engineer is woken by the
    completion notification anyway;
  - nothing is open: every criterion verified, no held locks, no open units,
    no unread findings, final-pass findings present.

Otherwise it blocks with the same "next actions" the status report shows, plus
a line telling a specialist that has *not* written its finding to do so.

Output: {"decision":"block","reason":...} on stdout — the shape both Devin and
Claude Code read for Stop hooks. Fails open on its own errors.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import teamlib  # noqa: E402


def main():
    payload = teamlib.read_payload()
    team = teamlib.find_team_dir(payload.get("cwd") or os.getcwd())
    if team is None or teamlib.paused(team) or payload.get("stop_hook_active"):
        return
    if teamlib.mode(team) == "dormant":
        return
    if teamlib.fresh_unread_findings(team):
        return
    snap = teamlib.snapshot(team)
    acts = teamlib.next_actions(snap)
    if not acts:
        return
    reason = "\n".join([
        "Team work is still open (Stop gate). Continue with the next action:",
        *[f"{i}. {a}" for i, a in enumerate(acts, 1)],
        "",
        "If you are a specialist subagent that has finished: write your finding file to the path in your task, then stop.",
        "If the user wants to pause the team, run /team:pause (creates .team/paused); this gate then stays off until /team:resume.",
    ])
    print(json.dumps({"decision": "block", "reason": reason}))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # fail open
        print(f"team-stop: gate error, allowing stop: {exc}", file=sys.stderr)
    sys.exit(0)
