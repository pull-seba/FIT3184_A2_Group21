# Firestore schema

Owner: member 2. Change it only through a PR from member 2 that requests every affected member as a reviewer.

## Rules
- `file_id` and every `files` document ID is the lowercase hex SHA-256 of the file's bytes (64 characters).
- Write only the fields your function owns, using `set(data, merge=True)` or `update()`. Never call `set()` without `merge=True` on a document that may exist.
- Every `*_at` field is written with `firestore.SERVER_TIMESTAMP`, except a seeded record's `uploaded_at` (see `seed`).
- Store bucket names, object keys and each object's permanent `gs://` address. Never store a signed URL: it expires. Sign one when building a response.
- Tag names must exist in `shared/tags.json`. Tag names can contain spaces ("feral pig"), so build field paths with `firestore.FieldPath("tags", name)`, never by string concatenation.

## `files/{file_id}`: one document per uploaded image or video

| Field | Type | Written by | Notes |
| --- | --- | --- | --- |
| `file_id` | string | 2 `process_upload` | Same as the document ID |
| `file_type` | `"image"` or `"video"` | 2 `process_upload` | From the content type |
| `content_type` | string | 2 `process_upload` | One of the accepted types in `storage-layout.md` |
| `original_filename` | string | 2 `process_upload` | From the upload's object metadata; display only |
| `size_bytes` | integer | 2 `process_upload` | |
| `media_bucket` | string | 2 `process_upload` | |
| `media_key` | string | 2 `process_upload` | `<file_id>.<ext>` |
| `media_uri` | string | 2 `process_upload` | `gs://<media_bucket>/<media_key>`: the original's permanent storage address, which the spec calls its storage URL. Browsers can't open it; sign a URL per response |
| `thumbnail_key` | string | 2 `process_upload` | `thumbs/<file_id>.jpg` in the derived bucket; videos get a poster thumbnail from their first frame |
| `thumbnail_uri` | string | 2 `process_upload` | `gs://<project-id>-derived/<thumbnail_key>`, written with `thumbnail_key` |
| `frame_keys` | array of strings | 2 `process_upload` | Videos only: `frames/<file_id>/<index>.jpg`, one per 10 s |
| `duration_s` | number | 2 `process_upload` | Videos only |
| `uploaded_by` | string | 2 `process_upload` | Cognito `sub` of the uploader |
| `uploaded_at` | timestamp | 2 `process_upload` | |
| `is_public` | boolean | 2 `process_upload` | Whether the file counts as a public sighting for lost pet search. Read from the object's `is-public` metadata, which `upload_init` signs from the request; default `true` |
| `status` | `"active"` or `"deleting"` | 2 `process_upload`, `delete_files` | `process_upload` writes `"active"` in the same merge as `media_key`, once the SHA-256 is verified. Queries and `upload_init` match only `"active"`, so a document tagging wrote first, which has no `status`, never matches |
| `pipeline.thumbnail` | `"done"` or `"failed"` | 2 `process_upload` | Each pipeline step writes only its own key |
| `pipeline.frames` | `"done"` or `"failed"` | 2 `process_upload` | Videos only |
| `pipeline.tagging` | `"done"` or `"failed"` | 3 tagging | |
| `tags` | map of tag name to integer count | 3 tagging; 4 `bulk_tags` | Counts are at least 1. For videos, the maximum count in any one frame |
| `manual_tags` | array of strings | 4 `bulk_tags` | Tags a person added by hand. Re-tagging keeps them |
| `model_version` | string | 3 tagging | The config version that produced the automatic tags |
| `tagged_at` | timestamp | 3 tagging | |
| `seed` | boolean | 2 `seed_data.py` | `true` only on seeded test records, so they are easy to wipe. `seed_data.py` writes the rest of a seeded record too, following this table, with `uploaded_at` in the past so date filters such as "yesterday" can be tested |

### Who writes `tags`
- Tagging (3) runs in a transaction: it writes the detected tags, then puts back every tag in `manual_tags` with its existing count.
- Bulk add (4) sets `tags.<name>` to 1 only if absent and adds the name to `manual_tags` with `ArrayUnion`.
- Bulk remove (4) deletes `tags.<name>` with `DELETE_FIELD` and removes the name from `manual_tags`. Removing a tag that isn't there is ignored.
- Known limit: re-tagging after a model change can bring back an automatic tag someone removed by hand.

## `sightings/{file_id}_{n}`: one document per cat or dog detected, for lost pet search

Firestore vector search needs one vector per document, so each detected pet gets its own document rather than an array on `files`.

| Field | Type | Written by | Notes |
| --- | --- | --- | --- |
| `file_id` | string | 3 tagging | The file the pet appears in |
| `species` | `"cat"` or `"dog"` | 3 tagging | From `lost_pet_species` in `shared/tags.json` |
| `colour` | string or null | 3 tagging | For example "ginger", "black", "tabby" |
| `breed` | string or null | 3 tagging | When the model provides one |
| `embedding` | Firestore `Vector` | 3 tagging | Image embedding of the pet's crop: 1408 numbers from Vertex AI `multimodalembedding@001` |
| `embedding_model` | string | 3 tagging | The model that made `embedding`. Vectors from different models can't be compared, so a model change means re-embedding |
| `bbox` | array of 4 numbers | 3 tagging | `[x, y, width, height]`, each 0 to 1 |
| `frame_index` | integer or null | 3 tagging | Videos only |
| `uploaded_at` | timestamp | 3 tagging | Copied from the file, so searches can filter by date |
| `is_public` | boolean | 3 tagging | Copied from the file |
| `created_at` | timestamp | 3 tagging | |

`delete_files` (2) deletes every sighting whose `file_id` matches a deleted file.

## `config/model`: the active models, so models change without code changes (rubric 2.1.3)

Owner: member 3. Holds the detector name, weights location and version, confidence threshold, any chained classifier, and the embedding model. The tagging service reads it on start-up and re-reads it every few minutes.

The source of truth is `functions/ml/config/model.json`; `functions/ml/config/push_model_config.py` writes it here.

| Field | Type | Notes |
| --- | --- | --- |
| `version` | string | Copied to `files.model_version` on every tagged file |
| `detector` | string | `rekognition` |
| `detector_region` | string | AWS region for the detector, `us-east-1` |
| `request_min_confidence` | number | Lowest confidence asked for from the detector; per-tag thresholds are applied after |
| `thresholds` | map of tag name to number | Per-tag minimum confidence (0-100), from the bake-off in `tools/testset` |
| `default_threshold` | number | For a tag missing from `thresholds` |
| `box_min_confidence` | number | A box counts towards a tag's count once its label passes the threshold and the box is at least this confident |
| `borrow_boxes` | boolean | When a tag has no boxes of its own, count the boxes on another animal label in the photo |
| `label_map_version` | integer | The `shared/tags.json` version these thresholds were chosen for |
| `chained_classifier` | string or null | None for now |
| `embedding_model` | string | `multimodalembedding@001` |
| `embedding_dimension` | integer | 1408 (Firestore vector indexes allow up to 2048) |
| `embedding_location` | string | Vertex AI region for the embedding call |
| `updated_at` | timestamp | Set by the push script |

## `subscriptions/{user_sub}`: tag alert preferences

Owner: member 1. Fields: `email`, `tags` (array of tag names), `sns_subscription_arn`, `updated_at`.

## Indexes
Defined in `infra/gcp/firestore.indexes.json`. Single-field indexes on `tags.<name>` are automatic. The vector index on `sightings.embedding`, with `species` and `is_public` as pre-filters, belongs to member 3.
