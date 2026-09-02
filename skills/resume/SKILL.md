---
name: resume
description: Resume a paused Programming Team — remove the pause marker, show the current status, and continue the loop from its next actions.
triggers:
  - user
  - model
---

Resume the team's loop after `/team:pause`.

1. Find the project's `.team/` directory (at or above the current directory). If
   there is none, say so and stop.
2. Remove the marker: `rm -f .team/paused`.
3. Run `/team:status` and carry out its **Next actions** in order, following
   `/team:build` Phases 4–6.
