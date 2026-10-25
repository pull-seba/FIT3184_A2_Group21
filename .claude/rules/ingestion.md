---
paths:
  - "functions/ingestion/**"
  - "scripts/seed_data.py"
  - "shared/python/ecoguard_common/urls.py"
---

# Ingestion and storage (member 2; rubric 2.1.1, 2.1.2, 2.3.2)

- `upload_init`: look up `files/<sha256>` before signing anything. A known hash returns `duplicate` and no URL, so no trigger ever fires for a duplicate. Sign with the exact headers in `docs/contracts/storage-layout.md`, including `x-goog-if-generation-match: 0`.
- Deduplication is by content hash only, never by file name or size (that is the rubric's 50% case).
- `process_upload`: stream the object, recompute its SHA-256 and compare with the key. On a mismatch, delete the object and write nothing.
- Images: decode with OpenCV, resize so the longest side is 320 px using `cv2.INTER_AREA`, keep the aspect ratio, encode JPEG at quality 80, write to the derived bucket, then merge `thumbnail_key` and `pipeline.thumbnail`.
- Videos: download to `/tmp`, open with `cv2.VideoCapture`, seek with `CAP_PROP_POS_MSEC` to 0, 10000, 20000 ms and so on, reading one frame at each; never decode every frame. A clip under 10 s still gives one frame. Write the frames and a poster thumbnail, merge `frame_keys`, `duration_s` and `pipeline.frames`, publish `frames-ready`, then delete the `/tmp` file.
- `delete_files`: resolve each URL with `ecoguard_common.urls.file_id_from_url`; set `status` to `deleting`; delete the original, thumbnail, every object under `frames/<file_id>/` and every `sightings` document for the file; delete the `files` document last. Treat not-found as already deleted. Return one result per URL.
- `seed_data.py` writes records that follow the schema exactly and sets `seed: true`; it must also be able to remove them.
