---
name: release
description: Release a stale verification lock whose specialist never reported. Writes a synthetic `blocked` finding per missing verifier so the lock releases through the normal path and the audit trail records it. Refuses unless the lock is stale or --force is given.
argument-hint: "<unit> [--role ROLE] [--force] [--reason TEXT]"
triggers:
  - user
  - model
---

Release a lock that is stale — a specialist has not written its finding within
the threshold (default 30 minutes) and is presumed dead.

1. First check the subagent panel: if the specialist is still running, do not
   release; wait or cancel it deliberately.
2. From the project directory run:

   ```sh
   python3 "${CLAUDE_SKILL_DIR}/scripts/team-release.py" <unit> [--role ROLE] [--force] [--reason "..."]
   ```

   `${CLAUDE_SKILL_DIR}` is this skill's directory (in Devin, the "Base
   directory" reported when this skill loaded). Without `--role` every verifier
   still waiting is released. The script refuses a non-stale lock unless
   `--force` is passed — use `--force` only after cancelling the specialist.

3. The script writes `.team/findings/<role>-<unit>.md` with `verdict: blocked`
   and an empty `status:`. Process it like any finding (Phase 5): normally
   re-dispatch the role for the unit; otherwise mark it `deferred: <why>`.

Never delete or edit lock files by hand; this is the only sanctioned way to
release one without a real finding.
