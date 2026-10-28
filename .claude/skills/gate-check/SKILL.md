---
name: gate-check
description: Run the integration checklist for a team gate (1 to 4, or demo) from docs/roadmap.md and report what passes, what fails and who owns each gap.
argument-hint: "[1|2|3|4|demo]"
disable-model-invocation: true
allowed-tools: Read Grep Glob Bash(git log *) Bash(git status *)
---

# Gate check

Gate: $ARGUMENTS

1. Read this gate's checklist in `docs/roadmap.md`. If no gate was given, use the first gate whose date hasn't passed.
2. For each item, look for evidence in the repo: code, config, tests, scripts, merged contracts. Only run read-only commands.
3. Anything that needs the deployed system, such as an upload, an email or a call to the gateway, is for a person to run. Give the exact command or steps, for example `API_BASE=<gateway url> scripts/check-no-token.sh`.
4. Never deploy, never delete cloud resources and never write to the shared Firestore or buckets.

Report a table with columns: item, owner, status (Pass, Fail, Needs a person), evidence or the step to run. End with what blocks the gate and who owns each blocker.
