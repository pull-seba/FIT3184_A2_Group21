# lost_pet

Owner: member 3 · Rubric: 2.2.4

## What it does
`POST /search/lost-pet`: the owner of a lost cat or dog finds public sightings that may be their pet, by photo, by description, or both.

```json
{ "image_base64": "<optional base64 photo>", "species": "cat", "colour": "ginger", "breed": null, "since_days": 30 }
```
Response: `{"results": [FileSummary + {"score": 0.91, "sighting_id": "<file_id>_0"}]}`, with fresh 60-minute signed `GET` URLs (`docs/contracts/api-routes.md`).

Sightings are the `sightings/<file_id>_<n>` documents tagging writes for every cat or dog it finds: the crop's Vertex AI embedding, species, colour, breed, and the file's `uploaded_at` and `is_public` (`../ecoguard_ml/sightings.py`, `docs/contracts/firestore-schema.md`).

- **Search by photo** (`image_base64` sent): the photo is shrunk in memory to a JPEG of at most 1024 px and embedded by Vertex AI with the model in `config/model`, the same one that embedded every sighting (`../ecoguard_ml/embed.py`). Firestore's vector search (`find_nearest`, cosine distance) returns the 50 nearest public sightings, of `species` if one is given. Results are best score first.
- **One vector query:** `firestore.indexes.json` has a vector index with `species` and `is_public` as pre-filters and one with `is_public` alone, so a photo with or without a species is one query. There is no separate cat and dog query.
- **Score:** `round(1 - distance, 2)`. Cosine distance is 1 minus the cosine similarity, so 1.0 means the same direction in embedding space, and higher is more alike.
- **Date and colour on photo search are checked in Python:** the vector indexes have no `uploaded_at` or `colour` field (each extra filter would need another vector index), so sightings older than `since_days`, or of another `colour`, are dropped from the 50 nearest after the query. Known limit: if most of the 50 nearest are too old or the wrong colour, fewer results come back.
- **Search by description** (no photo, so `species` is required): `species ==`, `is_public == true`, `colour ==` if given, `uploaded_at >=` the cutoff, newest first, at most 50. That is exactly one of the two `uploaded_at` indexes in `firestore.indexes.json`. `score` is `null`.
- **One result per file:** a photo can hold several pets. Each file appears once, with its best sighting (highest score, or the first in newest-first order), and `sighting_id` says which pet matched.
- **Only active files:** the matched files are read in one `get_all`; a file that is being deleted, or that `process_upload` hasn't recorded yet, is left out, the same `status == "active"` rule as `/search/tags`.
- **`breed` is checked in Python on both kinds of search:** tagging gives a sighting Rekognition's most confident label under Dog or Cat, such as Husky or Siamese (`../ecoguard_ml/sightings.py`). A sighting matches when the words sent are part of its breed, ignoring case, so "labrador" finds "Labrador Retriever". No new index is needed. Known limits: this filters the 50 sightings the query returns, breed labels often score only 50-60, a label describes the whole photo rather than one pet, and sightings tagged before this change have `breed: null`, so only newer uploads can match.
- **Never stored:** the photo stays in memory. This function makes no Cloud Storage or Firestore write, and logs only `species`, `colour`, `since_days`, whether a photo was sent and the result count, never the image, its base64 or its embedding. `test_a_full_search_makes_no_write_to_firestore_or_storage` checks every call a full search makes, and `test_the_log_has_no_photo_or_embedding` checks the log line. Vertex AI stores nothing it embeds. Rekognition is not called, so this route doesn't depend on the AWS link.
- **Missing and `null` are the same** for `species`, `colour` and `breed`. The lost-pet page sends `species: null` for "any species" (only with a photo: that is the `is_public`-only vector query), `colour: null` for any colour and `breed: null` for any breed; it leaves out `image_base64` when there is no photo.
- **Formats:** any image Pillow can read, up to 20 MB (`ecoguard_common.uploads.ACCEPTED`). The route has no `content_type`, so Pillow works out the format. The browser already sends a JPEG of about 1024 px (`docs/contracts/api-routes.md`), so the shrink here is a cheap safeguard for other clients.
- **Shared code to move later:** `signed_get_url()` and `file_summary()` are copied from member 4's `search/tag_query`, so `FileSummary` is built the same way on every route. They should move into `ecoguard_common` after the demo.

Input is checked in this order, before any Firestore or Vertex AI call:

| Status | Code | When |
| --- | --- | --- |
| 204 | | `OPTIONS` preflight, with the CORS headers from `infra/gateway/README.md` |
| 401 | `unauthenticated` | No gateway user (`ecoguard_common.auth.get_user`) |
| 400 | `bad_json` | Body isn't a JSON object |
| 400 | `missing_query` | Neither `image_base64` nor `species` (missing and `null` both count as not sent) |
| 400 | `bad_species` | `species` isn't in `lost_pet_species` (`cat`, `dog`) |
| 400 | `bad_colour` | `colour` isn't in `lost_pet_colours`. `null` or `""` means any colour |
| 400 | `bad_since_days` | `since_days` isn't a whole number from 1 to 365 (default 30; `true` is rejected) |
| 400 | `bad_breed` | `breed` isn't a string or `null` |
| 400 | `bad_file` | `image_base64` isn't a non-empty string |
| 400 | `bad_base64` | `image_base64` doesn't decode |
| 413 | `too_large` | Decoded photo over 20 MB |
| 400 | `bad_image` | Pillow can't read the photo |
| 500 | `internal` | Anything else, such as a Vertex AI error (logged) |

Every response carries `Access-Control-Allow-Origin: *`.

## Route
`POST /search/lost-pet` through API Gateway (`infra/gateway/openapi.yaml`, member 1), which checks the Cognito ID token and calls the `lost-pet` function as `ecoguard-gateway`, with a 60 s deadline because embedding a photo can take longer than the 15 s default.

## Service account
`fn-lost-pet@ecoguard-g21.iam.gserviceaccount.com`, created and granted by `infra/gcp/ml.sh`.

| Role | On | Why |
| --- | --- | --- |
| `roles/datastore.viewer` | project | Reads `config/model`, queries `sightings` and reads `files`. No write role, so it can't store anything in Firestore |
| `roles/aiplatform.user` | project | Embeds the query photo with Vertex AI |
| `roles/storage.objectViewer` | media bucket | A signed URL reads as the account that signed it: originals |
| `roles/storage.objectViewer` | derived bucket | The same, for thumbnails |
| `roles/iam.serviceAccountTokenCreator` | itself | Signs URLs through the IAM credentials API, without a key file |
| `roles/run.invoker` (held by `ecoguard-gateway`) | `lost-pet` service | Only the gateway may call it |

**AWS:** none. It doesn't call Rekognition, so `fn-lost-pet` isn't in the trust policy of `ecoguard-rekognition-detect`. `boto3` is in `requirements.txt` only because `ecoguard_ml.detect`, whose `model_config()` reads `config/model`, imports the Rekognition module.

Keep these tables to what the code actually uses. Member 1 reviews them before Gate 4.

## Test
```bash
cd functions/ml/lost_pet && python -m pytest   # this function
cd functions/ml && python -m pytest tests      # ecoguard_ml, which it shares with tagging
```

## Deploy (a person runs this)
First check that all four `sightings` indexes in `infra/gcp/firestore.indexes.json` are `READY`; a query whose index is still building fails with a 500:
```bash
gcloud firestore indexes composite list --project=ecoguard-g21
```
Then:
```bash
cd functions/ml/lost_pet
rm -rf ecoguard_common ecoguard_ml
cp -r ../../../shared/python/ecoguard_common ./   # gitignored copies of the shared packages
cp -r ../ecoguard_ml ./
cp ../../../shared/tags.json ecoguard_common/    # lost_pet_species and lost_pet_colours (tag_match.load_tags)
gcloud functions deploy lost-pet \
  --gen2 --runtime=python312 --region=us-east1 --memory=512Mi \
  --source=. --entry-point=handler --trigger-http \
  --service-account=fn-lost-pet@ecoguard-g21.iam.gserviceaccount.com \
  --no-allow-unauthenticated
cd ../../.. && infra/gcp/ml.sh   # the gateway's Invoker grant, once the service exists
```

## Check it works
Call the Cloud Run URL directly, as the gateway would. Your own identity token gets past `--no-allow-unauthenticated` (as a project owner you hold Invoker), and the `X-Apigateway-Api-Userinfo` header stands in for the claims the gateway forwards. A public photo with a cat must have been uploaded and tagged first, so a `sightings` document exists.

1. List both buckets before the search:
   ```bash
   gcloud storage ls -r gs://ecoguard-g21-media gs://ecoguard-g21-derived > /tmp/before.txt
   ```
2. Search with a cat photo from the test set:
   ```bash
   URL=$(gcloud functions describe lost-pet --region=us-east1 --format='value(serviceConfig.uri)')
   USERINFO=$(printf '{"sub":"manual-test"}' | base64 | tr '+/' '-_' | tr -d '=\n')
   printf '{"image_base64":"%s","species":"cat","since_days":365}' \
     "$(base64 < tools/testset/data/images/cat/cat_001.jpg | tr -d '\n')" > /tmp/query.json
   curl -s -X POST "$URL" \
     -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
     -H "X-Apigateway-Api-Userinfo: $USERINFO" \
     -H "Content-Type: application/json" \
     --data-binary @/tmp/query.json | python3 -m json.tool
   ```
   Expect public files with a cat in `results`, best `score` first. Searching with the very photo that was uploaded should put its file first with a score near 1.
3. Search by description, with no photo:
   ```bash
   curl -s -X POST "$URL" \
     -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
     -H "X-Apigateway-Api-Userinfo: $USERINFO" \
     -H "Content-Type: application/json" \
     -d '{"species":"cat","colour":"ginger","since_days":365}' | python3 -m json.tool
   ```
   Expect ginger cat sightings, newest first, each with `"score": null`.
4. List both buckets again. No line should differ:
   ```bash
   gcloud storage ls -r gs://ecoguard-g21-media gs://ecoguard-g21-derived > /tmp/after.txt
   diff /tmp/before.txt /tmp/after.txt && echo "nothing stored"
   ```
5. The log line has only the request fields and a count:
   ```bash
   gcloud functions logs read lost-pet --region=us-east1 --limit=5   # look for "lost pet search"
   ```

The photo is posted from a file (`--data-binary @/tmp/query.json`) because its base64 is too long for a command-line argument.
