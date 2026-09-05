---
name: status
description: Show the Programming Team's current state — criteria, units, held locks, unread findings, and what to do next. Run after compaction or interruption, or any time to see what the team is doing.
triggers:
  - user
  - model
---

Rebuild situational awareness from `.team/` without re-reading raw files.

1. From the project directory run:

   ```sh
   python3 "${CLAUDE_SKILL_DIR}/scripts/team-status.py"
   ```

   `${CLAUDE_SKILL_DIR}` is this skill's directory. In Devin it is the
   "Base directory" reported when this skill loaded. Options: `--json` for
   machine-readable output, `--stale-minutes N` (default 30).

   If it prints `no .team/ found`, say so and stop; there is no team in this
   project.

2. Show the report to the user verbatim — it is already formatted.

3. What to do next depends on the mode in the report's header:
   - **build** / **audit** — if you are the Implementation Engineer mid-run,
     carry out the **Next actions** in the order listed, following
     `/team:build` Phases 4–6 (an audit's equivalents are `/team:audit` A2–A4):
     unread findings first, then locks, then pick a unit. If you were only asked
     for the status, stop after showing it.
   - **dormant** — the loop is off. Show the report, mention the pending-audit
     line if there is one, and stop. Do not start units or dispatch anyone;
     only `/team:build` or `/team:audit` reopens the team.
