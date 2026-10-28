# thumbnail_lookup

Owner: member 4 · Rubric: 2.2.2

## What it does
Turns a thumbnail URL, signed or not, into a signed URL of its full-size file. `ecoguard_common.urls.file_id_from_url` gives the file ID, and the original's bucket and key come from its `files` record, so JPEG, PNG and WebP originals all work and a video's poster gives the video. Returns `{"file_id": "...", "file_type": "image", "url": "<signed GET URL>"}`, or `404` when the URL isn't one of ours or the file is missing or being deleted.

## Trigger
HTTP through API Gateway: `POST /search/thumbnail` (see `docs/contracts/api-routes.md`).

## Service account
`fn-thumbnail-lookup@ecoguard-g21.iam.gserviceaccount.com`

| Role | On | Why |
| --- | --- | --- |
| `roles/datastore.viewer` | project | Reads `files` records; writes nothing |
| `roles/storage.objectViewer` | media bucket | Signed `GET` links to originals |
| `roles/iam.serviceAccountTokenCreator` | itself | Signs URLs through the IAM credentials API, with no key file |

Keep this table to what the code actually uses. Member 1 reviews it before Gate 4.

## Test
```bash
python -m pytest
```

## Deploy (a person runs this)
Cloud Functions gen2 names allow only lowercase letters, digits and hyphens, so the function is `thumbnail-lookup`.
```bash
cp -r ../../../shared/python/ecoguard_common .   # gitignored copy of the shared package
gcloud functions deploy thumbnail-lookup \
  --gen2 --runtime=python312 --region=us-east1 \
  --source=. --entry-point=handler --trigger-http \
  --no-allow-unauthenticated \
  --service-account=fn-thumbnail-lookup@ecoguard-g21.iam.gserviceaccount.com
```
