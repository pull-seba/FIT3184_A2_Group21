#!/usr/bin/env bash
# Member 2's GCP resources: the media and derived buckets, CORS so the browser can upload, and one
# service account per ingestion function holding only the roles that function uses.
# Run after setup.sh. Buckets and accounts need Editor; the last section also needs Project IAM Admin
# and Service Account Admin (or Owner). Safe to re-run: each step skips what exists or repeats harmlessly.
# Usage: infra/gcp/ingestion.sh
set -euo pipefail

PROJECT_ID=${PROJECT_ID:-ecoguard-g21}
REGION=${REGION:-us-east1} # with Firestore; a storage trigger must be in its bucket's region
MEDIA_BUCKET="$PROJECT_ID-media"
DERIVED_BUCKET="$PROJECT_ID-derived"
HERE=$(cd "$(dirname "$0")" && pwd)

# Private buckets, as in docs/contracts/storage-layout.md. Soft delete is off so a deleted file is gone
# at once: rubric 2.3.2 checks storage is clean, and soft-deleted objects are still billed for 7 days.
for bucket in "$MEDIA_BUCKET" "$DERIVED_BUCKET"; do
  gcloud storage buckets describe "gs://$bucket" >/dev/null 2>&1 ||
    gcloud storage buckets create "gs://$bucket" --project="$PROJECT_ID" --location="$REGION" \
      --uniform-bucket-level-access --public-access-prevention --soft-delete-duration=0
done

# The browser PUTs straight to the media bucket with the signed headers, so they must pass CORS.
# Origins: the Angular dev server; add the Firebase Hosting domain once member 1 sets it up.
gcloud storage buckets update "gs://$MEDIA_BUCKET" --cors-file="$HERE/cors-media.json"

# One account per function, named fn-<function-name> (.claude/rules/infra.md). Prints its email.
service_account() {
  local email="$1@$PROJECT_ID.iam.gserviceaccount.com"
  gcloud iam service-accounts describe "$email" --project="$PROJECT_ID" >/dev/null 2>&1 ||
    gcloud iam service-accounts create "$1" --project="$PROJECT_ID" --display-name="$2" >/dev/null
  echo "$email"
}
# A new account takes a few seconds to reach IAM ("does not exist"), so its grants retry briefly.
bucket_role() {
  for _ in 1 2 3 4 5 6; do
    gcloud storage buckets add-iam-policy-binding "gs://$1" --member="serviceAccount:$2" --role="$3" >/dev/null && return
    sleep 5
  done
  return 1
}

UPLOAD_INIT=$(service_account fn-upload-init "upload_init (member 2)")

# A signed URL acts with its signer's permissions, so upload_init needs whatever its URLs do: PUT new
# originals, and GET the original and thumbnail when it answers "duplicate" with a FileSummary.
bucket_role "$MEDIA_BUCKET" "$UPLOAD_INIT" roles/storage.objectCreator
bucket_role "$MEDIA_BUCKET" "$UPLOAD_INIT" roles/storage.objectViewer
bucket_role "$DERIVED_BUCKET" "$UPLOAD_INIT" roles/storage.objectViewer

# ---- Needs Project IAM Admin and Service Account Admin (or Owner) ----
# Read files/<sha256> for the duplicate check. Firestore roles can only be granted on the project.
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$UPLOAD_INIT" \
  --role=roles/datastore.viewer --condition=None >/dev/null
# Signing without a key file goes through the IAM credentials API, which needs Token Creator on itself.
gcloud iam service-accounts add-iam-policy-binding "$UPLOAD_INIT" --project="$PROJECT_ID" \
  --member="serviceAccount:$UPLOAD_INIT" --role=roles/iam.serviceAccountTokenCreator >/dev/null

echo "Ingestion resources ready: gs://$MEDIA_BUCKET, gs://$DERIVED_BUCKET, $UPLOAD_INIT"
