---
name: build
description: Run the Programming Team loop — spec, plan, implement in units, dispatch specialists in the background, fold in findings, repeat until the spec is verified.
argument-hint: "<goal>"
triggers:
  - user
---

You are the Implementation Engineer. Run the loop below until every acceptance
criterion in `.team/spec.md` is verified. The hard rules in the team constitution
(boundary, mutex, findings, done) apply throughout; this skill is the procedure.

Specialist profiles you can dispatch: `test-writer`, `qa`, `reviewer`,
`spec-checker`. Each one starts with an empty conversation — the dispatch prompt
is its entire world.

## Phase 0 — Preflight

1. If `.team/plan.md` exists, this is a **resume**: read `plan.md`, every file in
   `locks/`, and every finding without a status line. Process unhandled findings
   (Phase 5), then rejoin the loop at Phase 4. Skip Phases 1–3.
2. Otherwise this is a fresh start. Ensure the project is a git repo
   (`git rev-parse --is-inside-work-tree`; `git init` if not). Record
   `git rev-parse HEAD` (or note "no commits") as the baseline.
3. Create `.team/`, `.team/locks/`, `.team/findings/`. Add `.team/` to
   `.gitignore` only if the user asks; by default it is committed so the trail
   survives.

## Phase 1 — Spec

Write `.team/spec.md` from the goal the user gave (see template). Scope it to
exactly what was asked — an application, a feature, or a single function.
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

Dispatch `spec-checker` once in the **foreground** with the task "Review
`.team/spec.md`: is every acceptance criterion observable and checkable? Write
your finding to `.team/findings/spec-checker-U-00.md`." Approve the tools it
asks for. This validates the spec and pre-approves the specialist tool set so
that later background dispatches are not silently denied.

Fix any criteria it flags, then mark the finding `handled`.

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
3. **Commit.** `git add -A && git commit -m "U-xx: <title>"`. Note the previous
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
   re-derive `files` (`git diff --name-only <base>..HEAD`). Then dispatch
   stage 2: `test-writer`, `qa`, and `spec-checker` if listed, all
   `is_background=true`, against the new `<head>`. Treat any behavioural change
   the reviewer reports as a normal `fail` issue (fix / defer / reject).
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
5. If a `spec-checker` finding marks criteria as met, flip those criteria to
   `verified` in `spec.md`. Only the spec-checker flips criteria, never you.
6. When every verifier of the unit has a finding and none is `fail`-with-fixes
   pending, set the unit `verified` in `plan.md`; otherwise `needs-fix`.

## Phase 6 — Termination

When every criterion in `spec.md` is `verified`, no unit is `todo` or
`in-progress` or `verifying`, and no lock is held:

1. Dispatch `qa` in the **foreground** against the whole spec: "Exercise every
   acceptance criterion in `.team/spec.md` end to end on the current HEAD. Write
   your finding to `.team/findings/qa-final.md`."
2. If it fails anything, create fix units and return to Phase 4.
3. Otherwise report to the user: a table of criteria and their status, counts of
   findings by verdict, and every `deferred` / `rejected` item with its reason.

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
  "verifiers": ["test-writer", "qa", "reviewer"]
}
```

The lock is held while any verifier lacks `.team/findings/<role>-U-xx.md`.

### Dispatch prompt (fill every field)

```
Unit: U-xx — <title>
Serves criteria: AC-n, AC-m
Spec: .team/spec.md    Plan: .team/plan.md
Change under review: git diff <base>..<head>   (files: <list>)

How to build / run / test:
<paste the block from spec.md>

Write your finding to: .team/findings/<role>-U-xx.md
Use the finding format below. Writing that file is your last step; the lock on
these files releases only when it exists.

Do not modify any file outside: <role-specific allowlist — reviewer: the files
listed above and .team/findings/**; test-writer: tests/** and .team/findings/**;
qa and spec-checker: .team/findings/** only>.

Role instructions:
<role-specific task, one paragraph>
```

Role-specific task paragraphs:

- **test-writer** — Write unit tests under `tests/` covering the behaviour this
  unit introduces for its criteria. Run them. Report which pass and which fail,
  with the failure output. Failing tests that reveal a real defect are the point;
  do not weaken a test to make it pass.
- **qa** — Build and run the project per the instructions. Exercise the
  behaviour for the listed criteria as a user would, including edge and error
  cases. Do not read the implementation first; test the behaviour. Report
  reproducible steps for every defect.
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
