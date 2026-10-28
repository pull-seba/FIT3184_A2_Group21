# tag_query

Owner: member 4 · Rubric: 2.2.1

## What it does
Finds files by tag. A `POST` body such as `{"feral pig": 1, "cane toad": 3}` gives each tag a minimum count, and a file must meet every one (AND). `["cat"]` means at least one cat, and `GET ?name=cat` is the one-species form. Optional `from` and `to` days (`YYYY-MM-DD`, Melbourne time, both inclusive) filter by upload time, which the chatbot uses for "yesterday". Returns `{"results": [FileSummary]}`, newest first, with fresh signed URLs.

## Trigger
HTTP through API Gateway: `POST /search/tags` and `GET /search/species` (see `docs/contracts/api-routes.md`). Both routes call this function, which tells them apart by method.

## Service account
`fn-tag-query@ecoguard-g21.iam.gserviceaccount.com`

| Role | On | Why |
| --- | --- | --- |
| `roles/datastore.viewer` | project | Reads `files` records; writes nothing |
| `roles/storage.objectViewer` | media bucket | Signed `GET` links to originals |
| `roles/storage.objectViewer` | derived bucket | Signed `GET` links to thumbnails |
| `roles/iam.serviceAccountTokenCreator` | itself | Signs URLs through the IAM credentials API, with no key file |

Keep this table to what the code actually uses. Member 1 reviews it before Gate 4.

## Test
```bash
python -m pytest
```

## Deploy (a person runs this)
Cloud Functions gen2 names allow only lowercase letters, digits and hyphens, so the function is `tag-query`.
```bash
cp -r ../../../shared/python/ecoguard_common .   # gitignored copy of the shared package
cp ../../../shared/tags.json ecoguard_common/    # the tag list tag_match reads
gcloud functions deploy tag-query \
  --gen2 --runtime=python312 --region=us-east1 \
  --source=. --entry-point=handler --trigger-http \
  --no-allow-unauthenticated \
  --service-account=fn-tag-query@ecoguard-g21.iam.gserviceaccount.com
```
