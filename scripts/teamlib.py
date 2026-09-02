"""Shared helpers for reading .team/ state. Used by every hook and skill script so
that the context injected into the agent, the gates enforced on it, and the
status report all agree by construction.

Formats parsed here are defined by skills/build/SKILL.md (templates section).
"""
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

PLAN_STATUSES = ("todo", "in-progress", "verifying", "verified", "needs-fix")
CRITERIA_STATUSES = ("unverified", "verified", "failed")
LOCK_STAGES = ("review", "verify")
STALE_MINUTES = 30


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


def _read(path):
    return Path(path).read_text(errors="replace")


# --- findings -----------------------------------------------------------------

def finding_status(path):
    """Value after the last 'status:' line; '' if empty or absent."""
    status = ""
    for line in _read(path).splitlines():
        m = re.match(r"^status:\s*(.*)$", line)
        if m:
            status = m.group(1).strip()
    return status


def finding_header(path):
    """{'role','unit','verdict','status'} from a finding file; '?' where absent."""
    text = _read(path)
    m = re.search(r"^# Finding:\s*(\S+)\s+on\s+(.+?)\s*$", text, re.M)
    v = re.search(r"^verdict:\s*(\S+)", text, re.M)
    return {
        "file": Path(path).name,
        "role": m.group(1) if m else "?",
        "unit": m.group(2) if m else "?",
        "verdict": v.group(1) if v else "?",
        "status": finding_status(path),
    }


def findings(team):
    return [finding_header(p) for p in sorted((Path(team) / "findings").glob("*.md"))]


def unread_findings(team):
    return sorted(p.name for p in (Path(team) / "findings").glob("*.md") if not finding_status(p))


# --- locks --------------------------------------------------------------------

@dataclass
class Lock:
    unit: str
    files: list = field(default_factory=list)
    verifiers: list = field(default_factory=list)
    stage: str = "review"
    created: str = ""
    waiting: list = field(default_factory=list)
    error: str = ""

    @property
    def held(self):
        return bool(self.waiting) or bool(self.error)

    def age_minutes(self, now=None):
        """Minutes since `created`; None if missing or unparseable."""
        if not self.created:
            return None
        try:
            ts = datetime.fromisoformat(self.created.replace("Z", "+00:00"))
        except ValueError:
            return None
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        now = now or datetime.now(timezone.utc)
        return max(0.0, (now - ts).total_seconds() / 60)

    def stale(self, threshold=STALE_MINUTES):
        age = self.age_minutes()
        return self.held and age is not None and age > threshold


def load_locks(team):
    """All locks under .team/locks/, held or not. Unreadable files become locks
    with `error` set and no files, so callers can report them without guessing."""
    team = Path(team)
    fdir = team / "findings"
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
                created=str(raw.get("created", "")),
                waiting=[r for r in verifiers if not (fdir / f"{r}-{unit}.md").exists()],
            ))
        except Exception as exc:
            locks.append(Lock(unit=lock_path.stem, error=f"unreadable lock file: {exc}"))
    return locks


def held_locks(team):
    return [l for l in load_locks(team) if l.held]


def locked_files(team):
    return {f for l in held_locks(team) for f in l.files}


# --- plan ---------------------------------------------------------------------

def plan_rows(team):
    """Rows of the plan.md table as dicts: unit, title, serves, files (list), status."""
    plan = Path(team) / "plan.md"
    if not plan.exists():
        return None
    rows = []
    for line in _read(plan).splitlines():
        if not line.startswith("| U-"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        rows.append({
            "unit": cells[0],
            "title": cells[1] if len(cells) > 1 else "",
            "serves": cells[2] if len(cells) > 2 else "",
            "files": [f for f in re.split(r"[,\s]+", cells[3]) if f] if len(cells) > 3 else [],
            "status": cells[-1],
        })
    return rows


def plan_counts(team):
    rows = plan_rows(team)
    if rows is None:
        return None
    counts = {s: 0 for s in PLAN_STATUSES}
    for r in rows:
        if r["status"] in counts:
            counts[r["status"]] += 1
    return counts


def free_todo_units(team):
    """Todo units whose expected files are disjoint from every held lock."""
    rows = plan_rows(team) or []
    busy = locked_files(team)
    return [r for r in rows if r["status"] == "todo" and not (set(r["files"]) & busy)]


# --- spec ---------------------------------------------------------------------

def spec_title(team):
    spec = Path(team) / "spec.md"
    if not spec.exists():
        return None
    m = re.search(r"^# Spec:\s*(.+)$", _read(spec), re.M)
    return m.group(1).strip() if m else "(untitled)"


def criteria(team):
    """[(id, status, text)] from spec.md; None if no spec."""
    spec = Path(team) / "spec.md"
    if not spec.exists():
        return None
    out = []
    for m in re.finditer(r"^- (AC-\d+):\s*(.*?)\s*[—–-]+\s*status:\s*(\S+)\s*$", _read(spec), re.M):
        out.append((m.group(1), m.group(3), m.group(2)))
    return out


def criteria_counts(team):
    crit = criteria(team)
    if crit is None:
        return None
    counts = {s: 0 for s in CRITERIA_STATUSES}
    for _, status, _ in crit:
        if status in counts:
            counts[status] += 1
    return counts


# --- paths --------------------------------------------------------------------

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
