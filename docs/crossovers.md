# Crossovers and conflicts

Places where two or more members' work meets. High means it breaks integration or costs a rubric item if left until the end. Rows marked New were added with this kit and still need the team's agreement.

| Members | Shared piece | Risk | What could go wrong | Agreed |
| --- | --- | --- | --- | --- |
| 2, 3 | Firestore file record | High | Field names or tag shape differ; one function overwrites another's fields | Member 2 commits the schema first; document ID is the SHA-256; each function merges only its own fields |
| 2, 3 | Upload event triggers | High | Thumbnail and tagging fire in either order; derived files re-trigger functions | Thumbnail key derives from the file ID; thumbnails and frames go to the derived bucket, which has no triggers |
| 2, 3 | Video frames | High | No agreed handoff, frames never cleaned up, counts summed | Member 2 extracts 1 frame per 10 s and publishes `frames-ready`; counts use the per-frame maximum; frames go when the file is deleted (Proposed change, see decisions) |
| 3, 4 | Tag vocabulary | High | Model labels never match query terms or Lex slot values | One list in `shared/tags.json`; member 3 maps model labels onto it; member 4's Lex slot type uses the same list |
| 1, 2, 3, 4 | API Gateway and Cognito tokens | High | Conflicting edits to one gateway spec; an endpoint left public | Member 1 owns the spec and merges route requests; the frontend sends tokens through one API client; `scripts/check-no-token.sh` tests every route |
| 1, 4 | Lex reaching GCP | High | Fulfilment Lambda has no valid token, or a hardcoded key; the widget can't call Lex | Token method still open (decisions); the widget uses a Cognito identity pool set up by member 1 |
| All | Cloud accounts and credits | High | Members deploy to separate accounts and nothing connects | One shared AWS account and one GCP project; agree whose credits pay for what |
| 2, 4 | Thumbnail naming | Medium | Thumbnail lookup guesses the original's name and fails for PNG or WebP | Thumbnails are `thumbs/<sha256>.jpg`; the original's key is in Firestore |
| 2, 4 | URLs as API input | Medium | Delete and bulk tagging parse URLs differently | One helper, `ecoguard_common.urls.file_id_from_url`, written by member 2 |
| 2, 3 | Query photos and re-uploads | Medium | Query photos go through the upload pipeline and get stored; a duplicate upload re-runs tagging | Query photos go to member 3's endpoints in memory; dedup happens before a signed URL is issued |
| 3, 4 | Manual and automatic tags | Medium | Re-tagging overwrites tags added by hand | Manual add sets count 1 if absent and records the tag in `manual_tags`; re-tagging keeps `manual_tags` |
| 3, 4 | Shared query logic | Medium | Search by file and lost pet search apply different AND or count rules | Both use `ecoguard_common.tag_match` (member 4); member 4's Lex fulfilment calls member 3's lost pet route |
| 1, 3, 4 | Notification events | Medium | Nobody publishes the event, or every write sends an email | Member 1's Firestore trigger fires only when `tags` gains a tag or a higher count; deletes and other writes are ignored |
| All | Least-privilege roles | Medium | Functions share one broad account; problems found too late to fix | Each owner writes a role limited to what their function touches; member 1 reviews all on Sat 31 Oct |
| 1, all | App shell and routing | Medium | Pages built in different styles; everyone edits the same route files | Framework and styling agreed; a folder per page; member 1 adds routes on request |
| 2, 3, 4 | Results gallery | Medium | Three galleries; selection works in one but not another | Member 4 builds one gallery with selection and full-size view; members 2 and 3 plug their actions and results into it |
| All | Report, diagram and Git history | Low | Report sections written the night before; unbalanced commits | Assign report owners now; everyone commits their own work through their own branches |
| 2, 3 | Sightings on delete (New) | Medium | Deleted files still show up in lost pet search | `delete_files` deletes `sightings` where `file_id` matches |
| 2, 3 | `frames-ready` topic (New) | Medium | Tagging never learns a video's frames exist | Member 2 publishes; member 3 subscribes; payload in `docs/contracts/events.md` |
