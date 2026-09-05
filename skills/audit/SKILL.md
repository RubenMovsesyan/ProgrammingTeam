---
name: audit
description: Verify the commits made since the last team checkpoint — cluster them into audit units and run the same reviewer / test-writer / qa / spec-checker loop the build runs, until they meet the spec. Use after iterating normally on a project a /team:build already delivered.
argument-hint: "[--since <sha|ref>] [--units A-01,A-03]"
triggers:
  - user
---

You are the Implementation Engineer. `/team:build` is a one-off: when it ends the
team goes **dormant** and you work normally, without the loop. This skill is the
other one-off — it takes everything committed since the last checkpoint and puts
it through the same verification the build used, so iterative work keeps the
quality bar without paying four specialists per prompt.

Nothing here is new machinery: audit units are `A-xx` rows in the same
`plan.md`, locks and findings live in the same directories, and findings are
handled by `/team:build` Phase 5 word for word. The one difference is that the
code already exists — you verify first and only write code to fix what the
specialists find.

## A0 — Preflight

1. From the project directory run:

   ```sh
   python3 "${CLAUDE_SKILL_DIR}/scripts/team-audit.py" plan [--since <sha|ref>]
   ```

   `${CLAUDE_SKILL_DIR}` is this skill's directory (in Devin, the "Base
   directory" reported when this skill loaded).

2. It refuses, and you stop, when:
   - there is no `.team/` — say `/team:build <goal>` comes first; an audit
     verifies against a spec, and only a build writes one;
   - the mode is not `dormant` — a build or audit is still open; run
     `/team:status` and finish that instead;
   - there is nothing in the range — say so and stop.

3. Otherwise it prints the proposed units: for each, the files, the commits
   (with any `intent` line recorded while dormant), and the exact diff command.

## A1 — Units and criteria

1. Read each unit's diff. For every unit decide `serves`:
   - **existing criteria** in `spec.md` whose behaviour these files implement —
     the audit re-verifies them, which is how regressions get caught;
   - **new criteria** for behaviour the commits added that no criterion covers.
     Append them to `spec.md` (continue the AC numbering) as observable,
     checkable statements with `status: unverified`, exactly as in a build.
     The spec is the living definition of done; work that outlived it is why
     you are here.
2. Write the units into `plan.md` as `A-01`, `A-02`, … with the files the script
   listed and status `todo`. Title them for what the commits did.
3. Show the user a short message: the units, their commits, the criteria each
   serves, and the ACs you added. Continue unless they object — do not wait for
   approval.
4. Arm the loop:

   ```sh
   python3 "${CLAUDE_SKILL_DIR}/scripts/team-audit.py" open [--since <sha|ref>]
   ```

   Mode becomes `audit`: the constitution and the Stop gate are back until the
   audit closes. If the user asked for a subset (`--units A-01,A-03`), keep only
   those rows in `plan.md`.

## A2 — Verify loop

Repeat until no unit is `todo`, `in-progress`, `verifying` or `needs-fix`:

1. **Pick a unit** whose files are in no held lock.
2. **Do not implement anything.** The commits are already in history. Set the
   unit `verifying` in `plan.md` and write `.team/locks/A-xx.json` from the
   `lock` object the script printed (`base` = checkpoint, `head` = HEAD,
   `files` = the unit's files).
3. **Dispatch stage 1 — reviewer alone**, `is_background=true`, using the
   `/team:build` dispatch template with one change: the change under review is
   `git diff <base>..<head> -- <files>`, not a plain range. Units are file-
   disjoint by construction, so that diff is exactly this unit's net change.
4. When the reviewer's finding arrives, follow `/team:build` Phase 5 step 2:
   re-derive the lock's `head` if it committed, set `stage: verify`, then
   dispatch `test-writer`, `qa` and `spec-checker` in the background.
5. Handle every finding by `/team:build` Phase 5. A `fail` you choose to fix
   becomes an `A-xx-fixN` unit that you *do* implement, commit
   (`A-xx-fixN: <title>`), lock and re-verify like a build unit.

## A3 — Final pass

When every unit is `verified` and no lock is held, dispatch in the background
and wait for both:

- `qa`: "Scope: audit final, range `<base>..HEAD`. Exercise every acceptance
  criterion in `.team/spec.md` end to end and try to break the product. Write
  your finding to `.team/findings/qa-final.md`."
- `spec-checker`: "Verification mode, unit `final`, range `<base>..HEAD`, all
  criteria in `.team/spec.md`. Write your finding to
  `.team/findings/spec-checker-final.md`."

The final pass covers the **whole** spec, not just the audited units — a change
in one place is how a criterion elsewhere regresses. Process both findings
(Phase 5); anything failing becomes a fix unit and you return to A2.

If findings from an earlier build or audit already sit at `qa-final.md` /
`spec-checker-final.md`, move them aside first
(`.team/findings/archive/<timestamp>/`) so this pass writes cleanly.

## A4 — Close

1. ```sh
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/team-state.py" close
   ```

   Mode goes back to `dormant`, the checkpoint advances to HEAD, and the journal
   empties — the audited commits are behind us. The Stop gate and the
   constitution switch off again. Only advance the checkpoint if the audit
   covered the whole range; with `--units` on a subset, leave it where it is and
   tell the user which units remain unaudited.
2. Report: units audited with their commits, findings by verdict, criteria added
   and their status, and every `deferred` / `rejected` item with its reason.
3. Remind the user in one line that the team is dormant again: ordinary prompts
   do not run the loop, and `/team:audit` picks up whatever comes next.

## Flags

- `--since <sha|ref>` — audit from an older commit than the checkpoint (e.g.
  re-audit work a previous pass deferred). Does not move the checkpoint back.
- `--units A-01,A-03` — audit a subset of the proposed units. The checkpoint
  only advances when the audited units cover the whole range.
