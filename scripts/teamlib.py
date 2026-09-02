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


# --- whole-team snapshot and next actions -------------------------------------

PAUSE_FILE = "paused"
FINAL_ROLES = ("qa", "spec-checker")
FRESH_SECONDS = 60


def paused(team):
    return (Path(team) / PAUSE_FILE).exists()


def fresh_unread_findings(team, seconds=FRESH_SECONDS):
    """Unread findings written within the last `seconds` — the signature of a
    specialist that has just finished (used to tell its Stop from the engineer's)."""
    import time
    now = time.time()
    return [p.name for p in (Path(team) / "findings").glob("*.md")
            if not finding_status(p) and now - p.stat().st_mtime < seconds]


def fmt_age(minutes):
    if minutes is None:
        return "unknown"
    return f"{int(minutes)}m" if minutes < 120 else f"{minutes / 60:.1f}h"


def snapshot(team, stale_minutes=STALE_MINUTES):
    """Everything the status report, the context hook and the Stop gate need."""
    team = Path(team)
    crit = criteria(team)
    plan = plan_rows(team)
    return {
        "team_dir": str(team),
        "spec_title": spec_title(team),
        "has_spec": crit is not None,
        "criteria": [{"id": i, "status": s, "text": t} for i, s, t in (crit or [])],
        "plan": plan,
        "locks": [{
            "unit": l.unit, "stage": l.stage, "files": l.files, "waiting": l.waiting,
            "held": l.held, "age_minutes": l.age_minutes(), "stale": l.stale(stale_minutes), "error": l.error,
        } for l in load_locks(team)],
        "findings": findings(team),
        "free_todo": [r["unit"] for r in free_todo_units(team)],
        "paused": paused(team),
        "stale_minutes": stale_minutes,
    }


def next_actions(d):
    """Ordered, human-readable actions for the engineer. Empty list == nothing open."""
    acts = []
    if not d["has_spec"]:
        return []
    unread = [f["file"] for f in d["findings"] if not f["status"]]
    held = [l for l in d["locks"] if l["held"]]
    stale = [l for l in held if l["stale"]]
    broken = [l for l in d["locks"] if l["error"]]
    plan = d["plan"] or []
    counts = {s: sum(1 for r in plan if r["status"] == s) for s in PLAN_STATUSES}
    crit = d["criteria"]

    if unread:
        acts.append(f"Process {len(unread)} unread finding(s) (Phase 5): " + ", ".join(unread))
    for l in broken:
        acts.append(f"Lock {l['unit']} is unreadable: fix or remove `.team/locks/{l['unit']}.json`.")
    for l in stale:
        acts.append(f"Lock {l['unit']} has waited {fmt_age(l['age_minutes'])} on {', '.join(l['waiting'])} "
                    f"(> {d['stale_minutes']}m): check the subagent panel; re-dispatch, or run `/team:release {l['unit']}`.")
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
                    f"(waiting on {', '.join(oldest['waiting'])}) with a blocking read.")
    open_units = counts["todo"] or counts["in-progress"] or counts["verifying"] or counts["needs-fix"]
    all_verified = bool(crit) and all(c["status"] == "verified" for c in crit)
    have_final = {f["role"] for f in d["findings"] if f["unit"] == "final"}
    if all_verified and not held and not open_units and not unread:
        missing = [r for r in FINAL_ROLES if r not in have_final]
        if missing:
            acts.append("All criteria verified, no open units or locks: run the Phase 6 final pass (" + ", ".join(missing) + ").")
    elif not acts and held:
        acts.append("Waiting on specialists: " + ", ".join(f"{l['unit']} ({', '.join(l['waiting'])})" for l in held))
    elif not acts and (open_units or not all_verified):
        acts.append("Work remains: " + (
            f"{counts['in-progress']} in-progress, {counts['verifying']} verifying, {counts['needs-fix']} needs-fix unit(s)"
            if open_units else "criteria still unverified — add units that serve them."))
    return acts


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
