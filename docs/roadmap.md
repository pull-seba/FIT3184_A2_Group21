# Roadmap

Contracts first, then what produces data (upload, schema, tagging) before what consumes it (queries, notifications, UI). Consumers build against seed data until the real pipeline is ready. No one starts the next phase until the gate above it passes. Run a gate's checklist with `/gate-check <n>`.

## Phases

| Phase | Dates | Member 1: identity | Member 2: ingestion | Member 3: ML | Member 4: search and chatbot |
| --- | --- | --- | --- | --- | --- |
| Contracts | by Mon 26 Oct | Shared accounts; gateway spec with every route stubbed; app framework | Firestore schema; storage key naming; route JSON for upload and delete | Tag list and model label mapping | Route JSON for search and tags |
| Foundations | to Tue 27 Oct | Cognito pool and client; gateway JWT check; app shell and guard; shared API client | Buckets; signed URL and dedup; record writes; seed data script | Detector container; `config/model`; label mapping; test on a sample set | Queries on seed data; thumbnail lookup; results gallery; Lex intents and slots |
| Pipeline | Wed 28 to Fri 30 Oct | Firestore trigger; Pub/Sub to SNS; Lex token path; notification page | Thumbnails and frames; delete API; upload page; delete in the gallery | Tagging on upload; search by file; lost pet search; their pages on the gallery | Queries on real data; bulk tag API; Lex fulfilment; search page and chat widget |
| Integrate | Sat 31 Oct | Every page inside the shell; review every role | Least-privilege roles; edge tests | Least-privilege roles; edge tests | Least-privilege roles; edge tests |
| Demo and reports | Sun 1 to Mon 2 Nov | Demo checklist, diagram, reports | Demo uploads; user guide steps | Demo checklist, reports | Demo checklist, reports |

## Working rules
- **Contracts before code.** The schema, tag list, route list and JSON shapes settle most High rows in `docs/crossovers.md` before anyone writes a function.
- **One owner creates each shared file first.** Gateway spec and app shell: member 1. Schema: member 2. Tag list: member 3. Gallery: member 4. Everyone else adds to them through pull requests.
- **Consumers never wait.** Member 2's seed data and member 1's stubbed routes let members 3 and 4 build before real uploads flow.
- **Integrate in pipeline order.** Upload, then thumbnails and tags, then queries, notifications and delete, then the UI.
- **Freeze a day early.** No new features after Saturday.

## Gate checklists

### Gate 1: contracts merged (end of Mon 26 Oct)
- [ ] `docs/contracts/` reviewed by all four members and merged to `main`
- [ ] `shared/tags.json` confirmed by member 3 and merged
- [ ] `infra/gateway/openapi.yaml` has every route in `docs/contracts/api-routes.md`, stubbed (member 1)
- [ ] Shared GCP project and AWS account; every member can deploy
- [ ] `.github/CODEOWNERS` filled in and branch protection on `main`
- [ ] Every Proposed item due Mon 26 Oct in `docs/decisions.md` confirmed or changed

### Gate 2: first real record (end of Tue 27 Oct)
- [ ] A real image upload creates `files/<sha256>` with the base fields (member 2)
- [ ] Uploading the same file again returns `duplicate` and adds no object (member 2)
- [ ] `scripts/check-no-token.sh` passes for every route (member 1)
- [ ] Seed data is loaded and the tag query returns seeded files (members 2 and 4)
- [ ] The detector runs on the sample set from `config/model` (member 3)

### Gate 3: end to end on real files (end of Fri 30 Oct)
- [ ] An image upload gets its thumbnail and tags within a minute
- [ ] A 60 s video gives 6 frames, a poster thumbnail and per-frame-maximum counts
- [ ] `{"fox": 2}` and `{"feral pig": 1, "cane toad": 3}` return the right files with working URLs
- [ ] Thumbnail URLs resolve to full-size URLs for JPEG, PNG and WebP originals
- [ ] Search by file returns matches and leaves storage and Firestore unchanged
- [ ] Lost pet search by photo ranks the right animal first; by description it respects the date window
- [ ] Bulk add and remove work across three files; removing an absent tag is ignored
- [ ] A subscriber gets an email for a monitored tag and none for others
- [ ] Lex answers "show me all photos of foxes spotted yesterday" and "help me find a lost ginger cat" with clickable links
- [ ] Delete removes the original, thumbnail, frames, sightings and record

### Gate 4: feature freeze (end of Sat 31 Oct)
- [ ] Every page sits inside the app shell behind sign-in; signed-out visits redirect
- [ ] Member 1 has reviewed each function's service account or role: no wildcards, no `allUsers`
- [ ] `scripts/check-no-token.sh` passes
- [ ] The `security-reviewer` agent finds no credentials in the repo or the frontend bundle
- [ ] Demo data uploaded through the real pipeline, not seeded
- [ ] Every member can explain the architecture, the three cross-cloud links, their own functions, AND logic, per-frame maximum and deduplication

### Demo: submission (23:55 Mon 2 Nov)
- [ ] Architecture diagram with official AWS and Google Cloud icons
- [ ] 3-minute architecture talk shared across all four members
- [ ] Team report: at most 1000 words, contribution table, user guide, repo link; PDF in 12 pt Arial, Helvetica or Times New Roman
- [ ] Repo private and shared with the whole teaching team
- [ ] Each member's individual report submitted
