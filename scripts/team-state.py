#!/usr/bin/env python3
"""Write .team/state.json — the team's mode and audit checkpoint.

Usage:
  team-state.py show
  team-state.py init [--baseline <sha>]        # mode=build, baseline=HEAD
  team-state.py mode <build|audit|dormant>
  team-state.py checkpoint [<sha>]             # default HEAD
  team-state.py close                          # mode=dormant + checkpoint=HEAD

`close` is how a build (Phase 6) or an audit (A4) hands the project back to
ordinary work: the loop stops, the constitution stops being injected, and the
Stop gate goes quiet until the next /team:build or /team:audit.

Exits 1 with a message when there is no .team/ or the arguments are wrong.
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import teamlib  # noqa: E402


def resolve(root, ref):
    sha = teamlib.git(root, "rev-parse", ref)
    return sha or None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("show")
    init = sub.add_parser("init")
    init.add_argument("--baseline")
    m = sub.add_parser("mode")
    m.add_argument("mode", choices=teamlib.MODES)
    cp = sub.add_parser("checkpoint")
    cp.add_argument("sha", nargs="?", default="HEAD")
    sub.add_parser("close")
    args = ap.parse_args()

    team = teamlib.find_team_dir(Path.cwd())
    if team is None:
        print("no .team/ found — run /team:build first", file=sys.stderr)
        return 1
    root = teamlib.project_root(team)

    if args.cmd == "show":
        print(json.dumps(teamlib.read_state(team), indent=2))
        return 0

    if args.cmd == "init":
        baseline = resolve(root, args.baseline or "HEAD") or ""
        state = teamlib.write_state(team, mode="build", baseline=baseline,
                                    since=datetime.now(timezone.utc).isoformat())
        if not state.get("checkpoint"):
            state = teamlib.write_state(team, checkpoint=baseline)
    elif args.cmd == "mode":
        state = teamlib.write_state(team, mode=args.mode,
                                    since=datetime.now(timezone.utc).isoformat())
    elif args.cmd == "checkpoint":
        sha = resolve(root, args.sha)
        if sha is None:
            print(f"cannot resolve {args.sha}", file=sys.stderr)
            return 1
        state = teamlib.write_state(team, checkpoint=sha)
    else:  # close
        sha = resolve(root, "HEAD") or ""
        state = teamlib.write_state(team, mode="dormant", checkpoint=sha,
                                    since=datetime.now(timezone.utc).isoformat())
        teamlib.sync_journal(team)  # the audited range is behind us; the journal empties

    print(f"mode: {state['mode']}  checkpoint: {(state.get('checkpoint') or '(none)')[:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
