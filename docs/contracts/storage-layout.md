# Cloud Storage layout

Owner: member 2 (the models bucket: member 3). Change it only through the owner's PR.

## Buckets
All buckets are private, use uniform bucket-level access with public access prevention enforced, and live in `us-east1`, with Firestore and the functions: an Eventarc Cloud Storage trigger must be in its bucket's region, and a bucket's location can't change once it's created.

| Bucket | Object key | Written by | Read by | Triggers |
| --- | --- | --- | --- | --- |
| `<project-id>-media` | `<file_id>.<ext>` | The browser, through a signed URL from 2 `upload_init` | 2 `process_upload`, 3 tagging, users through signed URLs | Object finalized → 2 `process_upload` and 3 tagging (images) |
| `<project-id>-derived` | `thumbs/<file_id>.jpg` | 2 `process_upload` | Users through signed URLs | None |
| `<project-id>-derived` | `frames/<file_id>/<index>.jpg` | 2 `process_upload` | 3 tagging | None |
| `<project-id>-models` | `<model-name>/<version>/<file>` | 3 | 3 tagging | None |

Only the media bucket has triggers. Eventarc Cloud Storage triggers fire for every object in a bucket and can't filter by prefix, so anything a function writes goes to another bucket to avoid trigger loops.

Photos sent to `/search/by-file` and `/search/lost-pet` are never written to any bucket.

## Keys
- `<file_id>`: lowercase hex SHA-256 of the file's bytes.
- `<ext>`: from the content type: `jpg`, `png`, `webp`, `mp4`, `mov`.
- Thumbnails: JPEG, longest side 320 px, aspect ratio preserved, quality 80. Videos get a poster thumbnail from their first frame at the same key.
- Frames: one per 10 s of video. `<index>` is four digits counting from `0000` (0 s); `0001` is 10 s. A clip shorter than 10 s gives one frame.

## Accepted uploads
| Content type | Extension | Size limit |
| --- | --- | --- |
| `image/jpeg` | `jpg` | 20 MB |
| `image/png` | `png` | 20 MB |
| `image/webp` | `webp` | 20 MB |
| `video/mp4` | `mp4` | 200 MB |
| `video/quicktime` | `mov` | 200 MB |

HEIC isn't accepted: OpenCV can't read it.

## Signed URLs
- Upload: V4, `PUT`, valid 15 minutes, for `<file_id>.<ext>` in the media bucket. Signed headers the browser must send exactly: `Content-Type`, `x-goog-if-generation-match: 0` (so an existing object can't be overwritten), `x-goog-meta-uploaded-by` (Cognito `sub`), `x-goog-meta-original-filename` (URL-encoded), `x-goog-meta-is-public` (`true` or `false`, from the init request). A `412` response means the object already exists: treat it as a duplicate.
- Download: V4, `GET`, valid 60 minutes, created per response for originals and thumbnails.
- Functions sign without key files, through IAM signing; each signing function's service account needs Service Account Token Creator on itself.

## CORS
The media bucket allows `PUT` from the app's hosting origin and `http://localhost:5173`, with `Content-Type` and the `x-goog-*` headers above. Signed `GET` links used in `<img>` and `<video>` tags need no CORS.

## URL to file ID
`ecoguard_common.urls.file_id_from_url` (owner: member 2) is the only way any function turns a URL into a file ID. It accepts:
- `https://storage.googleapis.com/<bucket>/<key>` and `https://<bucket>.storage.googleapis.com/<key>`
- `gs://<bucket>/<key>`
- Signed or unsigned, URL-encoded or not

It drops the query string, URL-decodes the key, rejects buckets that aren't ours, and returns the 64-character file ID from the key: `<file_id>.<ext>` in the media bucket, `thumbs/<file_id>.jpg` or `frames/<file_id>/<index>.jpg` in the derived bucket. Any other URL raises `ValueError`, whose message never repeats the URL, so a signed URL can't reach the logs. It works for originals, thumbnails and frames alike, so the thumbnail lookup (2.2.2), bulk tagging (2.3.1) and delete (2.3.2) all resolve URLs the same way.
