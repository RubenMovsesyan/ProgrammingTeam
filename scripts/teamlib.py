"""Shared helpers for reading .team/ state. Used by every hook script so that the
context injected into the agent and the gates enforced on it agree by construction.

Formats parsed here are defined by skills/build/SKILL.md (templates section).
"""
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

PLAN_STATUSES = ("todo", "in-progress", "verifying", "verified", "needs-fix")
CRITERIA_STATUSES = ("unverified", "verified", "failed")
LOCK_STAGES = ("review", "verify")


def read_payload():
    """Hook stdin as a dict; {} on anything unparseable."""
    try:
        return json.load(sys.stdin)
    except Exception:
        return {}


def find_team_dir(start):
    """Nearest .team/ at or above `start`, or None."""
    start = Path(start).resolve()
    for d in [start, *start.parents]:
        if (d / ".team").is_dir():
            return d / ".team"
    return None


def finding_status(path):
    """Value after the last 'status:' line; '' if empty or absent."""
    status = ""
    for line in Path(path).read_text(errors="replace").splitlines():
        m = re.match(r"^status:\s*(.*)$", line)
        if m:
            status = m.group(1).strip()
    return status


@dataclass
class Lock:
    unit: str
    files: list = field(default_factory=list)
    verifiers: list = field(default_factory=list)
    stage: str = "review"
    waiting: list = field(default_factory=list)
    error: str = ""

    @property
    def held(self):
        return bool(self.waiting) or bool(self.error)


def load_locks(team):
    """All locks under .team/locks/, held or not. Unreadable files become locks
    with `error` set and no files, so callers can report them without guessing."""
    team = Path(team)
    findings = team / "findings"
    locks = []
    for lock_path in sorted((team / "locks").glob("*.json")):
        try:
            raw = json.loads(lock_path.read_text())
            unit = raw.get("unit", lock_path.stem)
            verifiers = list(raw.get("verifiers", []))
            locks.append(Lock(
                unit=unit,
                files=[str(f) for f in raw.get("files", [])],
                verifiers=verifiers,
                stage=raw.get("stage", "review"),
                waiting=[r for r in verifiers if not (findings / f"{r}-{unit}.md").exists()],
            ))
        except Exception as exc:
            locks.append(Lock(unit=lock_path.stem, error=f"unreadable lock file: {exc}"))
    return locks


def held_locks(team):
    return [l for l in load_locks(team) if l.held]


def unread_findings(team):
    return sorted(p.name for p in (Path(team) / "findings").glob("*.md") if not finding_status(p))


def plan_counts(team):
    plan = Path(team) / "plan.md"
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
    spec = Path(team) / "spec.md"
    if not spec.exists():
        return None
    text = spec.read_text(errors="replace")
    return {s: len(re.findall(rf"^- AC-\d+:.*status:\s*{s}\s*$", text, re.M)) for s in CRITERIA_STATUSES}


def project_relative(path, team, base=None):
    """`path` (absolute, or relative to `base` / the process cwd) as a POSIX path
    relative to the project root (parent of .team/). None if outside the project."""
    root = Path(team).resolve().parent
    p = Path(path)
    if not p.is_absolute():
        p = Path(base or Path.cwd()) / p
    try:
        return p.resolve().relative_to(root).as_posix()
    except ValueError:
        return None
