# Architecture

Identity, the chatbot and email run on AWS, using the three services the spec names. Files, data and compute stay together on GCP, so files never cross clouds, and the demo still shows three real cross-cloud links.

## Services by requirement

| Rubric item | Owner | Cloud | Services | Why, and the alternative |
| --- | --- | --- | --- | --- |
| 1.1 Sign-up, sign-in, sign-out | 1 | AWS | Cognito user pool with managed login, or custom pages calling Cognito | The spec requires Cognito |
| 1.2 Access control | 1 | AWS + GCP | Cognito ID token; API Gateway JWT check against the user pool's issuer and keys; route guard in the app | The gateway rejects bad tokens before any function runs |
| 1.3 Permissions, cross-cloud auth | 1, all | AWS + GCP | One service account per function; one IAM role per Lambda; Workload Identity Federation; OIDC tokens on Pub/Sub push | No long-lived keys anywhere |
| 2.1.1 Upload and dedup | 2 | GCP | Cloud Run function behind the gateway issuing V4 signed upload URLs; Firestore lookup by SHA-256 | The browser hashes with Web Crypto; `if-generation-match: 0` blocks overwrites. Alternative: S3 presigned URLs, which would put files away from Firestore |
| 2.1.2 Thumbnails and video | 2 | GCP | Cloud Storage events through Eventarc to a Cloud Run function with OpenCV | Same cloud as the files |
| 2.1.3 ML tagging | 3 | GCP | Cloud Run service from a container running the detector; weights in Cloud Storage; active model in `config/model` | A container holds large model dependencies; editing the config swaps models. Alternative: Rekognition, managed but sends every image across clouds |
| 2.2.1 Find by tags | 4 | GCP | Cloud Run function with Firestore map-field queries | Runs next to the data |
| 2.2.2 Thumbnail lookup | 4 | GCP | Cloud Run function, one Firestore read by file ID | One read, no extra index |
| 2.2.3 Find by uploaded file | 3 | GCP | The detector's inference endpoint in memory, then the shared tag matching | Nothing touches storage or the database |
| 2.2.4 Lost pet search | 3 | GCP | Firestore vector search over `sightings` embeddings | Vector search lives in the database already in use |
| 2.2.5 Chatbot | 4 | AWS | Lex V2 bot with a Lambda that calls the GCP gateway | Spec requires Lex; cross-cloud link 2 |
| 2.3.1 Bulk tag editing | 4 | GCP | Cloud Run function with Firestore batched writes | All-or-nothing updates |
| 2.3.2 File deletion | 2 | GCP | Cloud Run function deleting objects, sightings and the record | Both stores on one cloud |
| 2.3.3 Notifications | 1 | GCP + AWS | Firestore trigger → Pub/Sub → push to an AWS Lambda → SNS email with a filter policy per tag | Cross-cloud link 3; GCP has no built-in email sender |
| 3.x User interface | All | GCP | Firebase Hosting single-page app; the Lex widget gets AWS credentials from a Cognito identity pool | HTTPS by default. Alternative: S3 with CloudFront |

## Cross-cloud links to demo
1. **Cognito → GCP API Gateway.** The browser sends the Cognito ID token; the gateway checks its signature against the user pool's public keys, its issuer and its audience (the app client ID), then forwards the claims to the function.
2. **Lex (AWS) → GCP API.** The fulfilment Lambda calls the gateway with a Cognito ID token (method in `docs/decisions.md`).
3. **Firestore (GCP) → SNS (AWS).** A Firestore trigger publishes to Pub/Sub, which pushes to an AWS Lambda with a Google-signed OIDC token; the Lambda checks the token and publishes to SNS.

## Flows

### Upload an image
1. The browser computes the file's SHA-256 and calls `POST /uploads/init`.
2. If `files/<sha256>` is an active record, the response is `duplicate` and nothing else happens. Otherwise it returns a signed PUT URL for `<sha256>.<ext>`.
3. The browser uploads straight to Cloud Storage with `XMLHttpRequest`, showing progress.
4. The finalize event starts `process_upload` (2): verify the hash, write the base record, write `thumbs/<sha256>.jpg`, merge `thumbnail_key`.
5. The same event starts tagging (3): detect, map labels, write `tags`; for cats and dogs, write `sightings`.
6. The `tags` change fires `on_tags_changed` (1) → `tag-changes` → AWS Lambda → SNS email to subscribers of those tags.

### Upload a video
Steps 1 to 4 as above, except `process_upload` extracts one frame per 10 s into `frames/<sha256>/`, makes a poster thumbnail and publishes `frames-ready`. Tagging tags each frame and keeps the highest count per tag.

### Search
The browser calls a search route through the gateway; the function queries Firestore, signs URLs and returns `FileSummary` objects for the shared gallery. Clicking a tile calls `/search/thumbnail` to open the full-size file.

### Chatbot
The widget calls Lex with identity pool credentials. Lex picks the intent and slots, the fulfilment Lambda calls the GCP route, and the reply lists results as links.

### Delete
`POST /files/delete` marks each file `deleting`, removes the original, thumbnail and frames, deletes its sightings, then deletes the record. A repeat call finishes any half-done delete.

For the team report, redraw this with the official AWS and Google Cloud architecture icons.
