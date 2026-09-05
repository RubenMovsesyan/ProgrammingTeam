#!/usr/bin/env python3
"""Report the Programming Team's current state from .team/ and say what to do next.

Usage: team-status.py [--json] [--stale-minutes N]
Run from the project or any subdirectory. Always exits 0.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import teamlib  # noqa: E402


def git(*args, cwd):
    try:
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        return ""


def table(headers, rows):
    if not rows:
        return ["  (none)"]
    widths = [max(len(str(c)) for c in col) for col in zip(headers, *rows)]
    fmt = "  " + "  ".join(f"{{:<{w}}}" for w in widths)
    return [fmt.format(*headers), fmt.format(*("-" * w for w in widths))] + [fmt.format(*(str(c) for c in r)) for r in rows]


def render(d, root):
    out = ["# Team status",
           f"team: {d['team_dir']}  mode: {d['mode'].upper()}" + ("  [PAUSED]" if d["paused"] else ""),
           f"git: {git('rev-parse', '--abbrev-ref', 'HEAD', cwd=root) or '?'} @ {git('rev-parse', '--short', 'HEAD', cwd=root) or '?'}",
           f"spec: {d['spec_title'] or '(no spec.md)'}", ""]
    out.append("## Criteria")
    out += table(["id", "status", "text"], [(c["id"], c["status"], c["text"]) for c in d["criteria"]])
    if d["criteria"]:
        cc = {s: sum(1 for c in d["criteria"] if c["status"] == s) for s in teamlib.CRITERIA_STATUSES}
        out.append("  " + ", ".join(f"{n} {s}" for s, n in cc.items()))
    out += ["", "## Units"]
    if d["plan"] is None:
        out.append("  (no plan.md)")
    else:
        out += table(["unit", "title", "serves", "files", "status"],
                     [(r["unit"], r["title"], r["serves"], ", ".join(r["files"]), r["status"]) for r in d["plan"]])
        if d["plan"]:
            pc = {s: sum(1 for r in d["plan"] if r["status"] == s) for s in teamlib.PLAN_STATUSES}
            out.append("  " + ", ".join(f"{n} {s}" for s, n in pc.items()))
    out += ["", "## Locks"]
    rows = []
    for l in d["locks"]:
        if l["error"]:
            rows.append((l["unit"], "?", "", "", l["error"]))
        elif l["held"]:
            rows.append((l["unit"], l["stage"], ", ".join(l["files"]), ", ".join(l["waiting"]),
                         f"HELD {teamlib.fmt_age(l['age_minutes'])}" + (" STALE" if l["stale"] else "")))
        else:
            rows.append((l["unit"], l["stage"], ", ".join(l["files"]), "", "released"))
    out += table(["unit", "stage", "files", "waiting on", "state"], rows)
    out += ["", "## Findings"]
    fs = sorted(d["findings"], key=lambda f: (bool(f["status"]), f["file"]))
    out += table(["file", "role", "unit", "verdict", "status"],
                 [(f["file"], f["role"], f["unit"], f["verdict"], f["status"] or "UNREAD") for f in fs])
    p = d.get("pending") or {}
    if d["mode"] == "dormant" or p.get("commits"):
        out += ["", "## Pending audit"]
        out += table(["range", "units", "commits", "files", "lines", "pressure"],
                     [(p.get("range", "?"), p.get("units", 0), p.get("commits", 0),
                       p.get("files", 0), p.get("churn", 0), f"{p.get('pressure', 0):.2f}")])
        budgets = p.get("budgets") or {}
        if budgets:
            out.append(f"  budgets: {int(budgets['churn'])} lines / {int(budgets['units'])} units"
                       f" — pressure >= 1.00 recommends an audit")
    out += ["", "## Next actions"]
    acts = teamlib.next_actions(d)
    if d["paused"]:
        out.append("Team is PAUSED (`.team/paused` exists): the Stop gate is off. Run `/team:resume` to continue.")
    if not d["has_spec"]:
        acts = ["No spec yet: start with `/team:build <goal>`."]
    elif d["mode"] == "dormant" and not acts:
        acts = ["Dormant, nothing unaudited. Work normally; `/team:build <goal>` starts new work."]
    elif not acts:
        acts = ["Nothing open: the spec holds and the final pass is done."]
    out += [f"{i}. {a}" for i, a in enumerate(acts, 1)]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--stale-minutes", type=int, default=teamlib.STALE_MINUTES)
    args = ap.parse_args()
    team = teamlib.find_team_dir(Path.cwd())
    if team is None:
        print(f"no .team/ found at or above {Path.cwd()}")
        return
    d = teamlib.snapshot(team, args.stale_minutes, sync=True)
    if args.json:
        d["next_actions"] = teamlib.next_actions(d)
        print(json.dumps(d, indent=2))
    else:
        print(render(d, team.parent))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"team-status: error: {exc}", file=sys.stderr)
    sys.exit(0)
