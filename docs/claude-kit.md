# EcoGuard Claude kit

This kit sets up Claude Code in the team repo so every member's sessions start from the same requirements, contracts, ownership and plan. `CLAUDE.md` and the rules are guidance Claude follows; `.claude/settings.json` permissions, `.github/CODEOWNERS` with branch protection, and `scripts/check-no-token.sh` actually enforce things.

## Install (one person, once)
1. Copy everything in the kit into the root of the team repo (private, shared with the teaching team). Nothing in it overwrites a `README.md`.
2. In `.github/CODEOWNERS`, replace `@member1` to `@member4` with GitHub usernames. Add names and student IDs to `docs/members/`.
3. Commit on a branch and open a PR. Everyone reviews it, because it changes how everyone's Claude behaves.
4. On GitHub, protect `main`: require a pull request, and turn on "Require review from Code Owners".

## Set up (each member)
1. Pull `main`.
2. Create `CLAUDE.local.md` in the repo root. It is gitignored, so it stays yours. Put this in it, with your own number:
   ```markdown
   @docs/members/member-2.md

   # My notes
   - Anything personal: sandbox project ID, test account email, how you like answers
   ```
3. Run `claude` in the repo and accept the import prompt if one appears.
4. Run `/context` and check that `CLAUDE.md`, `CLAUDE.local.md` and the unscoped rules are listed under Memory files. Run `/skills` and check that `contract-check`, `rubric-check`, `gate-check` and `new-function` are there.

## Day to day
| When | Do |
| --- | --- |
| Starting a function | `/new-function ingestion upload_init` |
| Planning or finishing a feature | `/rubric-check 2.1.1` |
| Before every commit that touches fields, keys, routes, events or tags | `/contract-check` |
| Before opening a PR | Ask Claude to "run the contract-reviewer agent on this branch" |
| When a gate is due | `/gate-check 2` |
| Before Gate 4 and the demo | Ask Claude to "run the security-reviewer agent" |

## What's inside
| Path | Purpose |
| --- | --- |
| `CLAUDE.md` | Project facts, layout, owners and the rules for every change; loaded in every session |
| `.claude/rules/` | Rules that load only when Claude touches matching files: functions, ingestion, ML, search, AWS, frontend, infrastructure |
| `.claude/skills/` | `contract-check`, `rubric-check`, `gate-check`, `new-function` (with templates) |
| `.claude/agents/` | `contract-reviewer`, `security-reviewer` |
| `.claude/settings.json` | Shared permissions: read-only git and tests run freely; cloud CLIs, pushes and the seed script ask first; force pushes, `rm -rf` and reading secrets are blocked |
| `docs/requirements.md` | Every rubric item with owner, full-marks criteria, the 50% trap and the demo proof, plus spec details |
| `docs/contracts/` | Firestore schema, storage layout, API routes, events: the agreements code must follow |
| `shared/tags.json` | Tag vocabulary and model label map (starter; member 3 confirms) |
| `docs/architecture.md`, `docs/crossovers.md`, `docs/roadmap.md`, `docs/decisions.md` | Services and flows, overlaps between members, phases with gate checklists, decisions made and still open |
| `docs/members/` | One brief per member: what they own, their steps, who they depend on |
| `shared/python/ecoguard_common/auth.py` | Starter helper that reads the gateway's forwarded claims (member 1 owns it) |
| `scripts/check-no-token.sh` | Calls every route without a valid token and expects 401 |
| `.github/` | CODEOWNERS and a PR template with the contract checklist and AI-use note |
| `functions/`, `aws/`, `infra/`, `frontend/`, `tests/` | Empty folders in the agreed layout |

## Keeping it current
- When a Proposed or Open item in `docs/decisions.md` is settled, update the decision and any contract it changes in the same PR.
- When Claude makes the same mistake twice, add a rule: to `CLAUDE.md` if it applies everywhere, otherwise to the matching file in `.claude/rules/`. Keep `CLAUDE.md` under 200 lines.
- Run `/doctor prompt-audit` now and then to find outdated or conflicting instructions.

## Note on AI use
The spec allows generative AI but requires it to be documented and acknowledged, and every member must be able to explain and change their code. The PR template's AI-use section and this kit in the repo are part of that record; mention them in the team report.
