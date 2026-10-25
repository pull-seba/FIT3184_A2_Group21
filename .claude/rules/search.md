---
paths:
  - "functions/search/**"
  - "shared/python/ecoguard_common/tag_match.py"
  - "aws/lex/**"
---

# Search, tags and chatbot (member 4; rubric 2.2.1, 2.2.2, 2.3.1, 2.2.5)

- Tag queries combine tags with AND and each count is a minimum. Query Firestore on one tag to narrow candidates, then check every tag and count in code before returning anything. OR results or ignored counts are the rubric's 50% case.
- Accept `{"cat": 1}` and `["cat"]` bodies and `GET /search/species?name=cat`. Lowercase and trim names. Unknown tags and counts below 1 give `400`. Skip files whose `status` is `deleting`.
- Resolve every URL with `ecoguard_common.urls.file_id_from_url`. Thumbnail lookup reads the file's `media_key` from Firestore; never rebuild the original's name from the thumbnail's.
- Bulk tags: `operation` 1 adds (count 1 if absent, `ArrayUnion` into `manual_tags`); 0 removes (`DELETE_FIELD`, `ArrayRemove`); removing an absent tag is not an error. Validate tags against `shared/tags.json`. At most 500 writes per batch. One result per URL.
- Lex: slot type values come from `shared/tags.json`. Resolve relative dates such as "yesterday" in Australia/Melbourne time and pass them as `from` and `to`. Reply with each result as a clickable link and a friendly message when nothing matches. Keep the bot definition exported in `aws/lex/` so it is in Git.
