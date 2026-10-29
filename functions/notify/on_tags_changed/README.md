# on_tags_changed

Owner: member 1 · Rubric: 2.3.3

## What it does
When a file's `tags` map gains a tag or a higher count, publishes one message to the `tag-changes` topic. The AWS notify Lambda turns it into an SNS email for people subscribed to those tags. Every other write (thumbnails, pipeline status, tag removals) and every delete is ignored.

Message, as in `docs/contracts/events.md`:
```json
{ "file_id": "<64 hex>", "file_type": "image", "tags": { "fox": 2 }, "added": ["fox"], "uploaded_at": "2026-10-26T09:43:00Z" }
```
`file_type` and `uploaded_at` are `null` if tagging finished before `process_upload` wrote the base record.

## Trigger
Firestore `files/{file_id}`, event `google.cloud.firestore.document.v1.written`.

`events.md` says `updated`, but tagging can create the document before `process_upload` does, and a create only fires `created`. `written` covers both, and the code ignores deletes. (Contract change proposed.)

Idempotency: the handler reads only the event, so a repeated event gives the same message. A repeat can still send a second email; deduplicating would need a new Firestore collection, which isn't in the schema.

## Service account
`fn-on-tags-changed@ecoguard-g21.iam.gserviceaccount.com`

| Role | On | Why |
| --- | --- | --- |
| `roles/pubsub.publisher` | topic `tag-changes` | Publishes the message |
| `roles/eventarc.eventReceiver` | project | Receives the Firestore event |

It reads nothing from Firestore: the event carries the old and new document.

## Test
```bash
python -m pytest
```

## Deploy
```bash
gcloud pubsub topics create tag-changes

gcloud iam service-accounts create fn-on-tags-changed

gcloud pubsub topics add-iam-policy-binding tag-changes \
  --member=serviceAccount:fn-on-tags-changed@ecoguard-g21.iam.gserviceaccount.com \
  --role=roles/pubsub.publisher

gcloud projects add-iam-policy-binding ecoguard-g21 \
  --member=serviceAccount:fn-on-tags-changed@ecoguard-g21.iam.gserviceaccount.com \
  --role=roles/eventarc.eventReceiver

cp -r ../../../shared/python/ecoguard_common .   # gitignored copy of the shared package
gcloud functions deploy on-tags-changed \
  --gen2 --runtime=python312 --region=us-east1 \
  --source=. --entry-point=handler \
  --trigger-event-filters=type=google.cloud.firestore.document.v1.written \
  --trigger-event-filters=database='(default)' \
  --trigger-event-filters-path-pattern=document='files/{file_id}' \
  --trigger-location=us-east1 \
  --service-account=fn-on-tags-changed@ecoguard-g21.iam.gserviceaccount.com
```
