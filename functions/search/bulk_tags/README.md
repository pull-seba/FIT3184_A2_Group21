# bulk_tags

Owner: member 4 · Rubric: 2.3.1

## What it does
Adds or removes tags on every file in `urls`. `operation` 1 sets each tag's count to 1 where the file doesn't have it (an existing count stays) and adds the names to `manual_tags`, so re-tagging keeps them; 0 deletes the tags and takes them out of `manual_tags`, and removing a tag a file doesn't have is ignored. Tags are checked against `shared/tags.json` with `tag_match`. Returns one result per URL in request order: `updated`, or `not_found` when the URL isn't one of ours or the file is missing or being deleted. Writes go in Firestore batches of at most 500.

## Trigger
HTTP through API Gateway: `POST /tags/bulk` (see `docs/contracts/api-routes.md`). Answers the browser's CORS preflight (`OPTIONS`, no token) with `204`, as `infra/gateway/README.md` asks.

## Service account
`fn-bulk-tags@ecoguard-g21.iam.gserviceaccount.com`

| Role | On | Why |
| --- | --- | --- |
| `roles/datastore.user` | project | Reads each file's `status`; updates its `tags` and `manual_tags` |

Keep this table to what the code actually uses. Member 1 reviews it before Gate 4.

## Test
```bash
python -m pytest
```

## Deploy (a person runs this)
Cloud Functions gen2 names allow only lowercase letters, digits and hyphens, so the function is `bulk-tags`.
```bash
cp -r ../../../shared/python/ecoguard_common .   # gitignored copy of the shared package
cp ../../../shared/tags.json ecoguard_common/    # the tag list tag_match reads
gcloud functions deploy bulk-tags \
  --gen2 --runtime=python312 --region=us-east1 \
  --source=. --entry-point=handler --trigger-http \
  --no-allow-unauthenticated \
  --service-account=fn-bulk-tags@ecoguard-g21.iam.gserviceaccount.com
```
