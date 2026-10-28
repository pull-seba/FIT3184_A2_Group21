# Events and messages

Every handler here is idempotent: Eventarc and Pub/Sub deliver at least once, so the same event can arrive twice.

## Eventarc triggers

| Source | Event | Handler | Owner | Does |
| --- | --- | --- | --- | --- |
| Media bucket | `google.cloud.storage.object.v1.finalized` | `ingestion/process_upload` | 2 | Verifies the SHA-256, writes the base `files` record, makes the thumbnail; for videos also extracts frames and publishes `frames-ready` |
| Media bucket | `google.cloud.storage.object.v1.finalized` | ML tagging service | 3 | Tags images. Returns at once for videos, which it tags from `frames-ready` |
| Firestore `files/{file_id}` | `google.cloud.firestore.document.v1.updated` | `notify/on_tags_changed` | 1 | Publishes `tag-changes` when the `tags` map gained a tag or a higher count. Ignores every other write and every delete |

`process_upload` and tagging fire on the same upload in either order. Neither waits for the other: tagging can merge its fields before the base record exists, and the thumbnail key is derived from the file ID.

## Pub/Sub topics

### `frames-ready`
Publisher: 2 `process_upload`. Subscriber: 3 tagging.
```json
{ "file_id": "<64 hex>", "bucket": "<project-id>-derived", "frame_keys": ["frames/<file_id>/0000.jpg", "frames/<file_id>/0001.jpg"], "duration_s": 14.2 }
```
Tagging runs the detector on every frame and records, per tag, the highest count in any one frame.

### `tag-changes`
Publisher: 1 `notify/on_tags_changed`. Subscriber: push subscription to the AWS notify Lambda, with an OIDC token.
```json
{ "file_id": "<64 hex>", "file_type": "image", "tags": { "fox": 2 }, "added": ["fox"], "uploaded_at": "2026-10-26T09:43:00Z" }
```
`added` lists tags that are new or whose count went up. A new upload counts as an update from no tags. The message carries no URLs, because signed URLs expire; the email links to the app.

## SNS
Topic `ecoguard-tag-alerts` (member 1). The AWS Lambda verifies the Google OIDC token on each push, then publishes with message attribute `tags` (`String.Array`) set to `added`. Each email subscription has a filter policy such as `{"tags": ["fox", "cane toad"]}`, so people only get alerts for tags they chose.
