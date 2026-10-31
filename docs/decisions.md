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
| Tag list confirmed: the six starter tags, unchanged (28 Oct) | Member 4's queries and Lex slots already use them |
| `model_label_map` holds Rekognition's real label names, matched case-insensitively (28 Oct) | From a 30-image pilot in `tools/testset`. Frog, Amphibian, Hare, Canine, Coyote and Wolf are left out because they also fire on tree frogs, hares and foxes vs dogs |
| Frames handed to tagging through the `frames-ready` topic (28 Oct) | Settles the frame handoff crossover; tagging keeps each tag's highest count in any one frame |
| Keep frames until the file is deleted (28 Oct) | Replaces "frames deleted after tagging"; the demo can show 1 frame per 10 s, and delete removes them with the file |
| One `sightings` document per detected cat or dog (28 Oct) | Firestore vector search needs one vector per document |
| Tagging uses Amazon Rekognition `DetectLabels` in AWS `us-east-1` as the first model, replacing the planned detector container (29 Oct, agreed in the team chat) | Rekognition names our species directly (fox, toad, pig, rabbit), where stock YOLO or MegaDetector would need a second species model. `us-east-1` is the closest AWS region to our GCP compute in `us-east1`, and Rekognition keeps no state, so it needn't share a region with other AWS services. Images are sent for analysis only and never stored on AWS |
| Counts come from Rekognition's boxes; when a tag has no boxes of its own, it borrows the boxes Rekognition put on another animal label in the same photo. No MegaDetector (29 Oct) | Bake-off on 140 photos (`tools/testset`): photos with 2+ animals get a count of 2+ for pigs 100%, foxes 67%, toads 33% and rabbits 33% with borrowing (0-50% without), with one over-count. Rubric 2.1.3 accepts Rekognition alone; a counting model can be added later through `config/model`. Toad groups are undercounted, a known limitation |
| Lost pet embeddings use Vertex AI `multimodalembedding@001`, 1408 numbers (29 Oct) | Images and text share one embedding space, so the same model serves search by photo and by description ("ginger cat") for the page and the chatbot. Same cloud as Firestore vector search, so it doesn't depend on the AWS federation. Chosen over CLIP (a 1-2 GB container), Titan Multimodal (would also need the federated AWS role) and Gemini Embedding 2 (3072 numbers by default, over Firestore's limit) |
| `/notifications/subscriptions` runs as the GCP function `notify/subscriptions`, which calls SNS with short-lived AWS credentials exchanged for its Google ID token (30 Oct) | Same path as every other route: behind the gateway's Cognito check, no public URL, caller from `ecoguard_common.auth.get_user`. No AWS keys, and SNS stays the one place alert tags live |

## Proposed (confirm by the date shown)

| Proposal | Owner | Confirm by | Notes |
| --- | --- | --- | --- |
| Functions in Python 3.12 with `functions-framework` | All | Mon 26 Oct | OpenCV and YOLO are Python |
| Frontend in Angular 21 (LTS) and TypeScript on Firebase Hosting | 1 | Mon 26 Oct | Firebase Hosting gives HTTPS, which Cognito callback URLs need. Member 4 proposed Angular instead of React and Vite on 27 Oct; member 1 to confirm |

## Open

| Question | Owner | Decide by | Options |
| --- | --- | --- | --- |
| How the Lex fulfilment Lambda authenticates to the GCP gateway | 1, 4 | Wed 28 Oct | Forward the user's ID token in Lex session attributes (simplest), or Workload Identity Federation with a separate gateway audience |
| Cognito's temporary password step | 1 | Tue 27 Oct | The spec asks for email verification and a temporary password change, but self sign-up gives no temporary password; admin-created users do. Ask on Ed, or create users through `AdminCreateUser` from the sign-up page |
| Who owns the team report, architecture diagram and user guide | All | Tue 27 Oct | Lighter loads: members 1 and 2 |
