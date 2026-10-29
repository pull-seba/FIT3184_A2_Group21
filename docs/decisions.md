# Decisions

When a Proposed or Open item is settled, move it to Decided with the date, and update any contract it affects in the same PR.

## Decided (team plan, 25 Oct)

| Decision | Why |
| --- | --- |
| Split: 1 identity and cross-cloud, 2 ingestion and storage, 3 ML and detection, 4 search and chatbot | Each member owns a backend slice and its UI |
| AWS hosts Cognito, Lex and SNS; GCP hosts storage, Firestore, functions, API Gateway and hosting | The spec names Cognito, Lex and SNS; files never cross clouds; three real cross-cloud links remain to demo |
| Firestore for data, Cloud Storage for files | Same cloud as the functions; Firestore has map queries and vector search |
| File ID = SHA-256 of the bytes | One key for dedup, thumbnail lookup and every record |
| Merge-only Firestore writes, each function writing its own fields | Several functions write the same record |
| Video tag counts = maximum in any one frame | Summing counts the same animal once per frame |
| Thumbnails named by file ID, not by the original's name | Thumbnail lookup works for every format |
| Store bucket, key and `gs://` address; sign URLs per response | Buckets stay private and no stored link expires; the `gs://` addresses (added 27 Oct) give each record the storage URLs the spec asks for |
| Separate media and derived buckets (27 Oct) | Storage triggers can't filter by prefix, so thumbnails or frames in the media bucket would re-trigger the pipeline |
| Accepted uploads: JPEG, PNG and WebP up to 20 MB; MP4 and MOV up to 200 MB (27 Oct) | Formats OpenCV reads; HEIC isn't one |
| `is_public` defaults to `true`, with a checkbox on the upload page, carried to `process_upload` in the signed `x-goog-meta-is-public` header (27 Oct) | Lost pet search covers public sightings only, and `process_upload` only sees what's on the object |
| Shared code copied into each function folder before deploy (27 Oct) | `gcloud` uploads only the function's folder |
| One results gallery, built by member 4 | Avoids three galleries with different behaviour |
| Member 1 owns the gateway spec and app shell | Avoids merge conflicts on shared files |
| One shared AWS account and one GCP project, everyone added | AWS Academy lab accounts can't add teammates |
| Feature freeze at the end of Sat 31 Oct | Leaves two days for the demo checklist and reports |
| Regions GCP `us-east1`, AWS `us-east-1` (27 Oct, replaces the Sydney proposal) | Firestore and the Cognito user pool already live there and neither can move; an Eventarc Cloud Storage trigger must share its bucket's region; Cloud Storage's free tier covers `us-east1` |
| `/notifications/subscriptions` runs as the GCP function `notify/subscriptions`, which calls SNS with short-lived AWS credentials exchanged for its Google ID token (30 Oct) | Same path as every other route: behind the gateway's Cognito check, no public URL, caller from `ecoguard_common.auth.get_user`. No AWS keys, and SNS stays the one place alert tags live |

## Proposed (confirm by the date shown)

| Proposal | Owner | Confirm by | Notes |
| --- | --- | --- | --- |
| Functions in Python 3.12 with `functions-framework` | All | Mon 26 Oct | OpenCV and YOLO are Python |
| Frontend in Angular 21 (LTS) and TypeScript on Firebase Hosting | 1 | Mon 26 Oct | Firebase Hosting gives HTTPS, which Cognito callback URLs need. Member 4 proposed Angular instead of React and Vite on 27 Oct; member 1 to confirm |
| Frames handed to tagging through the `frames-ready` topic | 2, 3 | Mon 26 Oct | Settles the frame handoff crossover |
| Keep frames until the file is deleted | 2, 3 | Mon 26 Oct | Changes the crossover agreement "frames deleted after tagging"; keeping them lets the demo show 1 frame per 10 s |
| One `sightings` document per detected cat or dog | 3 | Tue 27 Oct | Firestore vector search needs one vector per document |

## Open

| Question | Owner | Decide by | Options |
| --- | --- | --- | --- |
| How the Lex fulfilment Lambda authenticates to the GCP gateway | 1, 4 | Wed 28 Oct | Forward the user's ID token in Lex session attributes (simplest), or Workload Identity Federation with a separate gateway audience |
| Embedding model for lost pet search | 3 | Tue 27 Oct | CLIP in the tagging container (free, larger image) or Vertex AI multimodal embeddings (managed, billed per call) |
| Cognito's temporary password step | 1 | Tue 27 Oct | The spec asks for email verification and a temporary password change, but self sign-up gives no temporary password; admin-created users do. Ask on Ed, or create users through `AdminCreateUser` from the sign-up page |
| Who owns the team report, architecture diagram and user guide | All | Tue 27 Oct | Lighter loads: members 1 and 2 |
