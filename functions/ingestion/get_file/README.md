# get_file

Owner: member 2 · Rubric: 3.1

## What it does
One or two sentences.

## Trigger
HTTP through API Gateway: `GET /files/{file_id}` (see `docs/contracts/api-routes.md`).
For an event function: the Eventarc event and source from `docs/contracts/events.md`.

## Service account
`fn-get-file@ecoguard-g21.iam.gserviceaccount.com`

| Role | On | Why |
| --- | --- | --- |
| `roles/datastore.user` | project | Reads and writes its own Firestore fields |

Keep this table to what the code actually uses. Member 1 reviews it before Gate 4.

## Test
```bash
python -m pytest
```

## Deploy (a person runs this)
```bash
cp -r ../../../shared/python/ecoguard_common .   # gitignored copy of the shared package
gcloud functions deploy get_file \
  --gen2 --runtime=python312 --region=us-east1 \
  --source=. --entry-point=handler --trigger-http \
  --no-allow-unauthenticated \
  --service-account=fn-get-file@ecoguard-g21.iam.gserviceaccount.com
```
