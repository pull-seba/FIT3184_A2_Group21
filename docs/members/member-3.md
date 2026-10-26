# Member 3: ML and detection

Name and ID: (add)

You own 16 marks alone (2.1.3, 2.2.3, 2.2.4) and share 3.2 (search by file and lost pet screens). Tagging writes into member 2's record and turns member 2's frames into video tags, so most of your crossovers are with member 2.

## What you own
- `functions/ml/`: the tagging service (container), `search_by_file`, `lost_pet`
- `shared/tags.json`, `config/model`, the `sightings` collection and its vector index, the models bucket
- `frontend/src/app/pages/query-by-file/` and `frontend/src/app/pages/lost-pet/`

## Steps by phase
| Phase | Steps |
| --- | --- |
| Contracts, Mon 26 | Confirm the tag list and model label map; agree `frames-ready` with member 2 |
| Foundations, to Tue 27 | Detector container; `config/model`; label mapping; test on a sample set; choose the embedding model |
| Pipeline, Wed 28 to Fri 30 | Tagging on upload and on `frames-ready`; `sightings` with embeddings and colour; search by file; lost pet search; both pages on the shared gallery |
| Integrate, Sat 31 | Least-privilege service accounts; edge tests |

## Watch out for
- The first model must be MegaDetector, YOLO or Rekognition. MegaDetector only says animal, person or vehicle, and COCO-trained YOLO knows cat and dog but not fox, rabbit, pig or toad, so plan a chained species classifier.
- Models change through `config/model` and the models bucket, never through code (rubric 2.1.3).
- Tagging writes `tags` in a transaction and keeps every tag in `manual_tags`.
- Video counts are the maximum in any one frame.
- Query photos stay in memory: no Cloud Storage or Firestore writes in `search_by_file` or `lost_pet`.
- Use `ecoguard_common.tag_match` (member 4) for AND matching so every search agrees.

## Who you depend on, and who waits on you
| Who | Direction | What | Needed by |
| --- | --- | --- | --- |
| 2 | You need | Schema and first real record (Gate 2) | Tue 27 |
| 2 | You need | Seed data | Tue 27 |
| 2 | You need | Frames and `frames-ready` | Thu 29 |
| 4 | They need | Final tag list for Lex slot types | Mon 26 |
| 4 | They need | Lost pet route for the chatbot | Thu 29 |
| 4 | You need | Gallery and `tag_match` | Fri 30 |
