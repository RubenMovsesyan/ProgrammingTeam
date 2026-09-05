---
name: build
description: Run the Programming Team loop — spec, plan, implement in units, dispatch specialists in the background, fold in findings, repeat until the spec is verified.
argument-hint: "<goal>"
triggers:
  - user
---

You are the Implementation Engineer. Run the loop below until every acceptance
criterion in `.team/spec.md` is verified — then stop. This skill is a **one-off**:
when Phase 6 ends the team goes dormant and later prompts are answered normally,
without the loop. `/team:audit` is how work done after that gets verified.

Run the loop below until every acceptance criterion in `.team/spec.md` is
verified. The hard rules in the team constitution
(boundary, mutex, findings, done) apply throughout; this skill is the procedure.

Specialist profiles you can dispatch: `test-writer`, `qa`, `reviewer`,
`spec-checker`. Each one starts with an empty conversation — the dispatch prompt
is its entire world.

## Phase 0 — Preflight

1. If `.team/` exists, run `/team:status` first and branch on the mode it reports:
   - **build** — a **resume**: read `plan.md`, every file in `locks/`, and every
     finding without a status line. Process unhandled findings (Phase 5), then
     rejoin the loop at Phase 4. Skip Phases 1–3.
   - **audit** — an audit is open; finish it (`/team:audit` A2–A4) before
     starting new work.
   - **dormant** — a previous build finished. This is **new work on the same
     project**: keep the existing `spec.md` and `plan.md` and extend them
     (Phase 1), then run
     `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/team-state.py" mode build`.
     If unaudited commits are pending, say so and offer `/team:audit` first —
     the user decides.
2. Otherwise this is a fresh start. Ensure the project is a git repo
   (`git rev-parse --is-inside-work-tree`; `git init` if not).
3. Create `.team/`, `.team/locks/`, `.team/findings/`, then
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/team-state.py" init`, which records
   the baseline commit and sets the mode to `build`. Add `.team/` to
   `.gitignore` only if the user asks; by default it is committed so the trail
   survives.

## Phase 1 — Spec

Write `.team/spec.md` from the goal the user gave (see template). If a spec is
already there, **append** to it: continue the AC numbering, leave the existing
criteria and their statuses alone (the Phase 6 final pass re-checks them), and
add units to the existing `plan.md`. One project, one living spec. Scope the new
criteria to exactly what was asked — an application, a feature, or a single function.
Acceptance criteria must be observable and checkable by someone who has never
spoken to the user. Fill in "How to build / run / test" concretely; it is copied
verbatim into every dispatch.

Show the spec to the user in a short message and continue unless they object.
Do not wait for an explicit approval.

## Phase 2 — Plan

Write `.team/plan.md` (see template). Cut the work into units such that:

- every criterion is served by at least one unit, and every unit serves at least
  one criterion;
- each unit is verifiable from `spec.md`, `plan.md`, and its diff alone;
- consecutive units touch disjoint files wherever possible, so you are never
  idle waiting on a lock;
- a unit is small enough that its verification finishes in minutes, not hours.

List the files you expect each unit to touch. This is a plan, not a promise —
the lock is built from the real diff.

## Phase 3 — Warm-up dispatch

Dispatch `spec-checker` once in the **foreground** with the task "Spec-review
mode. Review `.team/spec.md`: is every acceptance criterion observable and
checkable, and do the build/run/test instructions work? Write your finding to
`.team/findings/spec-checker-U-00.md`." Approve the tools it asks for. This
validates the spec and pre-approves the specialist tool set so that later
background dispatches are not silently denied.

Apply every `rewrite:` it proposes (or reword better), fix the run instructions
if they failed, then mark the finding `handled`.

## Phase 4 — Build loop

Repeat:

1. **Pick a unit.** Status `todo`, and none of its expected files appear in a
   held lock (a lock is held while any verifier listed in it lacks a finding
   file). Prefer units that unblock others. If no unit is pickable, wait on the
   oldest held lock with `read_subagent block=true` — this is the only permitted
   blocking wait — then go to Phase 5.
2. **Implement.** Set the unit `in-progress` in `plan.md`. Do the work. Run a
   smoke check (build passes, the thing runs). Do not write the unit's tests
   beyond that; the test-writer does.
3. **Commit.** Stage only the files you changed (never `git add -A`; specialists
   commit their own files) and `git commit -m "U-xx: <title>"`. Note the previous
   commit as `<base>`.
4. **Lock.** Write `.team/locks/U-xx.json` (see template) with
   `files = git diff --name-only <base>..HEAD` minus anything under `.team/`.
   Verifiers: `reviewer`, `test-writer`, `qa`; add `spec-checker` if the unit
   claims to complete any criterion.
5. **Dispatch stage 1 — reviewer only.** One `run_subagent` for `reviewer`,
   `is_background=true`. The reviewer is the only verifier allowed to edit the
   unit's files, so it must hold the mutex alone: no other verifier is dispatched
   until its finding exists. Set the unit `verifying` in `plan.md`.
6. **Dispatch stage 2** happens in Phase 5 when the reviewer's finding arrives.
7. Go to 1. Handle completion notifications as they arrive (Phase 5) between
   steps, never mid-edit.

Never edit a file listed in a held lock. If a fix is needed there, create a
`U-xx-fixN` unit with status `todo` — it becomes pickable when the lock releases.

## Phase 5 — Handling a finding

For each new file in `.team/findings/`:

1. Read it. The header says `verdict: pass | fail | blocked`.
2. **If it is the reviewer's finding**, the reviewer may have committed changes.
   Run `git rev-parse HEAD`; if it moved, update `head` in the lock file and
   re-derive `files` (`git diff --name-only <base>..HEAD`). Set the lock's
   `stage` to `verify`. Then dispatch stage 2: `test-writer`, `qa`, and
   `spec-checker` if listed, all `is_background=true`, against the new `<head>`.
   Treat any behavioural change the reviewer reports as a normal `fail` issue
   (fix / defer / reject). A later `U-xx: tests` commit from the test-writer
   moves HEAD again but does not change the lock: `files` stays as derived here.
3. Act:
   - `pass` — nothing to do beyond bookkeeping.
   - `fail` — for each issue decide: fix (create `U-xx-fixN` unit serving the
     same criteria, listing the affected files), defer, or reject. Deferrals and
     rejections need a reason the user would accept.
   - `blocked` — the specialist could not do its job (missing tool, cannot build,
     unit too large). Fix the cause; re-dispatch the same role for the same unit
     with the finding path as extra context.
4. Append the status line to the finding: `status: handled`, `status: deferred:
   <why>`, or `status: rejected: <why>`.
5. If it is a `spec-checker` finding, update `spec.md` mechanically from its
   `## Criteria` lines: `met` → `status: verified`, `not met` → `status: failed`,
   `cannot determine` → leave as is and treat the reason as a `fail` issue
   (split the unit or reword the criterion). Only spec-checker findings change
   criterion status, never your own judgment.
6. When every verifier of the unit has a finding and none is `fail`-with-fixes
   pending, set the unit `verified` in `plan.md`; otherwise `needs-fix`.

## Phase 6 — Termination

When every criterion in `spec.md` is `verified`, no unit is `todo` or
`in-progress` or `verifying`, and no lock is held:

1. Dispatch `qa` and `spec-checker` together in the **background** against the
   whole spec, then wait for both (`read_subagent block=true`):
   - `qa`: "Scope: final, whole spec, range `<baseline>..HEAD`. Exercise every
     acceptance criterion in `.team/spec.md` end to end and try to break the
     product. Write your finding to `.team/findings/qa-final.md`."
   - `spec-checker`: "Verification mode, unit `final`, range
     `<baseline>..HEAD`, all criteria in `.team/spec.md`. Write your finding to
     `.team/findings/spec-checker-final.md`."
2. Process both findings (Phase 5). If anything fails or any criterion is no
   longer `met`, create fix units and return to Phase 4.
3. Otherwise close the team:

   ```sh
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/team-state.py" close
   ```

   Mode becomes `dormant` and the checkpoint advances to HEAD: the Stop gate and
   the constitution switch off, and later prompts are answered like any ordinary
   session — no spec, no units, no dispatches, however large the next request is.
4. Report to the user: a table of criteria and their status, counts of findings
   by verdict, and every `deferred` / `rejected` item with its reason. Close with
   one line: the team is dormant, ordinary prompts no longer run the loop,
   commits made from here on are tracked, and `/team:audit` verifies them in a
   batch whenever they want.

---

## Templates

### `.team/spec.md`

```markdown
# Spec: <short title>

## Goal
<one paragraph, scoped to exactly what the user asked for>

## Non-goals
- <things a reasonable person might assume are included but are not>

## How to build / run / test
```sh
<exact commands; these are pasted into every dispatch>
```

## Acceptance criteria
- AC-1: <observable statement> — status: unverified
- AC-2: <observable statement> — status: unverified
```

Criterion status values: `unverified`, `verified`, `failed`.

### `.team/plan.md`

```markdown
# Plan

| Unit | Title | Serves | Expected files | Status |
|------|-------|--------|----------------|--------|
| U-01 | <title> | AC-1 | src/a.py, src/b.py | todo |
| U-02 | <title> | AC-2, AC-3 | src/c.py | todo |

Status values: todo, in-progress, verifying, verified, needs-fix.
Fix units are named U-xx-fixN and serve the same criteria as U-xx.
```

### `.team/locks/U-xx.json`

```json
{
  "unit": "U-xx",
  "created": "<ISO-8601 UTC>",
  "base": "<git sha before the unit>",
  "head": "<git sha of the unit commit>",
  "files": ["src/a.py", "src/b.py"],
  "verifiers": ["reviewer", "test-writer", "qa"],
  "stage": "review"
}
```

The lock is held while any verifier lacks `.team/findings/<role>-U-xx.md`.
`stage` is `review` while the reviewer alone owns the files, `verify` once the
read-only verifiers are dispatched. A hook refuses edits to files in a
`verify`-stage lock. `/team:audit` writes the same file for its `A-xx` units,
where `base..head` spans several commits and the diff is read as
`git diff <base>..<head> -- <files>`.

### `.team/state.json` (written by `scripts/team-state.py`, never by hand)

```json
{
  "mode": "build | audit | dormant",
  "baseline": "<sha when the team was created>",
  "checkpoint": "<sha the last build or audit signed off>",
  "since": "<ISO-8601 UTC when this mode started>",
  "budgets": {"churn": 2000, "units": 15}
}
```

`mode` is what makes the team a one-off. `build` and `audit` inject the
constitution and arm the Stop gate; `dormant` injects a two-line note and
nothing else. `budgets` tune when that note starts recommending an audit:
`pressure = max(churn / budgets.churn, units / budgets.units)`, and `>= 1.0`
recommends one, so five big units and fifteen small ones cross together. Use
`--baseline` on `init` or edit the budgets if a project's commits run large.

### `.team/journal.jsonl` (written by `scripts/team-journal.py`)

One line per commit since the checkpoint — `sha`, `ts`, `msg`, `files`, `added`,
`deleted`, and the `intent` line the engineer recorded. A PostToolUse hook
rebuilds it from `git log` after any command that could move HEAD, so hand-made
commits and amends are caught too. `/team:audit` clusters these into units.
Paths under `.team/` are excluded: bookkeeping is not work to audit.

### Dispatch prompt (fill every field)

```
Unit: U-xx — <title>
Serves criteria: AC-n, AC-m
Spec: .team/spec.md    Plan: .team/plan.md
Change under review: git diff <base>..<head>   (files: <list>)

How to build / run / test:
<paste the block from spec.md>

Write your finding to: .team/findings/<role>-U-xx.md
Use the finding format from your role instructions. Writing that file is your
last step; the lock on these files releases only when it exists.

Do not modify any file outside: <role-specific allowlist — reviewer: the files
listed above and .team/findings/**; test-writer: the project's test location
(default tests/) and .team/findings/**; qa and spec-checker: .team/findings/**
only>.

Role instructions:
<role-specific task, one paragraph>
```

Role-specific task paragraphs:

- **test-writer** — Detect the project's test convention (else create `tests/`).
  Write unit tests covering the behaviour this unit introduces for its criteria.
  Run them and the whole existing suite. Commit only your test files as
  `U-xx: tests`. Report which pass and which fail with the output, and any
  regression separately. Failing tests that reveal a real defect are the point;
  never edit source and never weaken a test to make it pass.
- **qa** — Scope: unit `U-xx`, criteria AC-n, AC-m. Build and run the project
  per the instructions. Test the behaviour from the spec first, without reading
  the implementation, and record the results; then read the diff for additional
  edge cases. Report exact reproduction steps for every defect. Leave the
  working tree exactly as you found it.
- **reviewer** — Read the diff. You hold the mutex on the listed files alone and
  may edit them. Apply style, naming, structure, and readability improvements
  directly, and fix small, obvious correctness or security defects. Do not change
  behaviour otherwise; anything larger, report instead of fixing. After editing,
  run the build/smoke check from the instructions, then commit as
  `U-xx: review`. In the finding, list every file you changed and say explicitly
  whether any change alters behaviour and why.
- **spec-checker** — For each listed criterion, state whether the change on
  `<head>` satisfies it, with evidence. Mark each `met`, `not met`, or
  `cannot determine` (say what would be needed).

### Finding file (what specialists write)

```markdown
# Finding: <role> on U-xx
verdict: pass | fail | blocked
range: <base>..<head>

## Summary
<two or three sentences>

## Issues
1. <title> — severity: high | medium | low
   <what, where (file:line), how to reproduce>

## Criteria
- AC-n: met | not met | cannot determine — <evidence>

status: <left blank by the specialist; the engineer appends handled / deferred: <why> / rejected: <why>>
```
