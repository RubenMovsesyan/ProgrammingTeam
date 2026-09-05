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

MODES = ("build", "audit", "dormant")
STATE_FILE = "state.json"
JOURNAL_FILE = "journal.jsonl"
DEFAULT_BUDGETS = {"churn": 2000, "units": 15}


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
    """Rows of the plan.md table as dicts: unit, title, serves, files (list), status.
    Build units are `U-xx`, audit units `A-xx`; both live in the same table."""
    plan = Path(team) / "plan.md"
    if not plan.exists():
        return None
    rows = []
    for line in _read(plan).splitlines():
        if not line.startswith(("| U-", "| A-")):
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


# --- mode / state -------------------------------------------------------------

def project_root(team):
    return Path(team).resolve().parent


def read_state(team):
    """`.team/state.json` as a dict. A .team/ without one is a project from
    before modes existed: it is mid-build, so `build` is the safe default."""
    path = Path(team) / STATE_FILE
    state = {}
    if path.exists():
        try:
            state = json.loads(path.read_text())
        except Exception:
            state = {}
    if not isinstance(state, dict):
        state = {}
    state.setdefault("mode", "build")
    budgets = dict(DEFAULT_BUDGETS)
    given = state.get("budgets")
    if isinstance(given, dict):
        for k in DEFAULT_BUDGETS:
            try:
                v = float(given[k])
                if v > 0:
                    budgets[k] = v
            except (KeyError, TypeError, ValueError):
                pass
    state["budgets"] = budgets
    return state


def write_state(team, **fields):
    """Merge `fields` into state.json and write it atomically. Returns the state."""
    path = Path(team) / STATE_FILE
    state = read_state(team)
    state.update(fields)
    state["since"] = state.get("since") or datetime.now(timezone.utc).isoformat()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2) + "\n")
    tmp.replace(path)
    return state


def mode(team):
    m = read_state(team).get("mode")
    return m if m in MODES else "build"


def checkpoint(team):
    """Sha the last build or audit signed off on; falls back to the baseline."""
    state = read_state(team)
    return state.get("checkpoint") or state.get("baseline") or ""


# --- journal ------------------------------------------------------------------

def git(root, *args, timeout=10):
    """git stdout, or '' on any failure. Never raises."""
    import subprocess
    try:
        r = subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def commits_in_range(root, rng):
    """[{sha, ts, msg, files, added, deleted}] for `rng`, newest first.
    Paths under .team/ are dropped, and commits left with no files are omitted:
    the team's own bookkeeping is not work to audit."""
    out = git(root, "log", "--numstat", "--no-renames", "--format=%x01%H%x1f%aI%x1f%s", rng)
    entries = []
    for block in out.split("\x01"):
        lines = [l for l in block.split("\n") if l.strip()]
        if not lines:
            continue
        head = lines[0].split("\x1f")
        if len(head) < 3:
            continue
        files, added, deleted = [], 0, 0
        for line in lines[1:]:
            parts = line.split("\t")
            if len(parts) != 3:
                continue
            a, d, path = parts
            if path == ".team" or path.startswith(".team/"):
                continue
            files.append(path)
            added += int(a) if a.isdigit() else 0
            deleted += int(d) if d.isdigit() else 0
        if not files:
            continue
        entries.append({"sha": head[0], "ts": head[1], "msg": head[2],
                        "files": files, "added": added, "deleted": deleted})
    return entries


def journal(team):
    """Journal entries as written, oldest first. Unparseable lines are skipped."""
    path = Path(team) / JOURNAL_FILE
    if not path.exists():
        return []
    out = []
    for line in _read(path).splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except Exception:
            continue
        if isinstance(entry, dict) and entry.get("sha"):
            out.append(entry)
    return out


def audit_range(team, since=None):
    """`<base>..HEAD` for the unaudited work, or 'HEAD' when there is no
    checkpoint yet (nothing has ever been signed off)."""
    base = since or checkpoint(team)
    return f"{base}..HEAD" if base else "HEAD"


def sync_journal(team, since=None):
    """Rebuild journal.jsonl from git for the current audit range, preserving the
    `intent` line the engineer attached to each sha. Commits that left the range
    (amend, rebase, a closed audit advancing the checkpoint) drop out; their
    intent goes with them, since the sha they described no longer exists."""
    team = Path(team)
    root = project_root(team)
    intents = {e["sha"]: e["intent"] for e in journal(team) if e.get("intent")}
    entries = list(reversed(commits_in_range(root, audit_range(team, since))))
    for e in entries:
        if e["sha"] in intents:
            e["intent"] = intents[e["sha"]]
    path = team / JOURNAL_FILE
    tmp = path.with_suffix(".jsonl.tmp")
    tmp.write_text("".join(json.dumps(e) + "\n" for e in entries))
    tmp.replace(path)
    return entries


def set_intent(team, sha, text):
    """Attach `text` to the journalled commit `sha` (accepts a short sha).
    Returns the full sha, or None when no journal entry matches."""
    entries = journal(team)
    match = next((e for e in entries if e["sha"] == sha or e["sha"].startswith(sha)), None)
    if match is None:
        return None
    match["intent"] = text
    path = Path(team) / JOURNAL_FILE
    tmp = path.with_suffix(".jsonl.tmp")
    tmp.write_text("".join(json.dumps(e) + "\n" for e in entries))
    tmp.replace(path)
    return match["sha"]


# --- clustering and audit pressure --------------------------------------------

def cluster(entries):
    """Group commits that share a file into candidate audit units, so each unit's
    files are disjoint from every other's and `git diff <base>..<head> -- <files>`
    is exactly that unit's net change. Returns [{files, commits, added, deleted}]
    ordered by first appearance."""
    parent = {}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i, e in enumerate(entries):
        parent.setdefault(i, i)
        for f in e["files"]:
            key = ("f", f)
            parent.setdefault(key, key)
            union(i, key)

    groups = {}
    for i, e in enumerate(entries):
        groups.setdefault(find(i), []).append(e)

    out = []
    for members in groups.values():
        files = sorted({f for e in members for f in e["files"]})
        out.append({
            "files": files,
            "commits": [{"sha": e["sha"], "msg": e.get("msg", ""), "intent": e.get("intent", "")} for e in members],
            "added": sum(e.get("added", 0) for e in members),
            "deleted": sum(e.get("deleted", 0) for e in members),
        })
    return out


def pending(team, sync=False, since=None):
    """What is waiting to be audited: counts, churn, and the pressure the dormant
    nudge is built on. `pressure >= 1.0` means "audit recommended"; it is the
    worse of the two budgets so 5 big units and 15 small ones cross together."""
    entries = sync_journal(team, since) if sync else journal(team)
    clusters = cluster(entries)
    churn = sum(e.get("added", 0) + e.get("deleted", 0) for e in entries)
    budgets = read_state(team)["budgets"]
    return {
        "range": audit_range(team, since),
        "commits": len(entries),
        "units": len(clusters),
        "files": len({f for e in entries for f in e["files"]}),
        "churn": churn,
        "pressure": round(max(churn / budgets["churn"], len(clusters) / budgets["units"]), 2),
        "budgets": budgets,
        "clusters": clusters,
    }


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


def snapshot(team, stale_minutes=STALE_MINUTES, sync=False):
    """Everything the status report, the context hook and the Stop gate need."""
    team = Path(team)
    crit = criteria(team)
    plan = plan_rows(team)
    return {
        "team_dir": str(team),
        "mode": mode(team),
        "checkpoint": checkpoint(team),
        "pending": pending(team, sync=sync),
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


def pending_line(p):
    """One sentence describing unaudited work, or '' when there is none."""
    if not p or not p.get("commits"):
        return ""
    line = (f"{p['units']} unit(s) / {p['commits']} commit(s) / {p['churn']} lines unaudited "
            f"({p['range']}).")
    return line + (" Audit recommended: run `/team:audit`."
                   if p.get("pressure", 0) >= 1.0 else " Run `/team:audit` to verify them.")


def next_actions(d):
    """Ordered, human-readable actions for the engineer. Empty list == nothing open.

    A dormant team is never "open": its only action is the audit suggestion, and
    the Stop gate refuses to run at all in that mode."""
    acts = []
    if not d["has_spec"]:
        return []
    if d.get("mode") == "dormant":
        line = pending_line(d.get("pending"))
        return [f"Dormant — work normally, the team loop is off. {line}"] if line else []
    phase = {"finding": "A-loop", "pick": "A2", "final": "A3"} if d.get("mode") == "audit" else \
            {"finding": "Phase 5", "pick": "Phase 4", "final": "Phase 6"}
    unread = [f["file"] for f in d["findings"] if not f["status"]]
    held = [l for l in d["locks"] if l["held"]]
    stale = [l for l in held if l["stale"]]
    broken = [l for l in d["locks"] if l["error"]]
    plan = d["plan"] or []
    counts = {s: sum(1 for r in plan if r["status"] == s) for s in PLAN_STATUSES}
    crit = d["criteria"]

    if unread:
        acts.append(f"Process {len(unread)} unread finding(s) ({phase['finding']}): " + ", ".join(unread))
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
        acts.append("Pick a unit whose files are free (" + phase["pick"] + "): " + ", ".join(d["free_todo"]))
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
            acts.append("All criteria verified, no open units or locks: run the " + phase["final"] + " final pass (" + ", ".join(missing) + ").")
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
