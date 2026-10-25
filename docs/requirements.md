# Requirements and rubric

Source: the FIT3184 2026 S2 Assignment 2 spec and marking rubric (100 marks, 40% of the unit). Every rubric item is marked 100%, 50% or 0% in the demo. The 50% column is the specific failure that loses half the marks.

## How marking works
- Marks are given only during the live Zoom demo. No demo means no marks, and every member must attend.
- The demo: up to 3 minutes on the architecture, then up to 15 minutes of demo and Q&A following the examiners' guidelines. Any member can be asked about any code.
- Multi-cloud communication must be shown and justified in the demo.
- A member who doesn't contribute can lose up to 50% of the group mark, judged from the contribution table, Git history, individual reports and the Q&A.
- With no web UI, section 3 is capped at 14 of 20, and only if every UI interaction is shown another way (Postman, scripts, curl).
- Late submission: 5% per day for up to 7 days, then zero. No extensions for groups.
- The team pays for any cloud costs until assessment ends in Week 15.
- AI use is allowed but must be documented and acknowledged, and members must understand and be able to modify any generated code.

## 1. Authentication and authorisation (10 marks)

| Item | Marks | Owner | Full marks | Drops to 50% when | Show it in the demo |
| --- | --- | --- | --- | --- | --- |
| 1.1 Sign-up, sign-in, sign-out | 4 | 1 | Cognito handles registration with email, first name, last name and password; email verification; the temporary password change; login; sign-out | The verification flow, required attributes or password reset is buggy or incomplete | Register a new user live, verify by email, sign in, sign out |
| 1.2 Access control and redirection | 3 | 1 | Signed-out users are blocked from every page and endpoint except sign-up and sign-in, and redirected | Some routes or endpoints stay open, or redirects misbehave | Open a protected page signed out; run `scripts/check-no-token.sh` |
| 1.3 Least privilege and cross-cloud auth | 3 | 1 (all draft) | Uploads, function calls and database access use least-privilege roles; tokens reach the second cloud securely | Wildcard permissions, or insecure or hardcoded token passing. Zero if credentials are in client code | Show one function's service account and roles; explain each cross-cloud link's auth |

## 2. Core functionality (50 marks)

### 2.1 File and model handling (16 marks)

| Item | Marks | Owner | Full marks | Drops to 50% when | Show it in the demo |
| --- | --- | --- | --- | --- | --- |
| 2.1.1 Upload and deduplication | 5 | 2 | Files upload reliably through a REST API or SDK to object storage; duplicates are blocked by a checksum of the content | Duplicate detection fails, errors, or uses file names or sizes | Upload a photo, then the same photo renamed: duplicate message, no new object |
| 2.1.2 Thumbnails and video | 5 | 2 | An event-driven function makes compressed thumbnails that keep the aspect ratio (for example with OpenCV); videos give one frame per 10 seconds | Ignores compression or aspect ratio, or extracts frames at the wrong rate | Compare original and thumbnail sizes and dimensions; show a 60 s clip's 6 frames |
| 2.1.3 ML tagging, extensibility, database | 6 | 3 | A serverless function runs MegaDetector, YOLO or Rekognition and saves species tags, file type and URLs; models change without code changes | Incomplete records, manual triggers, or models tied to the code | Change `config/model`, upload, show the new `model_version` |

### 2.2 Queries and retrieval (24 marks)

| Item | Marks | Owner | Full marks | Drops to 50% when | Show it in the demo |
| --- | --- | --- | --- | --- | --- |
| 2.2.1 Find by tags | 5 | 4 | JSON queries with minimum counts (`{"fox": 2}`, `{"feral pig": 1, "cane toad": 3}`) combined with AND, plus species queries, return correct media URLs | Behaves as OR, ignores counts, or returns malformed URLs | Seed files where OR or ignored counts would give a visibly different answer |
| 2.2.2 Find by thumbnail URL | 3 | 4 | Any thumbnail URL resolves to its full-size image URL | Fails for some formats or returns invalid URLs | JPEG, PNG and WebP originals, and a signed thumbnail URL |
| 2.2.3 Find by uploaded file | 5 | 3 | Accepts a file, detects tags on the fly, returns files with those tags; the query file is never stored or indexed | The query file stays in storage or the database | Search, then show the buckets and Firestore unchanged |
| 2.2.4 Lost pet search | 5 | 3 | Search by a pet photo or by tags such as breed and colour, against public sightings | Text only with no photo input, or sightings not filtered | Photo of a cat seen in earlier uploads ranks first; description search respects the date window |
| 2.2.5 Lex chatbot | 6 | 4 | Lex parses intents and entities, calls the backend functions and shows matching media links | Fragile slot recognition, backend not called, or raw unformatted replies | "Show me all photos of foxes spotted yesterday"; "Help me find a lost ginger cat" |

### 2.3 Data management and notifications (10 marks)

| Item | Marks | Owner | Full marks | Drops to 50% when | Show it in the demo |
| --- | --- | --- | --- | --- | --- |
| 2.3.1 Bulk tag editing | 3 | 4 | A POST API adds (`operation: 1`) or removes (`operation: 0`) tags across many URLs; removing a tag a file doesn't have is ignored | Works for one file only, or misreads the operation flag | Add and remove across three files, including an absent tag |
| 2.3.2 File and record deletion | 3 | 2 | Deletes files, videos and thumbnails from storage together with their database entries | Leaves orphaned records or files, or bulk delete fails | Delete a video and an image; show storage and Firestore clean |
| 2.3.3 Tag-based notifications | 4 | 1 | SNS (or a GCP equivalent) emails reliably when files with monitored tags are uploaded or updated | Intermittent, no tag filtering, or broken message bodies | Subscribe to fox, upload a fox and a cat: one email |

## 3. User interface (20 marks)

| Item | Marks | Owner | Full marks | Drops to 50% when |
| --- | --- | --- | --- | --- |
| 3.1 Auth and upload UI | 5 | 1 (auth), 2 (upload) | Sign-up, sign-in and upload pages with clear feedback on upload success and duplicates | No feedback or error states, layout defects, or manual refreshes |
| 3.2 Query and lost pet UI | 5 | 4 (tag query, gallery), 3 (by file, lost pet) | Tag and count queries, file search and lost pet search, with a responsive thumbnail gallery that opens full-size media | Missing previews, clicking doesn't open the full image, or lost pet UI not wired up |
| 3.3 Chatbot UI | 5 | 4 | A chatbot widget in the app, live text chat, clickable results | Poorly integrated, crashes on unexpected input, or links not clickable |
| 3.4 Tag management and usability | 5 | 4 (tags), 2 (delete), 1 (shell) | Bulk tag add and remove and file deletion controls; clean, accessible, intuitive design | Clunky, no bulk selection, or hard to navigate |

## 4. Demo and reports (20 marks)

| Item | Marks | Owner | Full marks | Drops to 50% when |
| --- | --- | --- | --- | --- |
| 4.1.1 Architecture presentation | 5 | All | Clear 3-minute talk on the multi-cloud architecture and trade-offs, official cloud icons, services on both providers justified, every member speaks | Rushed, shallow on trade-offs, unofficial icons, or uneven participation |
| 4.1.2 Demo and Q&A | 10 | All | Smooth, bug-free demo of every workflow; confident answers to technical questions | Notable bugs or delays, or struggling with architecture and code questions |
| 4.2.1 Team report | 3 | Open (see decisions) | Official multi-cloud diagram, complete contribution table, user guide, private repo link with balanced commits | Missing one or two of these |
| 4.2.2 Individual report | 2 | Each member | About 150 words on your role and contribution and about 150 words reflecting on the teamwork | Incomplete or no real reflection |

## Spec details the rubric doesn't spell out
- Sign-up records email, first name, last name and password. Every page and endpoint except sign-up is blocked when signed out. Login and sign-up can use Cognito's managed login or custom pages.
- Fine-grained permissions use IAM roles or the GCP equivalent. AWS Academy roles are limited; a personal free AWS account avoids that.
- The first model in any chain must be MegaDetector, YOLO (Ultralytics) or Rekognition. Later models can come from Hugging Face. No training is needed.
- Uploads trigger a serverless function. Thumbnails resize to a smaller size keeping the aspect ratio, then compress. Videos: one frame per 10 seconds, not every frame.
- The tag query returns thumbnail URLs for images and file URLs for videos. The spec's species-only example `{"cat"}` isn't valid JSON; `docs/contracts/api-routes.md` defines the accepted forms.
- Lost pet search takes a photo or tags such as breed or colour and searches recent public sightings.
- Bulk tag edits send a list of URLs, the tags and `operation`. Delete takes a list of URLs and removes files, thumbnails and records.
- Notifications: email when new or updated files carry the tags a user chose, through SNS or an equivalent.
- The UI must support every core function; without one, the demo must show each another way.
- Team report: at most 1000 words (tables, diagram, screenshots and references don't count); a multi-cloud diagram with official icons for every provider; a three-column contribution table (name and ID, percentage, what they did in at most 100 words); a simple user guide; a link to a private repo shared with the teaching team, where every member commits their own code. PDF, Arial, Helvetica or Times New Roman at 12 pt. One submission per team.
- Individual report: at most 500 words, written with little or no consultation; role and contribution (150 words) and a reflection on teammates' work, challenges and teamwork (150 words). PDF, every member submits.
