# get_file

Owner: member 2 · Rubric: 3.1

## What it does
Returns one file's `FileSummary` plus its record's `pipeline`, so the upload page can show each upload's progress: the thumbnail appearing, then its tags.

```json
{ "file_id": "<64 hex>", "file_type": "image", "url": "<signed GET>", "thumbnail_url": "<signed GET or null>",
  "tags": { "fox": 2 }, "uploaded_at": "2026-10-27T09:43:00Z", "pipeline": { "thumbnail": "done", "tagging": "done" } }
```

- Each step adds its own key to `pipeline` when it finishes, `"done"` or `"failed"`: `thumbnail` and, for videos, `frames` from `process_upload`, and `tagging` from member 3's tagging. A missing key means the step hasn't finished.
- `thumbnail_url` is `null` until the thumbnail exists, and `tags` is `{}` until tagging finishes.
- Signed URLs are V4 `GET`, valid 60 minutes, signed through IAM with no key file (`storage-layout.md`).
- `404` unless the record is `active`: no record yet (keep polling until `process_upload` has verified the upload), one tagging wrote before that, or a file being deleted.
- Any signed-in user can read any file, as search already shows every file to everyone. Only deleting is limited to the uploader.

Reads only; it never writes.

## Trigger
HTTP through API Gateway: `GET /files/{file_id}` (see `docs/contracts/api-routes.md`). The gateway passes `{file_id}` as the query parameter `?file_id=`. Answers the browser's CORS preflight (`OPTIONS`, no token) with `204`, as `infra/gateway/README.md` asks.

## Service account
`fn-get-file@ecoguard-g21.iam.gserviceaccount.com`, created and granted by `infra/gcp/ingestion.sh`.

| Role | On | Why |
| --- | --- | --- |
| `roles/datastore.viewer` | project | Reads `files/<sha256>` |
| `roles/storage.objectViewer` | media bucket | A signed URL acts with its signer's permissions, so signing a GET for the original needs read access |
| `roles/storage.objectViewer` | derived bucket | The same, for the thumbnail |
| `roles/iam.serviceAccountTokenCreator` | its own service account | Signing without a key file goes through the IAM credentials API |

The gateway's account, `ecoguard-gateway@ecoguard-g21.iam.gserviceaccount.com`, holds `roles/run.invoker` on this function, granted by `ingestion.sh` once it's deployed.

Keep this table to what the code actually uses. Member 1 reviews it before Gate 4.

## Test
```bash
python -m pytest
```

## Deploy (a person runs this)
Cloud Functions gen2 names allow only lowercase letters, digits and hyphens, so the function is `get-file`, the name the gateway calls.
```bash
cp -r ../../../shared/python/ecoguard_common .   # gitignored copy of the shared package
gcloud functions deploy get-file \
  --gen2 --runtime=python312 --region=us-east1 \
  --source=. --entry-point=handler --trigger-http \
  --no-allow-unauthenticated \
  --service-account=fn-get-file@ecoguard-g21.iam.gserviceaccount.com
```
Run `infra/gcp/ingestion.sh` before the first deploy, for the service account and its roles, and again after it, for the gateway's Invoker grant.
