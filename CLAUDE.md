# Aussie EcoGuard: Friends & Foes

FIT3184 2026 S2 Assignment 2, a four-person team project. A multi-cloud serverless app: signed-in users upload wildlife photos and videos; the system makes thumbnails and tags species with ML; users then search by tags, thumbnail, uploaded file or lost-pet photo, edit tags in bulk, delete files, get email alerts by tag and ask a Lex chatbot.

Due 23:55 Mon 2 Nov 2026. Marks are awarded only in a live Zoom demo, where any member can be asked about any code. Every change must be something its owner can explain and modify.

## Read before you build
- Requirements and rubric, per item, with owner: `docs/requirements.md`
- Contracts: `docs/contracts/` (Firestore schema, storage layout, API routes, events) and `shared/tags.json`
- Architecture and the three cross-cloud links: `docs/architecture.md`
- Where members' work overlaps: `docs/crossovers.md`
- Phases, gates and checklists: `docs/roadmap.md`; each member's brief: `docs/members/`
- Decisions made, proposed and still open: `docs/decisions.md`

## Architecture
- AWS: Cognito user pool (sign-up, sign-in) and identity pool (credentials for the Lex widget); Lex V2 bot with a fulfilment Lambda; a Lambda that turns Pub/Sub pushes into SNS emails.
- GCP: API Gateway in front of every endpoint; Cloud Run functions in Python; Firestore; Cloud Storage; Pub/Sub; Firebase Hosting for the single-page app.
- Cross-cloud link 1: API Gateway verifies the Cognito ID token. Link 2: the Lex fulfilment Lambda calls the GCP API. Link 3: tag changes travel Pub/Sub → AWS Lambda → SNS email.

## Repository layout and owners
Member 1: identity and cross-cloud. Member 2: ingestion and storage. Member 3: ML and detection. Member 4: search and chatbot.

```text
frontend/                       Angular app; shell, routing, auth pages, API client: 1
  src/app/                      root component, routes (app.routes.ts) and providers: 1
    api/                        shared API client (attaches the Cognito ID token): 1
    components/gallery/         the one results gallery: 4 (delete action: 2)
    pages/<page>/               upload: 2 · search, tags, chat: 4 · query-by-file, lost-pet: 3 · notifications: 1
functions/                      GCP Cloud Run functions, one folder per function
  ingestion/                    upload_init, process_upload, get_file, delete_files: 2
  ml/                           tagging container, search_by_file, lost_pet: 3
  search/                       tag_query, thumbnail_lookup, bulk_tags: 4
  notify/                       Firestore trigger that publishes tag changes: 1
aws/
  lex/                          bot definition and fulfilment Lambda: 4
  notify/                       Pub/Sub push receiver that publishes to SNS: 1
  iam/                          IAM role policies (each owner drafts, 1 reviews): 1
infra/
  gateway/                      API Gateway OpenAPI spec: 1
  gcp/                          buckets, service accounts, Firestore indexes: owner of each resource
shared/
  tags.json                     tag vocabulary and model label map: 3
  python/ecoguard_common/       auth.py: 1 · urls.py: 2 · tag_match.py: 4
scripts/                        seed_data.py: 2 · check-no-token.sh
tests/                          cross-member checks for the gates
docs/                           requirements, contracts, plans
```

## Rules for every change
- Use only names defined in `docs/contracts/` and `shared/tags.json`: Firestore fields, bucket keys, routes, JSON shapes, event payloads, tag names. If something you need isn't defined, stop and say so instead of inventing it.
- A file's ID is the lowercase hex SHA-256 of its bytes. It is the Firestore document ID and the stem of every storage key for that file.
- Firestore: write only the fields your function owns (see the schema), with `set(..., merge=True)` or `update()`. Never overwrite a whole document.
- Store bucket, key and the permanent `gs://` address, never a signed URL. Create signed URLs only when building a response.
- A video's tag counts are the maximum count in any single extracted frame, never the sum.
- Every HTTP endpoint sits behind API Gateway's Cognito check, and no Cloud Run service allows unauthenticated calls. Read the caller with `ecoguard_common.auth.get_user`.
- No credentials anywhere in the repo or the frontend bundle: no service account keys, AWS access keys or tokens. Cross-cloud calls use Workload Identity Federation or OIDC tokens.
- Each function runs as its own service account or IAM role with only the permissions it uses, listed in its folder's README.
- Photos sent to search (by file, lost pet) are processed in memory and never stored or indexed.
- Only the media bucket has upload triggers; thumbnails and frames go to the derived bucket.
- Event handlers are idempotent: Eventarc and Pub/Sub can deliver the same event twice.
- Don't edit files another member owns. Propose the change in a PR that requests their review (`.github/CODEOWNERS`).
- Prefer the simplest code its owner can explain in the Q&A, and comment any non-obvious choice.

## Stack
- Functions: Python 3.12 with `functions-framework`; tests with `pytest`, run from each function's folder.
- Frontend: Angular 21 (LTS) and TypeScript on Firebase Hosting (Proposed). No frontend unit tests: `ng generate` skips spec files.
- Regions: GCP `us-east1`, AWS `us-east-1` (Decided 27 Oct: Firestore and the Cognito user pool already live there and can't move).
- Anything marked Proposed in `docs/decisions.md` may still change: flag code that depends on it.

## Commands
- Function tests: `cd functions/<area>/<function> && python -m pytest`
- Format Python before committing: `ruff format` from the repo root (settings in `ruff.toml`; `pip install ruff` first, or run `uvx ruff format`)
- Frontend: `cd frontend && npm start` (dev server on http://localhost:5173), `npm run build`
- New page or component: `cd frontend && npx ng g c pages/<page>` or `npx ng g c components/<name>`; both land under `src/app/`.
- Check every route rejects calls without a token: `API_BASE=<gateway url> scripts/check-no-token.sh`
- Deploys (`gcloud`, `firebase`, `aws`) always need a person to approve them.

## Git and pull requests
- One branch per task, prefixed with the member number: `m2/upload-init`. Merge to `main` only through a PR; never push to `main` or force-push.
- Members commit their own work from their own accounts: the rubric checks for a balanced commit history.
- Every PR names its rubric item, confirms `/contract-check` passed and notes where Claude helped (the spec requires AI use to be acknowledged).
- A contract change is its own PR by the contract's owner, with every affected member requested as a reviewer.

## Skills and agents in this repo
- `/contract-check`: compare current changes with the contracts before committing.
- `/rubric-check <item>`: what full marks needs for a rubric item and how to show it in the demo.
- `/gate-check <1-4|demo>`: run a team gate's checklist.
- `/new-function <area> <name>`: scaffold a Cloud Run function in the agreed layout.
- Agents: `contract-reviewer` before opening a PR; `security-reviewer` before Gate 4.
