#!/usr/bin/env python3
"""Prepare an audit: check the team is auditable, and propose audit units from
the commits made since the last checkpoint.

Usage:
  team-audit.py plan [--since <sha|ref>] [--json]
  team-audit.py open [--since <sha|ref>]     # plan, then switch the mode to audit

`plan` is read-only — run it first and show the user what would be audited.
`open` arms the loop (mode=audit, so the constitution and the Stop gate come
back); after that, only closing the audit (`team-state.py close`) turns them off.

Units are clusters of commits that share files, so each unit's file set is
disjoint from every other's and its change is exactly
`git diff <base>..<head> -- <files>`. The lock a unit needs is printed with it.

Exit codes: 0 ready, 1 nothing to do or not auditable (message on stderr).
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import teamlib  # noqa: E402


def build_plan(team, since):
    root = teamlib.project_root(team)
    p = teamlib.pending(team, sync=True, since=since)
    base = since or teamlib.checkpoint(team)
    head = teamlib.git(root, "rev-parse", "HEAD")
    units = []
    for i, c in enumerate(p["clusters"], 1):
        units.append({
            "unit": f"A-{i:02d}",
            "files": c["files"],
            "commits": c["commits"],
            "added": c["added"],
            "deleted": c["deleted"],
            "diff": f"git diff {base}..{head} -- " + " ".join(c["files"]),
            "lock": {
                "unit": f"A-{i:02d}",
                "created": datetime.now(timezone.utc).isoformat(),
                "base": base,
                "head": head,
                "files": c["files"],
                "verifiers": ["reviewer", "test-writer", "qa", "spec-checker"],
                "stage": "review",
            },
        })
    return {"range": p["range"], "base": base, "head": head, "mode": teamlib.mode(team),
            "commits": p["commits"], "churn": p["churn"], "pressure": p["pressure"], "units": units}


def render(d):
    out = [f"# Audit plan — {d['range']}",
           f"{len(d['units'])} unit(s), {d['commits']} commit(s), {d['churn']} lines, pressure {d['pressure']:.2f}",
           ""]
    for u in d["units"]:
        out.append(f"## {u['unit']}  +{u['added']}/-{u['deleted']}")
        out.append(f"files: {', '.join(u['files'])}")
        for c in u["commits"]:
            intent = f"\n      intent: {c['intent']}" if c.get("intent") else ""
            out.append(f"  {c['sha'][:8]}  {c['msg']}{intent}")
        out.append(f"diff: {u['diff']}")
        out.append("")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "open"):
        s = sub.add_parser(name)
        s.add_argument("--since", help="audit from this commit instead of the checkpoint")
        s.add_argument("--json", action="store_true")
    args = ap.parse_args()

    team = teamlib.find_team_dir(Path.cwd())
    if team is None:
        print("no .team/ found — /team:audit verifies work a build produced. Run /team:build <goal> first.",
              file=sys.stderr)
        return 1
    mode = teamlib.mode(team)
    if mode != "dormant":
        print(f"team mode is '{mode}', not 'dormant' — a build or audit is still open. "
              f"Run /team:status and finish it first.", file=sys.stderr)
        return 1

    d = build_plan(team, args.since)
    if not d["units"]:
        print(f"nothing to audit in {d['range']} — no commits since the last checkpoint.", file=sys.stderr)
        return 1

    if args.cmd == "open":
        teamlib.write_state(team, mode="audit", since=datetime.now(timezone.utc).isoformat())
        d["mode"] = "audit"

    print(json.dumps(d, indent=2) if args.json else render(d))
    return 0


if __name__ == "__main__":
    sys.exit(main())
