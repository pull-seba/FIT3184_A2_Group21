# tagging

Owner: member 3 · Rubric: 2.1.3, 2.2.4 (lost pet sightings), and the data 2.2.1 searches

## What it does
Gives every upload species tags with counts, written to `files/<sha256>`: `tags`, `model_version`, `tagged_at` and `pipeline.tagging`. Each cat or dog it finds also becomes a lost pet sighting, `sightings/<sha256>_<n>`.

- **Images:** the bytes go to Amazon Rekognition `DetectLabels` in `us-east-1`. Labels are mapped to our tags through `shared/tags.json` and kept if they pass the tag's threshold. The count is the number of boxes on the tag's own label. If that label has no boxes, the count borrows the boxes on another animal label in the photo, or is 1. That's the rule the bake-off chose (`tools/testset`, decision of 29 Oct), in `../ecoguard_ml/detect.py`.
- **Videos:** tagged from `frames-ready`. Each tag's count is the highest count in any one frame, never the sum.
- **Settings:** every threshold, the detector, its region and the counting switches come from Firestore `config/model`, read on every event. Changing a threshold means editing `../config/model.json`, bumping `version` and running `../config/push_model_config.py`. No code change and no redeploy (rubric 2.1.3).
- **Manual tags:** the write is a transaction that keeps every tag in `manual_tags` at its existing count. Automatic tags the model no longer finds are removed.
- **Not stored on AWS:** Rekognition analyses the bytes and keeps nothing.
- **Original bytes, as in the bake-off:** a JPEG or PNG under 5 MB goes to Rekognition unchanged. Re-encoding can drop the weak labels a count borrows boxes from, so the bake-off's thresholds only hold for original bytes. WebP, and anything over 5 MB, becomes a 2048 px JPEG first (Rekognition reads only JPEG and PNG, up to 5 MB).
- **Logs:** each `tagged` log line lists the animal labels behind the counts, for example `Dog 84.8 (2 boxes)`.

Idempotent: a repeat event for a file already tagged by the current `config/model` version does nothing. An image Rekognition or Pillow can't read gets `pipeline.tagging: "failed"` and isn't retried. Any other error is raised, so the event is retried.

- **Sightings (rubric 2.2.4):** every Cat or Dog label that passes its tag's threshold gives one sighting per box with confidence of at least `box_min_confidence`, or one whole-image sighting (`bbox` `[0, 0, 1, 1]`) if it has none. Each box is cropped from the original with 10% padding, after EXIF rotation (Rekognition's boxes are for the upright photo), and embedded with Vertex AI `multimodalembedding@001` (1408 numbers, model and region from `config/model`). `colour` is the word in `lost_pet_colours` (`shared/tags.json`) whose text embedding, "a photo of a ginger cat", is closest to the crop's. `breed` is Rekognition's most confident label with Dog or Cat as a parent, skipping generic ones such as Puppy, or null if there is none. Code: `../ecoguard_ml/sightings.py` and `../ecoguard_ml/embed.py`.
- **Sightings' `uploaded_at` and `is_public`:** for an image, from the storage event (`timeCreated`, and `is-public` metadata by `process_upload`'s rule), because tagging can run before `process_upload` writes `files/`. For a video, from `files/`, which exists before `frames-ready` is published. Video sightings set `frame_index` and are numbered on across frames.
- **Write order:** sightings are written before the tags, because a file whose `pipeline.tagging` is `done` is skipped on a repeat event. Re-tagging with fewer pets deletes the extra sightings.

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
| `roles/datastore.user` | project | Reads `config/model` and `files/<id>`, writes its tag fields and `sightings` |
| `roles/aiplatform.user` | project | Calls Vertex AI `multimodalembedding@001` for each pet crop and the colour words. If it's judged too broad, a custom role with only `aiplatform.endpoints.predict` would do |
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
3. The `sightings` indexes, recorded in `infra/gcp/firestore.indexes.json`. Don't `firebase deploy` that file: other members' indexes aren't in it.
   ```bash
   IDX="gcloud firestore indexes composite create --project=ecoguard-g21 --collection-group=sightings --query-scope=COLLECTION"
   VEC='field-path=embedding,vector-config={"dimension":"1408","flat":"{}"}'
   # Photo + species, and photo only (api-routes.md allows a photo with no species)
   $IDX --field-config=field-path=species,order=ascending --field-config=field-path=is_public,order=ascending --field-config="$VEC"
   $IDX --field-config=field-path=is_public,order=ascending --field-config="$VEC"
   # Description searches, newest first, without and with colour
   $IDX --field-config=field-path=species,order=ascending --field-config=field-path=is_public,order=ascending \
        --field-config=field-path=uploaded_at,order=descending
   $IDX --field-config=field-path=species,order=ascending --field-config=field-path=is_public,order=ascending \
        --field-config=field-path=colour,order=ascending --field-config=field-path=uploaded_at,order=descending
   gcloud firestore indexes composite list --project=ecoguard-g21   # wait until all four are READY
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
and the file's `tags` in the Firestore console. A cat or dog photo also gets `sightings/<sha256>_0` with a 1408-number `embedding`, a `colour` and its `is_public`; the log line shows `sightings=1`.
