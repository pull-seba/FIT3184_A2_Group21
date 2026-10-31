# search_by_file

Owner: member 3 · Rubric: 2.2.3

## What it does
`POST /search/by-file`: the user sends a photo, and gets back every stored file that shows the same species.

```json
{ "file_base64": "<base64>", "content_type": "image/jpeg" }
```
Response: `{"detected_tags": {"fox": 2}, "results": [FileSummary, ...]}`, newest first, with fresh 60-minute signed `GET` URLs (`docs/contracts/api-routes.md`).

- **Detection:** the photo is tagged by `../ecoguard_ml/detect.py`, the same code, detector (Rekognition) and `config/model` thresholds that tag uploads, so a photo gets the tags it would get if it were uploaded.
- **Matched by species, not count:** the spec says it "discovers the list of all species (tags) in the uploaded file, then finds all files in the database that contain that set of tags". So every detected species becomes a minimum of 1: a photo of two foxes finds a file with one fox. Two species must both be in a file (AND). The rule itself is member 4's `ecoguard_common.tag_match.matches()`, the one `/search/tags` uses, so only `active` records match. `detected_tags` still reports the counts as detected.
- **Nothing detected:** `{"detected_tags": {}, "results": []}`, without querying Firestore.
- **Never stored:** the photo stays in memory. This function makes no Cloud Storage or Firestore write, and logs only the detected tags and the result count, never the image. `test_a_full_search_makes_no_write_to_firestore_or_storage` checks every call a full search makes. Rekognition analyses the bytes and keeps nothing.
- **Formats:** JPEG, PNG and WebP up to 20 MB (`ecoguard_common.uploads.ACCEPTED`). Videos can't be searched by file.
- **Shared code to move later:** `search()`, `signed_get_url()` and `file_summary()` are copied from member 4's `search/tag_query`, so `FileSummary` is built the same way on every route. They should move into `ecoguard_common` after the demo.

| Status | Code | When |
| --- | --- | --- |
| 204 | | `OPTIONS` preflight, with the CORS headers from `infra/gateway/README.md` |
| 400 | `bad_json`, `bad_file`, `bad_content_type`, `bad_base64` | Body isn't a JSON object, a field is missing or the wrong type, or the base64 doesn't decode |
| 400 | `bad_image` | Pillow or Rekognition can't read the photo |
| 401 | `unauthenticated` | No gateway user (`ecoguard_common.auth.get_user`) |
| 413 | `too_large` | Decoded photo over 20 MB |
| 415 | `unsupported_type` | `content_type` isn't `image/jpeg`, `image/png` or `image/webp` |
| 500 | `internal` | Anything else (logged) |

Every response carries `Access-Control-Allow-Origin: *`.

## Route
`POST /search/by-file` through API Gateway (`infra/gateway/openapi.yaml`, member 1), which checks the Cognito ID token and calls the `search-by-file` function as `ecoguard-gateway`.

## Service account
`fn-search-by-file@ecoguard-g21.iam.gserviceaccount.com`, created and granted by `infra/gcp/ml.sh`.

| Role | On | Why |
| --- | --- | --- |
| `roles/datastore.viewer` | project | Reads `config/model` and queries `files`. No write role, so it can't store anything in Firestore |
| `roles/storage.objectViewer` | media bucket | A signed URL reads as the account that signed it: originals |
| `roles/storage.objectViewer` | derived bucket | The same, for thumbnails |
| `roles/iam.serviceAccountTokenCreator` | itself | Signs URLs through the IAM credentials API, without a key file |
| `roles/run.invoker` (held by `ecoguard-gateway`) | `search-by-file` service | Only the gateway may call it |

**AWS:** like tagging, it swaps its Google ID token for one-hour credentials on `ecoguard-rekognition-detect`, which may call only `rekognition:DetectLabels` in `us-east-1`. The role's trust policy already lists `fn-search-by-file` (`aws/iam/rekognition-detect-trust.json`, cross-cloud link 4). No AWS keys anywhere.

Keep these tables to what the code actually uses. Member 1 reviews them before Gate 4.

## Test
```bash
cd functions/ml/search_by_file && python -m pytest   # this function
cd functions/ml && python -m pytest tests            # ecoguard_ml, which it shares with tagging
```

## Deploy (a person runs this)
The role ARN is written out in full: in zsh, `$ACCOUNT:role` loses the `:r`.
```bash
cd functions/ml/search_by_file
rm -rf ecoguard_common ecoguard_ml
cp -r ../../../shared/python/ecoguard_common ./   # gitignored copies of the shared packages
cp -r ../ecoguard_ml ./
cp ../../../shared/tags.json ecoguard_ml/         # the label map detect reads
gcloud functions deploy search-by-file \
  --gen2 --runtime=python312 --region=us-east1 --memory=512Mi \
  --source=. --entry-point=handler --trigger-http \
  --service-account=fn-search-by-file@ecoguard-g21.iam.gserviceaccount.com \
  --set-env-vars="REKOGNITION_ROLE_ARN=arn:aws:iam::686890423796:role/ecoguard-rekognition-detect" \
  --no-allow-unauthenticated
cd ../../.. && infra/gcp/ml.sh   # the gateway's Invoker grant, once the service exists
```

## Check it works
Call the Cloud Run URL directly, as the gateway would. Your own identity token gets past `--no-allow-unauthenticated` (as a project owner you hold Invoker), and the `X-Apigateway-Api-Userinfo` header stands in for the claims the gateway forwards.

1. List both buckets before the search:
   ```bash
   gcloud storage ls -r gs://ecoguard-g21-media gs://ecoguard-g21-derived > /tmp/before.txt
   ```
2. Search with a two-fox photo from the test set:
   ```bash
   URL=$(gcloud functions describe search-by-file --region=us-east1 --format='value(serviceConfig.uri)')
   USERINFO=$(printf '{"sub":"manual-test"}' | base64 | tr '+/' '-_' | tr -d '=\n')
   printf '{"file_base64":"%s","content_type":"image/jpeg"}' \
     "$(base64 < tools/testset/data/images/fox/fox_020.jpg | tr -d '\n')" > /tmp/query.json
   curl -s -X POST "$URL" \
     -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
     -H "X-Apigateway-Api-Userinfo: $USERINFO" \
     -H "Content-Type: application/json" \
     --data-binary @/tmp/query.json | python3 -m json.tool
   ```
   Expect `detected_tags` with `fox`, and every active file tagged `fox` in `results`, newest first.
3. List both buckets again. No line should differ:
   ```bash
   gcloud storage ls -r gs://ecoguard-g21-media gs://ecoguard-g21-derived > /tmp/after.txt
   diff /tmp/before.txt /tmp/after.txt && echo "nothing stored"
   ```
4. The log line has only the tags and a count:
   ```bash
   gcloud functions logs read search-by-file --region=us-east1 --limit=5   # look for "search by file"
   ```

The photo is posted from a file (`--data-binary @/tmp/query.json`) because its base64 is too long for a command-line argument.
