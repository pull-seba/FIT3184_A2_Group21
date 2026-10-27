# upload_init

Owner: member 2 · Rubric: 2.1.1

## What it does
Checks a file the browser wants to upload. If its SHA-256 matches a verified, active record, it answers `duplicate` with that file's `FileSummary` and no upload happens. Otherwise it returns a 15-minute signed `PUT` URL for `<sha256>.<ext>` in the media bucket, plus the exact headers the browser must send. It writes nothing; `process_upload` creates the record once the file arrives.

## Trigger
HTTP through API Gateway: `POST /uploads/init` (see `docs/contracts/api-routes.md`).

## Service account
`fn-upload-init@ecoguard-g21.iam.gserviceaccount.com`, created and granted by `infra/gcp/ingestion.sh`.

| Role | On | Why |
| --- | --- | --- |
| `roles/datastore.viewer` | project | Reads `files/<sha256>` for the duplicate check; writes nothing |
| `roles/storage.objectCreator` | media bucket | A signed URL acts as its signer, so the browser's `PUT` needs create permission |
| `roles/storage.objectViewer` | media bucket | Signed `GET` link to a duplicate's original |
| `roles/storage.objectViewer` | derived bucket | Signed `GET` link to a duplicate's thumbnail |
| `roles/iam.serviceAccountTokenCreator` | itself | Signs URLs through the IAM credentials API, with no key file |

Keep this table to what the code actually uses. Member 1 reviews it before Gate 4.

## Configuration
| Variable | Default |
| --- | --- |
| `MEDIA_BUCKET` | `ecoguard-g21-media` |
| `DERIVED_BUCKET` | `ecoguard-g21-derived` |

## Test
```bash
python -m pytest
```

## Deploy (a person runs this)
Cloud Functions gen2 names allow only lowercase letters, digits and hyphens, so the function is `upload-init`.
```bash
cp -r ../../../shared/python/ecoguard_common .   # gitignored copy of the shared package
gcloud functions deploy upload-init \
  --gen2 --runtime=python312 --region=us-east1 \
  --source=. --entry-point=handler --trigger-http \
  --no-allow-unauthenticated \
  --service-account=fn-upload-init@ecoguard-g21.iam.gserviceaccount.com
```
