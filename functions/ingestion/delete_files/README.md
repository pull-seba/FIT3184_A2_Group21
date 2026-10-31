# delete_files

Owner: member 2 · Rubric: 2.3.2

## What it does
Deletes files by URL, along with everything made from them. Any URL of a file works: its original, thumbnail or one of its frames, signed or not, through `ecoguard_common.urls.file_id_from_url`. Only the person who uploaded a file can delete it.

For each file, in this order:
1. Sets `status: "deleting"` on its record. Queries and `upload_init` only match `"active"`, so the file leaves every result at once, even if a later step fails.
2. Deletes `<file_id>.<ext>` from the media bucket, and `thumbs/<file_id>.jpg` and everything under `frames/<file_id>/` from the derived bucket. They're found by listing each prefix rather than read from the record, so objects an interrupted `process_upload` saved before writing their keys go too.
3. Deletes every `sightings` document whose `file_id` matches, so the file stops showing in lost pet search.
4. Deletes the `files` document, last, so a retry can still find the file.

Anything already gone counts as deleted, so calling again finishes a delete that stopped halfway. Files are deleted 8 at a time: the gateway gives up on a call after 15 s.

| `status` | When |
| --- | --- |
| `deleted` | Everything above is gone. A file sent twice in one request (say its original and its thumbnail) is deleted once and both URLs get `deleted` |
| `not_found` | The URL isn't one of our files (`file_id: null`), or the file has no record: never uploaded, or already deleted |
| `error` | `detail` says why: `You can only delete files you uploaded`, or `Could not delete it. Try again.` for anything unexpected, which is logged with the `file_id`. The rest of the list carries on |

A file whose record doesn't name the caller as `uploaded_by` is refused, which includes seeded records (`uploaded_by: "seed-data"`; remove them with `scripts/seed_data.py --remove`) and a record tagging merged before the upload finished.

Logs carry the `file_id`, never the URL, since URLs may be signed.

## Trigger
HTTP through API Gateway: `POST /files/delete` (see `docs/contracts/api-routes.md`). Answers the browser's CORS preflight (`OPTIONS`, no token) with `204`, as `infra/gateway/README.md` asks.

## Service account
`fn-delete-files@ecoguard-g21.iam.gserviceaccount.com`, created and granted by `infra/gcp/ingestion.sh`.

| Role | On | Why |
| --- | --- | --- |
| `roles/datastore.user` | project | Reads the record to check the uploader, marks it `deleting`, deletes it and queries and deletes its `sightings` |
| `roles/storage.objectUser` | media bucket | Lists and deletes the original (the narrowest predefined role with delete) |
| `roles/storage.objectUser` | derived bucket | Lists and deletes the thumbnail and frames |

The gateway's account, `ecoguard-gateway@ecoguard-g21.iam.gserviceaccount.com`, holds `roles/run.invoker` on this function, granted by `ingestion.sh` once it's deployed.

Keep this table to what the code actually uses. Member 1 reviews it before Gate 4.

## Test
```bash
python -m pytest
```

## Deploy (a person runs this)
Cloud Functions gen2 names allow only lowercase letters, digits and hyphens, so the function is `delete-files`, the name the gateway calls.
```bash
cp -r ../../../shared/python/ecoguard_common .   # gitignored copy of the shared package
gcloud functions deploy delete-files \
  --gen2 --runtime=python312 --region=us-east1 \
  --source=. --entry-point=handler --trigger-http \
  --no-allow-unauthenticated \
  --service-account=fn-delete-files@ecoguard-g21.iam.gserviceaccount.com
```
Run `infra/gcp/ingestion.sh` before the first deploy, for the service account and its roles, and again after it, for the gateway's Invoker grant.
