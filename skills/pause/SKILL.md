---
name: pause
description: Pause the Programming Team — turn off the Stop gate so the engineer can talk with the user without being pushed to continue. Background specialists already running keep running. Resume with /team:resume.
triggers:
  - user
  - model
---

Pause the team's loop for conversation or a manual intervention.

1. Find the project's `.team/` directory (at or above the current directory). If
   there is none, say so and stop.
2. Create the marker file: `touch .team/paused`.
3. Confirm to the user: "Team paused. The Stop gate is off; specialists already
   dispatched will still finish and write findings. Run `/team:resume` to
   continue the loop."

Do not dispatch new specialists or pick new units while paused. Do continue to
answer questions and, if asked, process findings.
