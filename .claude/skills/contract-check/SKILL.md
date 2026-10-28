---
name: contract-check
description: Check current changes against EcoGuard's contracts (Firestore schema, storage layout, API routes, events, tag names) and file ownership. Use before committing or opening a PR, or whenever a change touches Firestore fields, bucket keys, route JSON, Pub/Sub payloads or tag names.
allowed-tools: Bash(git status *) Bash(git diff *) Read Grep Glob
---

# Contract check

1. Collect the changes: run `git status --short` and `git diff HEAD`. If the working tree is clean, use `git diff main...HEAD` instead.
2. Read the contracts the changes touch:
   - `docs/contracts/firestore-schema.md`: field names and types, which function owns each field written, merge-only writes
   - `docs/contracts/storage-layout.md`: bucket names, key patterns, signed URL settings, the URL helper
   - `docs/contracts/api-routes.md`: paths, request and response JSON, error shape, `FileSummary`
   - `docs/contracts/events.md`: triggers and payloads
   - `shared/tags.json`: every tag string used
   - `.github/CODEOWNERS`: whether a changed file belongs to another member
3. Also check the "Rules for every change" in `CLAUDE.md`: no credentials, no stored URLs, no stored query photos, per-frame maximum, calls only through the gateway, idempotent event handlers.
4. If a route was added or removed, check `scripts/check-no-token.sh` lists the same routes as `api-routes.md`.

Report in three groups: **Breaks a contract**, **Touches another member's file**, **Fine**. For each problem give the file and line, the contract line it breaks and the fix. If the code is right and the contract needs to change, name the contract's owner and say it needs its own PR. End with one line: `Contract check: pass` or `Contract check: fail`.

Don't edit any files.
