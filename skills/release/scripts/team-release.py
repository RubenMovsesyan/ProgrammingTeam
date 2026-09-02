#!/usr/bin/env python3
"""Release a stale lock by writing a synthetic `blocked` finding for each verifier
that never reported. The lock then releases through the normal path (a finding
exists for every verifier) and the audit trail shows exactly what happened.

Usage: team-release.py <unit> [--role ROLE ...] [--force] [--reason TEXT]

Refuses unless the lock is stale (older than the threshold) or --force is given.
Never deletes or edits the lock file. Always exits 0; prints what it did.
"""
import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import teamlib  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("unit")
    ap.add_argument("--role", action="append", help="release only these verifiers (default: all still waiting)")
    ap.add_argument("--force", action="store_true", help="release even if the lock is not stale")
    ap.add_argument("--reason", default="", help="why the engineer is releasing (recorded in the finding)")
    ap.add_argument("--stale-minutes", type=int, default=teamlib.STALE_MINUTES)
    args = ap.parse_args()

    team = teamlib.find_team_dir(Path.cwd())
    if team is None:
        print(f"no .team/ found at or above {Path.cwd()}")
        return
    lock = next((l for l in teamlib.load_locks(team) if l.unit == args.unit), None)
    if lock is None:
        print(f"no lock for {args.unit} in {team / 'locks'}")
        return
    if lock.error:
        print(f"lock {args.unit} is unreadable ({lock.error}); fix or remove the file by hand")
        return
    if not lock.held:
        print(f"lock {args.unit} is already released")
        return
    age = lock.age_minutes()
    if not lock.stale(args.stale_minutes) and not args.force:
        print(f"lock {args.unit} is held but not stale (age {teamlib.fmt_age(age)}, threshold {args.stale_minutes}m); "
              f"waiting on {', '.join(lock.waiting)}. Check the subagent panel first, or pass --force.")
        return

    roles = [r for r in (args.role or lock.waiting) if r in lock.waiting]
    if not roles:
        print(f"none of {args.role} are waiting on {args.unit} (waiting: {', '.join(lock.waiting)})")
        return
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for role in roles:
        path = team / "findings" / f"{role}-{args.unit}.md"
        path.write_text(
            f"# Finding: {role} on {args.unit}\n"
            f"verdict: blocked\n"
            f"released: {now} by engineer via /team:release (lock age {teamlib.fmt_age(age)}"
            f"{', forced' if args.force else ', stale'})\n\n"
            f"## Summary\n"
            f"No finding was produced by {role}; the lock was released manually. "
            f"{args.reason or 'Re-dispatch this role for the unit, or record why its verification is not needed.'}\n\n"
            f"## Issues\n1. {role} did not report on {args.unit} — severity: high\n"
            f"   The unit is unverified by this role. Re-dispatch, or defer with a reason.\n\n"
            f"status:\n"
        )
        print(f"wrote {path.relative_to(team.parent)}")
    still = [r for r in lock.waiting if r not in roles]
    print(f"lock {args.unit}: " + ("released" if not still else f"still waiting on {', '.join(still)}"))
    print("Next: process the new finding(s) — re-dispatch the role(s) or mark them deferred with a reason.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"team-release: error: {exc}", file=sys.stderr)
    sys.exit(0)
