# tagging

Owner: member 3 · Rubric: 2.1.3 (and the data 2.2.1 searches)

## What it does
Gives every upload species tags with counts, written to `files/<sha256>`: `tags`, `model_version`, `tagged_at` and `pipeline.tagging`.

- **Images:** the bytes go to Amazon Rekognition `DetectLabels` in `us-east-1`. Labels are mapped to our tags through `shared/tags.json` and kept if they pass the tag's threshold. The count is the number of boxes on the tag's own label. If that label has no boxes, the count borrows the boxes on another animal label in the photo, or is 1. That's the rule the bake-off chose (`tools/testset`, decision of 29 Oct), in `../ecoguard_ml/detect.py`.
- **Videos:** tagged from `frames-ready`. Each tag's count is the highest count in any one frame, never the sum.
- **Settings:** every threshold, the detector, its region and the counting switches come from Firestore `config/model`, read on every event. Changing a threshold means editing `../config/model.json`, bumping `version` and running `../config/push_model_config.py`. No code change and no redeploy (rubric 2.1.3).
- **Manual tags:** the write is a transaction that keeps every tag in `manual_tags` at its existing count. Automatic tags the model no longer finds are removed.
- **Not stored on AWS:** Rekognition analyses the bytes and keeps nothing.
- **Original bytes, as in the bake-off:** a JPEG or PNG under 5 MB goes to Rekognition unchanged. Re-encoding can drop the weak labels a count borrows boxes from, so the bake-off's thresholds only hold for original bytes. WebP, and anything over 5 MB, becomes a 2048 px JPEG first (Rekognition reads only JPEG and PNG, up to 5 MB).
- **Logs:** each `tagged` log line lists the animal labels behind the counts, for example `Dog 84.8 (2 boxes)`.

Idempotent: a repeat event for a file already tagged by the current `config/model` version does nothing. An image Rekognition or Pillow can't read gets `pipeline.tagging: "failed"` and isn't retried. Any other error is raised, so the event is retried.

Not yet: lost pet `sightings` (cat and dog crops with Vertex AI embeddings).

## Triggers
Two functions deploy from this folder (`docs/contracts/events.md`):

| Function | Entry point | Trigger |
| --- | --- | --- |
| `tagging` | `on_upload` | Eventarc `google.cloud.storage.object.v1.finalized` on `ecoguard-g21-media`. Returns at once for videos |
| `tagging-frames` | `on_frames_ready` | Pub/Sub topic `frames-ready`, published by member 2's `process_upload` |

## Service account
`fn-tagging@ecoguard-g21.iam.gserviceaccount.com`, created and granted by `infra/gcp/ml.sh`. It is both functions' runtime account and their triggers' account.

| Role | On | Why |
| --- | --- | --- |
| `roles/storage.objectViewer` | media bucket | Reads each new image |
| `roles/storage.objectViewer` | derived bucket | Reads video frames |
| `roles/datastore.user` | project | Reads `config/model` and `files/<id>`, writes its tag fields |
| `roles/eventarc.eventReceiver` | project | Receives the media bucket's events |
| `roles/run.invoker` | `tagging` and `tagging-frames` services | Lets the triggers call functions that allow no unauthenticated calls |

**AWS:** the function swaps its Google ID token for one-hour credentials on the role `ecoguard-rekognition-detect`, which may call only `rekognition:DetectLabels` in `us-east-1` (`aws/iam/rekognition-detect.json`). Its trust policy accepts only tokens from `fn-tagging` and `fn-search-by-file` (`aws/iam/rekognition-detect-trust.json`). There are no AWS keys anywhere. This is cross-cloud link 4.

The policy's `Resource` is `*` because AWS has no resource ARNs for `DetectLabels`. The region condition narrows it instead.

Keep these tables to what the code actually uses. Member 1 reviews them before Gate 4.

## Test
```bash
cd functions/ml/tagging && python -m pytest   # this function
cd functions/ml && python -m pytest tests      # ecoguard_ml, including all 140 bake-off photos
```
`tests/test_detect.py` checks that `detect.count_tags`, with the thresholds in `config/model.json`, gives the same tags as `bakeoff.py` on every cached Rekognition response in `tools/testset`.

## Set up (a person runs this, once)
1. GCP accounts, which also print the unique IDs AWS needs:
   ```bash
   infra/gcp/ml.sh
   ```
2. With an AWS admin profile:
   ```bash
   aws iam create-role --role-name ecoguard-rekognition-detect \
     --assume-role-policy-document file://aws/iam/rekognition-detect-trust.json
   aws iam put-role-policy --role-name ecoguard-rekognition-detect \
     --policy-name detect-labels --policy-document file://aws/iam/rekognition-detect.json
   ```

## Deploy (a person runs this)
Gen2 names allow only lowercase letters, digits and hyphens.
```bash
cd functions/ml/tagging
cp -r ../../../shared/python/ecoguard_common .   # gitignored copies of the shared packages
cp -r ../ecoguard_ml .
cp ../../../shared/tags.json ecoguard_common/    # the tag list and label map
ROLE=arn:aws:iam::686890423796:role/ecoguard-rekognition-detect
SA=fn-tagging@ecoguard-g21.iam.gserviceaccount.com

gcloud functions deploy tagging \
  --gen2 --runtime=python312 --region=us-east1 --memory=512Mi \
  --source=. --entry-point=on_upload \
  --trigger-event-filters="type=google.cloud.storage.object.v1.finalized" \
  --trigger-event-filters="bucket=ecoguard-g21-media" \
  --trigger-service-account=$SA --service-account=$SA \
  --set-env-vars=REKOGNITION_ROLE_ARN=$ROLE \
  --retry --no-allow-unauthenticated

# Once member 2's process_upload publishes frames-ready:
gcloud functions deploy tagging-frames \
  --gen2 --runtime=python312 --region=us-east1 --memory=512Mi --timeout=540s \
  --source=. --entry-point=on_frames_ready \
  --trigger-topic=frames-ready \
  --trigger-service-account=$SA --service-account=$SA \
  --set-env-vars=REKOGNITION_ROLE_ARN=$ROLE \
  --retry --no-allow-unauthenticated
```
After the first deploy, re-run `infra/gcp/ml.sh` for the `run.invoker` grants.

`--retry` redelivers an event while it keeps failing for up to 24 hours. If the logs show `AccessDenied` from AWS, fix the role or trust policy rather than waiting it out.

## Check it works
Upload an image through the app (or `upload_init`), then within a minute:
```bash
gcloud functions logs read tagging --region=us-east1 --limit=20   # look for "tagged"
```
and the file's `tags` in the Firestore console.
