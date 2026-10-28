---
paths:
  - "functions/ml/**"
  - "shared/tags.json"
---

# ML and detection (member 3; rubric 2.1.3, 2.2.3, 2.2.4)

- The first model in the chain is MegaDetector, YOLO or Rekognition. Chained models after it can come from Hugging Face.
- Read `config/model` on start-up and re-read it every few minutes. Never hardcode a weights path, model name or threshold: changing models must need no code change.
- Map every model label through `model_label_map` in `shared/tags.json` and drop labels that aren't mapped.
- Write `tags` in a transaction that keeps every tag listed in `manual_tags`. Set `model_version`, `tagged_at` and `pipeline.tagging`.
- Videos are tagged from `frames-ready`, not from the upload event. For each tag keep the highest count in any one frame.
- For each detected cat or dog, write a `sightings` document with the crop's embedding as a Firestore `Vector`, colour, breed if known, and `uploaded_at` and `is_public` copied from the file.
- `search_by_file` and `lost_pet` keep the query photo in memory. They must not call any Cloud Storage write or Firestore write.
- Match tags with `ecoguard_common.tag_match` so AND and count rules agree with `/search/tags`.
- Lost pet search filters to `is_public == true`, the requested species and the date window before ranking by similarity.
