#!/usr/bin/env python3
"""Track the commits made since the last audit checkpoint, so work done outside
the team loop is still visible to /team:audit.

Usage:
  team-journal.py sync                  # rebuild journal.jsonl from git
  team-journal.py intent <sha> "<why>"  # attach the reason a commit was made
  team-journal.py pending [--json]      # counts, churn and audit pressure
  team-journal.py clusters [--json]     # proposed audit units (A-01, A-02, ...)

`sync` reconciles the whole `<checkpoint>..HEAD` range instead of trusting any
single commit command, so hand-made commits, `--amend` and rebases all land
correctly; entries whose sha left the range are dropped.

Runs as a PostToolUse hook, so it never fails loudly: no .team/, no git, bad
arguments — say so on stderr and exit 0.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import teamlib  # noqa: E402


def render_pending(p):
    if not p["commits"]:
        return f"nothing to audit ({p['range']})"
    return (f"{p['units']} unit(s), {p['commits']} commit(s), {p['files']} file(s), "
            f"{p['churn']} lines changed in {p['range']}\n"
            f"pressure {p['pressure']:.2f} "
            f"(budgets: {int(p['budgets']['churn'])} lines / {int(p['budgets']['units'])} units) — "
            + ("audit recommended" if p["pressure"] >= 1.0 else "below the audit threshold"))


def render_clusters(clusters):
    if not clusters:
        return "(no unaudited commits)"
    out = []
    for i, c in enumerate(clusters, 1):
        out.append(f"A-{i:02d}  +{c['added']}/-{c['deleted']}  files: {', '.join(c['files'])}")
        for commit in c["commits"]:
            intent = f"  [intent: {commit['intent']}]" if commit.get("intent") else ""
            out.append(f"      {commit['sha'][:8]}  {commit['msg']}{intent}")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sync")
    s.add_argument("--since", help="override the checkpoint")
    sub.add_parser("hook")  # PostToolUse: read cwd from the payload, sync, say nothing
    i = sub.add_parser("intent")
    i.add_argument("sha")
    i.add_argument("text")
    for name in ("pending", "clusters"):
        p = sub.add_parser(name)
        p.add_argument("--json", action="store_true")
        p.add_argument("--since", help="override the checkpoint")
    args = ap.parse_args()

    if args.cmd == "hook":
        payload = teamlib.read_payload()
        team = teamlib.find_team_dir(payload.get("cwd") or Path.cwd())
        command = str((payload.get("tool_input") or {}).get("command") or "")
        # Cheap filter: only a command that could have moved HEAD is worth a git call.
        if team is not None and any(w in command for w in ("commit", "merge", "rebase", "cherry-pick", "revert", "reset")):
            teamlib.sync_journal(team)
        return

    team = teamlib.find_team_dir(Path.cwd())
    if team is None:
        print("no .team/ found", file=sys.stderr)
        return

    if args.cmd == "sync":
        entries = teamlib.sync_journal(team, getattr(args, "since", None))
        print(f"journalled {len(entries)} commit(s) in {teamlib.audit_range(team, args.since)}")
        return

    if args.cmd == "intent":
        sha = teamlib.set_intent(team, args.sha, args.text)
        if sha is None:
            teamlib.sync_journal(team)  # the commit may be newer than the journal
            sha = teamlib.set_intent(team, args.sha, args.text)
        print(f"intent recorded for {sha[:8]}" if sha
              else f"no journalled commit matches {args.sha} — nothing recorded")
        return

    p = teamlib.pending(team, sync=True, since=args.since)
    if args.json:
        print(json.dumps(p, indent=2))
    elif args.cmd == "pending":
        print(render_pending(p))
    else:
        print(render_clusters(p["clusters"]))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # a bookkeeping hook must never break a session
        print(f"team-journal: {exc}", file=sys.stderr)
    sys.exit(0)
