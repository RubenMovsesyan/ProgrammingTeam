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


def fmt_age(minutes):
    if minutes is None:
        return "unknown"
    return f"{int(minutes)}m" if minutes < 120 else f"{minutes / 60:.1f}h"


def collect(team, stale_minutes):
    root = team.parent
    locks = teamlib.load_locks(team)
    plan = teamlib.plan_rows(team)
    crit = teamlib.criteria(team)
    return {
        "team_dir": str(team),
        "branch": git("rev-parse", "--abbrev-ref", "HEAD", cwd=root),
        "head": git("rev-parse", "--short", "HEAD", cwd=root),
        "spec_title": teamlib.spec_title(team),
        "criteria": [{"id": i, "status": s, "text": t} for i, s, t in (crit or [])],
        "has_spec": crit is not None,
        "plan": plan,
        "locks": [{
            "unit": l.unit, "stage": l.stage, "files": l.files, "waiting": l.waiting,
            "held": l.held, "age_minutes": l.age_minutes(), "stale": l.stale(stale_minutes), "error": l.error,
        } for l in locks],
        "findings": teamlib.findings(team),
        "free_todo": [r["unit"] for r in teamlib.free_todo_units(team)],
    }


def next_actions(d, stale_minutes):
    acts = []
    unread = [f["file"] for f in d["findings"] if not f["status"]]
    held = [l for l in d["locks"] if l["held"]]
    stale = [l for l in held if l["stale"]]
    broken = [l for l in d["locks"] if l["error"]]
    plan = d["plan"] or []
    counts = {s: sum(1 for r in plan if r["status"] == s) for s in teamlib.PLAN_STATUSES}
    crit = d["criteria"]

    if not d["has_spec"]:
        return ["No spec yet: start with `/team:build <goal>`."]
    if unread:
        acts.append(f"Process {len(unread)} unread finding(s) (Phase 5): " + ", ".join(unread))
    for l in broken:
        acts.append(f"Lock {l['unit']} is unreadable: fix or remove `.team/locks/{l['unit']}.json`.")
    for l in stale:
        acts.append(f"Lock {l['unit']} has waited {fmt_age(l['age_minutes'])} on {', '.join(l['waiting'])} "
                    f"(> {stale_minutes}m): check the subagent panel, re-dispatch, or release manually.")
    failed = [c["id"] for c in crit if c["status"] == "failed"]
    if failed:
        acts.append("Failed criteria " + ", ".join(failed) + ": make sure fix units exist and are prioritised.")
    if d["plan"] is None:
        acts.append("Spec exists but no plan.md: write the plan (Phase 2).")
    elif d["free_todo"]:
        acts.append("Pick a unit whose files are free (Phase 4): " + ", ".join(d["free_todo"]))
    elif counts["todo"] and held:
        oldest = max(held, key=lambda l: l["age_minutes"] or 0)
        acts.append(f"Nothing pickable — every todo unit touches locked files. Wait on lock {oldest['unit']} "
                    f"(waiting on {', '.join(oldest['waiting'])}).")
    all_verified = bool(crit) and all(c["status"] == "verified" for c in crit)
    idle = not held and not (counts["todo"] or counts["in-progress"] or counts["verifying"] or counts["needs-fix"])
    if all_verified and idle and not unread:
        acts.append("All criteria verified, no open units or locks: run the Phase 6 final pass.")
    elif not acts and not held:
        acts.append("Nothing pending. Check plan.md for units to add, or run the Phase 6 final pass if the spec holds.")
    elif not acts:
        acts.append("Waiting on specialists: " + ", ".join(f"{l['unit']} ({', '.join(l['waiting'])})" for l in held))
    return acts


def render(d, stale_minutes):
    out = ["# Team status", f"team: {d['team_dir']}",
           f"git: {d['branch'] or '?'} @ {d['head'] or '?'}",
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
                         f"HELD {fmt_age(l['age_minutes'])}" + (" STALE" if l["stale"] else "")))
        else:
            rows.append((l["unit"], l["stage"], ", ".join(l["files"]), "", "released"))
    out += table(["unit", "stage", "files", "waiting on", "state"], rows)
    out += ["", "## Findings"]
    fs = sorted(d["findings"], key=lambda f: (bool(f["status"]), f["file"]))
    out += table(["file", "role", "unit", "verdict", "status"],
                 [(f["file"], f["role"], f["unit"], f["verdict"], f["status"] or "UNREAD") for f in fs])
    out += ["", "## Next actions"]
    out += [f"{i}. {a}" for i, a in enumerate(next_actions(d, stale_minutes), 1)]
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
    d = collect(team, args.stale_minutes)
    if args.json:
        d["next_actions"] = next_actions(d, args.stale_minutes)
        print(json.dumps(d, indent=2))
    else:
        print(render(d, args.stale_minutes))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"team-status: error: {exc}", file=sys.stderr)
    sys.exit(0)
