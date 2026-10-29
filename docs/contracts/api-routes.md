# API routes

Owner of this file and of the gateway spec (`infra/gateway/openapi.yaml`): member 1. Each route's request and response are owned by the route's owner below; changes go through a PR to this file first, then the gateway spec, then the code. Keep `scripts/check-no-token.sh` in step with the route list.

## Every route
- Base URL: the API Gateway host, for example `https://ecoguard-<id>.ts.gateway.dev`.
- Header `Authorization: Bearer <Cognito ID token>`. The gateway rejects a missing or invalid token with `401` before any function runs. Send the ID token, not the access token: Cognito access tokens have no `aud` claim for the gateway to check.
- Functions read the caller from `X-Apigateway-Api-Userinfo` through `ecoguard_common.auth.get_user`, never from the request body.
- Bodies are JSON with `Content-Type: application/json`. Images inside JSON are base64, resized in the browser to about 1024 px first.

### Errors
```json
{ "error": { "code": "unknown_tag", "message": "Tag 'foxx' is not in the tag list" } }
```
| Status | When |
| --- | --- |
| 400 | Invalid input |
| 401 | No token or bad token (from the gateway) |
| 403 | The caller may not do this |
| 404 | No such file |
| 413 | Payload too large |
| 415 | Unsupported file type |
| 500 | Anything else; log it with the `file_id` |

### `FileSummary`: how every route returns a file
```json
{
  "file_id": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
  "file_type": "image",
  "url": "<signed GET URL of the original image or video>",
  "thumbnail_url": "<signed GET URL of the thumbnail or video poster>",
  "tags": { "fox": 2 },
  "uploaded_at": "2026-10-26T09:43:00Z"
}
```
Results lists are `{"results": [FileSummary, ...]}`, newest first unless a route says otherwise.

## Routes

| Method and path | Owner | Function | Rubric |
| --- | --- | --- | --- |
| `POST /uploads/init` | 2 | `ingestion/upload_init` | 2.1.1 |
| `GET /files/{file_id}` | 2 | `ingestion/get_file` | 3.1 |
| `POST /files/delete` | 2 | `ingestion/delete_files` | 2.3.2 |
| `POST /search/tags` | 4 | `search/tag_query` | 2.2.1 |
| `GET /search/species` | 4 | `search/tag_query` | 2.2.1 |
| `POST /search/thumbnail` | 4 | `search/thumbnail_lookup` | 2.2.2 |
| `POST /search/by-file` | 3 | `ml/search_by_file` | 2.2.3 |
| `POST /search/lost-pet` | 3 | `ml/lost_pet` | 2.2.4 |
| `POST /tags/bulk` | 4 | `search/bulk_tags` | 2.3.1 |
| `GET /notifications/subscriptions` | 1 | `notify/subscriptions` | 2.3.3 |
| `PUT /notifications/subscriptions` | 1 | `notify/subscriptions` | 2.3.3 |

### `POST /uploads/init` (member 2)
Request:
```json
{ "sha256": "<64 hex>", "filename": "fox-cam3.jpg", "content_type": "image/jpeg", "size_bytes": 2483021, "is_public": true }
```
Response when the file already exists (no upload happens and no trigger fires):
```json
{ "status": "duplicate", "file": { "...": "FileSummary" } }
```
Response when the browser should upload:
```json
{ "status": "upload", "file_id": "<64 hex>", "upload_url": "<signed PUT URL>", "headers": { "Content-Type": "image/jpeg", "x-goog-if-generation-match": "0", "x-goog-meta-uploaded-by": "<sub>", "x-goog-meta-original-filename": "fox-cam3.jpg" }, "expires_at": "2026-10-26T10:00:00Z" }
```
Errors: `400` bad hash, `413` over the size limit, `415` type not accepted.

### `GET /files/{file_id}` (member 2)
Returns a `FileSummary` plus `"pipeline": {"thumbnail": "done", "tagging": "done"}` so the upload page can show processing progress. `404` if missing or deleting.

### `POST /files/delete` (member 2)
```json
{ "urls": ["<original, thumbnail or frame URL>", "..."] }
```
Response, one result per URL in the same order:
```json
{ "results": [ { "url": "...", "file_id": "<64 hex>", "status": "deleted" }, { "url": "...", "file_id": null, "status": "not_found" } ] }
```
`status` is `deleted`, `not_found` or `error` (with `detail`). Deleting removes the original, thumbnail, frames, sightings and the `files` document.

### `POST /search/tags` (member 4)
Body is the tag query from the spec: tag name to minimum count, combined with AND.
```json
{ "feral pig": 1, "cane toad": 3 }
```
Also accepted: a list of tag names, each meaning a minimum of 1 (`["cat"]`). Optional query parameters `from` and `to` (dates, `YYYY-MM-DD`, Australia/Melbourne) filter by `uploaded_at`, which the chatbot uses for questions like "yesterday". Response: `{"results": [FileSummary]}`. An unknown tag gives `400 unknown_tag`; a count below 1 gives `400`.

### `GET /search/species?name=cat` (member 4)
Every file with at least one of that species. Same response and date parameters as `/search/tags`.

### `POST /search/thumbnail` (member 4)
```json
{ "thumbnail_url": "<thumbnail URL, signed or not>" }
```
Response: `{"file_id": "...", "file_type": "image", "url": "<signed GET URL of the full-size file>"}`. For a video poster, `url` is the video. `404` if no such file.

### `POST /search/by-file` (member 3)
```json
{ "file_base64": "<base64>", "content_type": "image/jpeg" }
```
Response: `{"detected_tags": {"fox": 1}, "results": [FileSummary]}`. Matches use the same AND rule as `/search/tags`. The query file is never stored or indexed.

### `POST /search/lost-pet` (member 3)
```json
{ "image_base64": "<optional base64 photo>", "species": "cat", "colour": "ginger", "breed": null, "since_days": 30 }
```
At least `image_base64` or `species` is required. Only public sightings within `since_days` count. Response: `{"results": [FileSummary + {"score": 0.91, "sighting_id": "<file_id>_0"}]}`, best score first when a photo was given, newest first otherwise. The query photo is never stored or indexed.

### `POST /tags/bulk` (member 4)
```json
{ "urls": ["<file URL>", "..."], "tags": ["fox", "cat"], "operation": 1 }
```
`operation` 1 adds (count 1 if the tag is absent), 0 removes. Removing a tag a file doesn't have is ignored. Unknown tags give `400 unknown_tag`. Response: one result per URL, as in `/files/delete`, with `status` `updated` or `not_found`.

### `GET` and `PUT /notifications/subscriptions` (member 1)
`PUT` body `{"tags": ["fox", "cane toad"]}` replaces the caller's alert tags; `GET` returns them. Tags are the caller's SNS email subscription to `ecoguard-tag-alerts`, filtered on `tags`; the function reaches AWS without keys (`docs/decisions.md`).

## Chatbot
The Lex fulfilment Lambda (member 4) calls `/search/tags`, `/search/species` and `/search/lost-pet` through the gateway like any other client, with a Cognito ID token (see `docs/decisions.md` for how it gets one). It returns each result as a clickable link.
