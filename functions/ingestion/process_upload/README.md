# process_upload

Owner: member 2 · Rubric: 2.1.1 (2.1.2 adds thumbnails and frames here)

## What it does
Runs when a file lands in the media bucket. It streams the object, recomputes its SHA-256 and checks it matches the key, then merges the base `files/<sha256>` record with `status: "active"`. From then on `upload_init` treats the same bytes as a duplicate.

An object that isn't a valid upload is deleted and gets no record:

| Reason (in the log) | When |
| --- | --- |
| `bad_key` | The key isn't `<sha256>.<ext>` |
| `bad_type` | The content type isn't accepted or doesn't match the extension |
| `too_large` | The stored size is over the type's limit: `upload_init` only saw the size the browser claimed |
| `no_uploader` | No `uploaded-by` metadata, which every `upload_init` URL signs in |
| `hash_mismatch` | The bytes don't hash to the key |
| `duplicate` | The same bytes are already recorded under another extension (two uploads at once) |

Idempotent: a repeat event for a file that already has its record does nothing, so `uploaded_at` keeps its first value.

## Trigger
Eventarc `google.cloud.storage.object.v1.finalized` on `ecoguard-g21-media` (see `docs/contracts/events.md`). Deployed with `--retry`: an unexpected error is raised, so Eventarc delivers the event again. Rejections return normally and aren't retried.

## Service account
`fn-process-upload@ecoguard-g21.iam.gserviceaccount.com`, created and granted by `infra/gcp/ingestion.sh`. It is also the trigger's service account, which Eventarc uses to call the function.

| Role | On | Why |
| --- | --- | --- |
| `roles/datastore.user` | project | Reads `files/<sha256>` and merges the base record |
| `roles/storage.objectUser` | media bucket | Reads each new object to hash it, and deletes rejected ones (the narrowest predefined role with delete) |
| `roles/eventarc.eventReceiver` | project | Receives events as the trigger's service account |
| `roles/run.invoker` | the `process-upload` service | Lets the trigger call the function, which allows no unauthenticated calls |

The trigger also needs the Cloud Storage service agent to hold `roles/pubsub.publisher` on the project; `ingestion.sh` grants it. That one grant covers every storage trigger in the project, including member 3's tagging.

Keep this table to what the code actually uses. Member 1 reviews it before Gate 4.

## Test
```bash
python -m pytest
```

## Deploy (a person runs this)
Cloud Functions gen2 names allow only lowercase letters, digits and hyphens, so the function is `process-upload`.
```bash
cp -r ../../../shared/python/ecoguard_common .   # gitignored copy of the shared package
gcloud functions deploy process-upload \
  --gen2 --runtime=python312 --region=us-east1 \
  --source=. --entry-point=handler \
  --trigger-event-filters="type=google.cloud.storage.object.v1.finalized" \
  --trigger-event-filters="bucket=ecoguard-g21-media" \
  --trigger-service-account=fn-process-upload@ecoguard-g21.iam.gserviceaccount.com \
  --retry --no-allow-unauthenticated \
  --service-account=fn-process-upload@ecoguard-g21.iam.gserviceaccount.com
```
After the first deploy, re-run `infra/gcp/ingestion.sh`: the `run.invoker` grant needs the service to exist.
