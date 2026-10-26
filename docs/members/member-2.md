# Member 2: ingestion and storage

Name and ID: Dylan (33879419)

You own 13 marks alone (2.1.1, 2.1.2, 2.3.2) and share 3.1 (upload UI) and 3.4 (delete controls). You also own the Firestore schema that tagging and every query depend on, the storage layout and the URL helper, so your work is on the team's critical path.

Finish the schema and contracts today: members 1, 3 and 4 build on them. Then get a real upload writing its record by Tuesday. That is Gate 2, and member 3 can't connect tagging to uploads until it passes.

## What you own
- `functions/ingestion/`: `upload_init`, `process_upload` (verify, record, thumbnail, frames), `get_file`, `delete_files`
- `docs/contracts/firestore-schema.md`, `docs/contracts/storage-layout.md`
- `shared/python/ecoguard_common/urls.py` (URL to file ID)
- `scripts/seed_data.py`
- `frontend/src/app/pages/upload/` and the delete action in the gallery

## Steps in order

| # | Step | Due | Done when | Watch out for |
| --- | --- | --- | --- | --- |
| 1 | Schema and key naming | Mon 26 | The schema lists every field, its type and its writer, and the team has read it | Tags stay a species-to-count map; store bucket and key, never URLs |
| 2 | Route and frame contracts | Mon 26 | JSON for `/uploads/init` and `/files/delete` is with member 1; the frame handoff is agreed with member 3 | Settle `frames-ready` before either of you writes code |
| 3 | Buckets and upload init | Tue 27 | The browser gets a signed PUT URL, or a duplicate response for a known hash | Signing from Cloud Run needs Service Account Token Creator on the function's own account; bucket CORS must allow PUT from the app and localhost; HEIC isn't readable by OpenCV |
| 4 | Process upload: verify and record | Tue 27 | Uploading a file creates its record within seconds | Recompute the SHA-256 and delete the object on a mismatch; carry the uploader from init as object metadata |
| 5 | Seed data script | Tue 27 | One command loads about 20 records with varied tags | Real schema and naming; mark seeds with `seed: true` |
| 6 | Thumbnails | Thu 29 | Every image gets `thumbs/<sha256>.jpg` and its record shows the key | Write to the derived bucket so nothing re-triggers |
| 7 | Video frames | Thu 29 | A 60 s clip gives frames at 0, 10, 20, 30, 40 and 50 s, plus a poster | Seek by time, don't read every frame; clips under 10 s give one frame; raise memory and timeout, since `/tmp` uses memory |
| 8 | Upload page | Fri 30 | Several files upload with progress; duplicates show a clear message | `fetch` has no upload progress, so PUT with `XMLHttpRequest` |
| 9 | Delete API | Fri 30 | A list of URLs removes originals, thumbnails, frames, sightings and records, with a result per URL | Objects first, record last, ignoring not-found, so a retry finishes a half-done delete |
| 10 | Delete in the gallery | Fri 30 | Selecting tiles and confirming removes them | Build against a plain list if the gallery isn't ready |
| 11 | Roles and edge tests | Sat 31 | Each function runs with only what it touches; edge cases pass | Same file twice, same file renamed, each format, a clip under 10 s, deleting a video, deleting twice, no token |
| 12 | Demo uploads, report parts | Sun 1 | Demo files went through the real pipeline; your user guide steps are written | Upload before the freeze so tags and thumbnails are real |

## Dependencies and conflicts

| With | Direction | What | Needed by | If it slips or clashes |
| --- | --- | --- | --- | --- |
| 1 | You need | Shared GCP project and AWS access | Mon 26 | Build in your own project meanwhile, with names in config |
| 3 | Shared | Frame handoff and per-frame maximum | Mon 26 | Two halves of video tagging that don't fit |
| 1, 3, 4 | They need | Schema, key naming, route contracts | Mon 26 | Field names guessed; integration breaks |
| 1 | You need | Gateway routes for init and delete passing the user's claims | Tue 27 | Test against the function URL with a fixed test user |
| 3, 4 | They need | Seed data script | Tue 27 | Queries and lost pet search can't be built |
| 3 | They need | First real upload creating a record (Gate 2) | Tue 27 | Tagging can't be connected; the Pipeline phase slips |
| 3 | Shared | Both write the same record | Wed 28 | A full overwrite wipes the other's fields; merge only |
| 3 | Shared | Query photos never reach the media bucket | Wed 28 | Search by file breaks the spec's privacy rule |
| 4 | They need | Thumbnail keys on records | Thu 29 | Broken gallery images; thumbnail lookup fails |
| 3 | They need | Video frames and `frames-ready` | Thu 29 | Videos never get tagged |
| 1 | You need | App shell and API client | Thu 29 | Build the upload page standalone and move it in on Saturday |
| 1 | You need | Notification trigger ignores deletes and non-tag writes | Fri 30 | Uploads, thumbnail writes or deletes email subscribers |
| 4 | Shared | URL helper used by delete and bulk tagging | Fri 30 | One API accepts signed URLs and the other 404s |
| 4 | You need | Gallery with tile selection | Fri 30 | Ship delete as a list view and plug it in later |
| 1 | You need | Review of your service accounts | Sat 31 | Over-broad roles exposed in the Q&A |
