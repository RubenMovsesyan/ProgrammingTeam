#!/usr/bin/env python3
"""PreToolUse gate: refuse edits to files whose mutex is held by specialists.

A lock (.team/locks/<unit>.json) is held while any listed verifier lacks a
finding file. Its `stage` says who owns the files:

  review  - the reviewer alone may edit. Claude Code identifies the caller
            (agent_type), so anyone else is denied. Devin gives hooks no caller
            identity, so edits are allowed and the engineer's restraint is
            advisory for this window only.
  verify  - read-only verifiers hold it. Nobody may edit.

Paths under .team/ are never gated, and nothing is gated while the team is
dormant — no specialist is running then, so a lock left behind by an abandoned
build cannot wedge ordinary work. On its own errors the gate fails OPEN with a
note on stderr: a typo in a lock file must not wedge the session; the rule is
also stated in the constitution, which is the primary control.

Output: on deny, a Claude Code permissionDecision JSON on stdout AND exit code 2
with the reason on stderr (Devin's protocol). Each runtime reads its own channel.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import teamlib  # noqa: E402

PATH_KEYS = ("file_path", "notebook_path", "path")


def target_path(tool_input):
    for k in PATH_KEYS:
        if tool_input.get(k):
            return tool_input[k]
    return None


def caller_is_reviewer(payload):
    """True only when the runtime tells us the caller is the reviewer."""
    agent_type = str(payload.get("agent_type") or "")
    return agent_type.split(":")[-1] == "reviewer"


def decide(payload, team):
    """Return a deny reason string, or None to allow."""
    if teamlib.mode(team) == "dormant":
        return None  # no verification is in flight; a leftover lock must not wedge the session
    rel = teamlib.project_relative(target_path(payload.get("tool_input") or {}) or "", team, payload.get("cwd"))
    if rel is None or rel == ".team" or rel.startswith(".team/"):
        return None
    for lock in teamlib.held_locks(team):
        if lock.error or rel not in lock.files:
            continue
        if lock.stage == "review":
            if "agent_type" in payload and not caller_is_reviewer(payload):
                return (f"{rel} is locked by {lock.unit} (stage review): only the reviewer may edit it "
                        f"right now. Wait for the reviewer's finding, or work on a unit whose files are free.")
            return None
        return (f"{rel} is locked by {lock.unit} (stage {lock.stage}), waiting on {', '.join(lock.waiting)}. "
                f"Do not edit it. Create a fix unit ({lock.unit}-fixN) or pick a unit whose files are free.")
    return None


def main():
    payload = teamlib.read_payload()
    team = teamlib.find_team_dir(payload.get("cwd") or os.getcwd())
    if team is None:
        return 0
    reason = decide(payload, team)
    if reason is None:
        return 0
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }}))
    print(f"team-mutex: {reason}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # fail open, loudly
        print(f"team-mutex: gate error, allowing edit: {exc}", file=sys.stderr)
        sys.exit(0)
