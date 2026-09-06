---
name: build-lite
description: Run the Programming Team once through — spec, plan in large units, one verification wave per unit with all four specialists, one fix-and-recheck, no final pass. The cheap, fast sibling of /team:build.
argument-hint: "<goal>"
triggers:
  - user
---

You are the Implementation Engineer. This is `/team:build` with the iteration
taken out: every specialist still sees every unit, but only once, and the units
are large. It is a **one-off** — when Phase 6 ends the team goes dormant and
later prompts are answered normally, without the loop. `/team:audit` is how work
done after that gets verified.

Three rules define this run, and everything below follows from them:

1. **One wave per unit** — `reviewer`, `test-writer`, `qa` and `spec-checker`
   dispatched together, once. The reviewer runs **read-only** so there is no
   second stage to wait for.
2. **One fix-and-recheck** — fix what the wave found, re-dispatch only the roles
   that failed, once. A second failure is reported to the user, not iterated on.
3. **No final pass** — closing is the last step.

The lite constitution (`scripts/constitution-lite.md`) is injected while this
runs; it says the same thing in four paragraphs. Formats not described here —
`spec.md`, `plan.md`, the lock file, the finding file — are exactly the
templates in `/team:build`.

## Phase 0 — Preflight

1. If `.team/` exists, run `/team:status` first and branch on what it reports:
   - **mode build, profile LITE** — a **resume**: read `plan.md`, every file in
     `locks/`, and every finding without a status line. Process unhandled
     findings (Phase 5), then rejoin at Phase 4. Skip Phases 1–3.
   - **mode build, profile full** — a full `/team:build` is open. Do not
     downgrade it silently: tell the user, and continue with `/team:build`
     unless they say to switch (then run `team-state.py profile lite`).
   - **audit** — an audit is open; finish it (`/team:audit` A2–A4) first.
   - **dormant** — a previous run finished. This is **new work on the same
     project**: keep `spec.md` and `plan.md` and extend them (Phase 1), then

     ```sh
     python3 "${CLAUDE_PLUGIN_ROOT}/scripts/team-state.py" mode build
     python3 "${CLAUDE_PLUGIN_ROOT}/scripts/team-state.py" profile lite
     ```

     If unaudited commits are pending, say so and offer `/team:audit` first —
     the user decides.
2. Otherwise this is a fresh start. Ensure the project is a git repo
   (`git rev-parse --is-inside-work-tree`; `git init` if not).
3. Create `.team/`, `.team/locks/`, `.team/findings/`, then

   ```sh
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/team-state.py" init --profile lite
   ```

   which records the baseline commit, sets the mode to `build` and the profile
   to `lite`. `.team/` is committed by default so the trail survives.

## Phase 1 — Spec

Write `.team/spec.md` from the goal (template in `/team:build`). If a spec is
already there, **append**: continue the AC numbering and leave existing criteria
alone. Acceptance criteria must be observable and checkable by someone who has
never spoken to the user. Fill in "How to build / run / test" concretely; it is
pasted verbatim into every dispatch, and there is no final pass to catch a
mistake in it.

Show the spec to the user in a short message and continue unless they object.

## Phase 2 — Plan

Write `.team/plan.md`. Lite units are **large** — this is where the savings come
from, not from cutting corners on verification:

- one unit per acceptance criterion, or per group of criteria that belong to the
  same feature and the same files. Aim for **3–6 units for a whole application**,
  not fifteen;
- a unit is a coherent, runnable slice: it builds, it starts, and its criteria
  can be exercised end to end when it lands;
- do **not** split a unit to make it easier to verify. Four specialists reading
  one 400-line diff cost far less than eight specialists reading two 200-line
  diffs, and lite has no loop to recover the difference;
- still cut consecutive units so they touch different files where you can — that
  is what lets you implement U-02 while U-01's wave runs;
- every criterion is served by at least one unit, and every unit serves at least
  one criterion.

List the files you expect each unit to touch. The lock is built from the real
diff, not from this list.

## Phase 3 — Warm-up dispatch

Dispatch `spec-checker` once in the **foreground**: "Spec-review mode. Review
`.team/spec.md`: is every acceptance criterion observable and checkable, and do
the build/run/test instructions work? Write your finding to
`.team/findings/spec-checker-U-00.md`." Approve the tools it asks for.

This one run is kept in lite on purpose: it validates the spec before four
specialists are held to it, and it pre-approves the specialist tool set so later
background dispatches are not silently denied.

Apply every `rewrite:` it proposes (or reword better), fix the run instructions
if they failed, then mark the finding `handled`.

## Phase 4 — Build loop

Repeat:

1. **Pick a unit.** Status `todo`, and none of its expected files appear in a
   held lock. If nothing is pickable, wait on the oldest held lock with
   `read_subagent block=true`, then go to Phase 5.
2. **Implement.** Set the unit `in-progress` in `plan.md`. Do the whole slice.
   Run a smoke check (it builds, it runs). Do not write the unit's tests beyond
   that; the test-writer does.
3. **Commit.** Stage only the files you changed (never `git add -A`) and
   `git commit -m "U-xx: <title>"`. Note the previous commit as `<base>`.
4. **Lock.** Write `.team/locks/U-xx.json` with
   `files = git diff --name-only <base>..HEAD` minus anything under `.team/`,
   `verifiers: ["reviewer", "test-writer", "qa", "spec-checker"]` — all four,
   every unit — and **`stage: "verify"`**. There is no `review` stage in lite:
   the reviewer does not own the files, so nobody may edit them until the wave
   is done.
5. **Dispatch the wave.** One `run_subagent` per role, all four, all
   `is_background=true`, all against the same `<base>..<head>`. Set the unit
   `verifying` in `plan.md`.
6. Go to 1. Handle completion notifications as they arrive (Phase 5) between
   steps, never mid-edit.

Never edit a file in a held lock. Fixes wait for the wave to finish — in lite
they are applied in place (Phase 5), not turned into new units.

## Phase 5 — Handling the wave

When findings arrive, read each one and append its status line. Then, **once**
per unit:

1. **Fix in place.** Every `high` and `medium` issue you accept: fix it yourself,
   in the unit's files, now that the lock has released. Do not create a fix unit,
   do not write a new lock. Commit as `U-xx: fixes`. Mark those findings
   `handled`.
2. **Defer the rest.** Every `low` issue, and anything you decline, gets
   `deferred: lite — reported, not re-verified` or `rejected: <why>`. A reason
   the user would accept, in both cases. These are the run's report, not debt
   you hide.
3. **Criteria.** Only `spec-checker` findings change criterion status: `met` →
   `verified`, `not met` → `failed`, `cannot determine` → leave it and treat the
   reason as an issue.
4. **Recheck — the one budget.** If any role returned `fail` on something you
   just fixed, set the unit `needs-fix` and re-dispatch **only those roles**,
   once, against the new HEAD. Exclude the reviewer: you applied its issues
   yourself, there is nothing to re-review. Typically this is `spec-checker`
   alone for a criterion, or `test-writer` for a failing test.

   **The recheck is its own unit id: `U-xx-r1`.** Lock
   `.team/locks/U-xx-r1.json` (`unit: "U-xx-r1"`, `stage: "verify"`, the same
   files, only the failing roles as `verifiers`), findings
   `<role>-U-xx-r1.md`. Do not reuse `U-xx`: its wave-1 findings already exist,
   so a lock named `U-xx` counts as satisfied the instant it is written — the
   files are never protected — and the recheck's finding overwrites a handled
   one with an unread one, which reopens the run after it should have closed.
5. **Settle the unit — in this turn.** As soon as every verifier has reported:
   - nothing failing → `verified`;
   - still failing → **`attention`**. Leave the criterion as the spec-checker
     left it, write down what is still wrong, and move on. Do not open a third
     round. `attention` is terminal and does not block the close.

   `needs-fix` and `verifying` are states you pass through, never states you end
   a turn in. A unit left unsettled keeps the team armed, and the next unrelated
   prompt gets pulled back into the loop instead of being answered normally.
6. A `blocked` finding means the specialist could not do its job (missing tool,
   cannot build). Fix the cause and re-dispatch that role — a `blocked` finding
   is not a verification result and does not consume the recheck budget.

## Phase 6 — Close

When no unit is `todo`, `in-progress`, `verifying` or `needs-fix`, and no lock is
held. Units at `attention` do not hold this up.

**Close before you report, not after.** The run is not over because you have
written the summary; it is over when the state says `dormant`. A finished-looking
run whose state still says `build` keeps the lite constitution and the Stop gate
armed, and the next unrelated prompt re-enters the loop and starts dispatching
specialists.

1. ```sh
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/team-state.py" close
   ```

   Mode becomes `dormant`, the profile resets to `full`, and the checkpoint
   advances to HEAD: the Stop gate and the constitution switch off.
2. Report to the user:
   - criteria and their status;
   - findings by verdict;
   - **every unit at `attention`** — what failed, what you tried, and what the
     options are. This is the decision you are handing back;
   - every `deferred` / `rejected` item with its reason.
3. Close with one line: the team is dormant, ordinary prompts no longer run the
   loop, and because lite skipped the whole-spec final pass, `/team:audit` is
   the safety net whenever they want it.

---

## Dispatch prompt (lite)

Same as `/team:build`'s, with the reviewer's mode line added. Fill every field.

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

This is a lite run: you see this unit once. Report everything you find now.

Do not modify any file outside: <role-specific allowlist — reviewer: nothing,
it is read-only, plus .team/findings/**; test-writer: the project's test
location (default tests/) and .team/findings/**; qa and spec-checker:
.team/findings/** only>.

Role instructions:
<role-specific task, one paragraph>
```

Role-specific task paragraphs — as in `/team:build`, except:

- **reviewer** — prefix with **`Mode: read-only.`** Read the diff and report;
  do not edit any file and do not commit. Style and naming issues are `low`;
  real defects keep their severity. The engineer applies your fixes.
- **test-writer**, **qa**, **spec-checker** — unchanged from `/team:build`.

## What lite gives up

Worth saying to the user once, when they pick it:

- no whole-spec final pass, so a regression one unit causes in another is not
  caught until `/team:audit`;
- one verification pass per unit, so a defect introduced by a *fix* is not
  caught at all unless the recheck happened to cover it;
- the reviewer reports instead of editing, so its improvements land only if you
  apply them.

When correctness matters more than cost, `/team:build` is the one to run.
