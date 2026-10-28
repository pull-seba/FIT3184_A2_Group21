# Member 4: search and chatbot

Name and ID: Jenul Ferdinand (33119805)

You own 22 marks alone (2.2.1, 2.2.2, 2.3.1, 2.2.5, 3.3), the heaviest load, and share 3.2 (tag query UI and gallery) and 3.4 (bulk tag controls). The gallery and `tag_match` are used by members 2 and 3, so build them early.

## What you own
- `functions/search/`: `tag_query`, `thumbnail_lookup`, `bulk_tags`
- `shared/python/ecoguard_common/tag_match.py`
- `aws/lex/`: bot definition, slot types, fulfilment Lambda
- `frontend/src/app/components/gallery/`, `frontend/src/app/pages/search/`, `frontend/src/app/pages/tags/`, `frontend/src/app/pages/chat/`

## Steps by phase
| Phase | Steps |
| --- | --- |
| Contracts, Mon 26 | Route JSON for search, thumbnail lookup and bulk tags |
| Foundations, to Tue 27 | Tag queries on seed data; thumbnail lookup; results gallery; Lex intents and slots |
| Pipeline, Wed 28 to Fri 30 | Queries on real data; bulk tag API; Lex fulfilment calling the gateway; search page and chat widget |
| Integrate, Sat 31 | Least-privilege roles; edge tests |

## Watch out for
- AND with minimum counts: query Firestore on the rarest tag, then check every tag and count in code before returning.
- Accept `{"cat": 1}` and `["cat"]`, plus `GET /search/species?name=cat`. Lowercase and trim names; unknown tags give `400`.
- Thumbnail lookup and bulk tagging resolve URLs only through `ecoguard_common.urls`, so signed and encoded URLs work.
- Bulk add sets count 1 if absent and records `manual_tags`; removing an absent tag is ignored; batches hold at most 500 writes.
- Lex slot type values come from `shared/tags.json`. Resolve "yesterday" in Australia/Melbourne time.
- The chat widget needs identity pool credentials from member 1.

## Who you depend on, and who waits on you
| Who | Direction | What | Needed by |
| --- | --- | --- | --- |
| 2 | You need | Seed data | Tue 27 |
| 3 | You need | Final tag list | Mon 26 |
| 1 | You need | Identity pool and the Lex token method | Wed 28 |
| 2 | You need | Thumbnail keys on records; URL helper | Thu 29 |
| 2, 3 | They need | Gallery with selection and full-size view | Fri 30 |
| 3 | They need | `tag_match` | Wed 28 |
