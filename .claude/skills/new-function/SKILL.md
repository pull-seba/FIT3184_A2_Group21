---
name: new-function
description: Scaffold a new GCP Cloud Run function in EcoGuard's agreed layout, with gateway auth, the error shape, a README listing its service account and roles, and a test.
argument-hint: "[area] [function_name]"
disable-model-invocation: true
---

# New Cloud Run function

Create `functions/$0/$1/`.

1. Check the layout in `CLAUDE.md`: if area `$0` belongs to another member, stop and say who owns it.
2. Find this function's route in `docs/contracts/api-routes.md` or its trigger in `docs/contracts/events.md`. If it isn't there, stop: the contract comes first.
3. Copy the files from `${CLAUDE_SKILL_DIR}/templates/` into the new folder, replacing `FUNCTION_NAME` with `$1`, `AREA` with `$0`, and the owner, rubric item and route or trigger from the contract.
4. For an event-triggered function, replace the HTTP handler with `@functions_framework.cloud_event` and drop the gateway auth check; keep the idempotency note.
5. In `README.md`, set the service account to `fn-` plus the function name with underscores turned into hyphens (6 to 30 characters), and list only the roles this function needs.
6. Show the files created and the deploy command for a person to run. Don't deploy.
