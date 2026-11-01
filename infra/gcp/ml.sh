#!/usr/bin/env bash
# Member 3's GCP resources: one service account per ML function, holding only the roles it uses.
# Run after setup.sh and member 2's ingestion.sh (buckets, frames-ready topic, storage trigger grant).
# Needs Project IAM Admin and Service Account Admin (or Owner). Safe to re-run.
# Usage: infra/gcp/ml.sh
set -euo pipefail

PROJECT_ID=${PROJECT_ID:-ecoguard-g21}
REGION=${REGION:-us-east1}
MEDIA_BUCKET="$PROJECT_ID-media"
DERIVED_BUCKET="$PROJECT_ID-derived"

service_account() {
  local email="$1@$PROJECT_ID.iam.gserviceaccount.com"
  gcloud iam service-accounts describe "$email" --project="$PROJECT_ID" >/dev/null 2>&1 ||
    gcloud iam service-accounts create "$1" --project="$PROJECT_ID" --display-name="$2" >/dev/null
  echo "$email"
}
# A new account takes a few seconds to reach IAM, so its grants retry briefly.
retry() {
  for _ in 1 2 3 4 5 6; do
    "$@" && return
    sleep 5
  done
  return 1
}
bucket_role() {
  retry gcloud storage buckets add-iam-policy-binding "gs://$1" --member="serviceAccount:$2" --role="$3" >/dev/null
}
project_role() {
  retry gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$1" --role="$2" \
    --condition=None >/dev/null
}
# Lets $2 call Cloud Run service $1. The service exists only after its first deploy.
invoker() {
  if gcloud run services describe "$1" --project="$PROJECT_ID" --region="$REGION" >/dev/null 2>&1; then
    gcloud run services add-iam-policy-binding "$1" --project="$PROJECT_ID" --region="$REGION" \
      --member="serviceAccount:$2" --role=roles/run.invoker >/dev/null
  else
    echo "$1 isn't deployed yet: deploy it, then re-run this script for its Invoker grant." >&2
  fi
}

TAGGING=$(service_account fn-tagging "tagging (member 3)")
SEARCH_BY_FILE=$(service_account fn-search-by-file "search_by_file (member 3)")
LOST_PET=$(service_account fn-lost-pet "lost_pet (member 3)")
GATEWAY="ecoguard-gateway@$PROJECT_ID.iam.gserviceaccount.com" # member 1's, see infra/gateway

# tagging reads each new image and each video's frames. Read only: it never writes to storage.
bucket_role "$MEDIA_BUCKET" "$TAGGING" roles/storage.objectViewer
bucket_role "$DERIVED_BUCKET" "$TAGGING" roles/storage.objectViewer
# Reads config/model and files/<id>, writes its tag fields and sightings. Firestore roles exist only on the project.
project_role "$TAGGING" roles/datastore.user
# Embeds each cat or dog crop, and the colour words, with Vertex AI (lost pet sightings).
project_role "$TAGGING" roles/aiplatform.user
# Receives the media bucket's events as the trigger's service account.
project_role "$TAGGING" roles/eventarc.eventReceiver

# Both triggers call their function as fn-tagging, and the functions allow no unauthenticated calls.
invoker tagging "$TAGGING"
invoker tagging-frames "$TAGGING"

# search_by_file reads files/<id> to match tags. Read only: the query photo is never stored.
project_role "$SEARCH_BY_FILE" roles/datastore.viewer
# A signed URL reads as the account that signed it, so it needs read access to originals and thumbnails.
bucket_role "$MEDIA_BUCKET" "$SEARCH_BY_FILE" roles/storage.objectViewer
bucket_role "$DERIVED_BUCKET" "$SEARCH_BY_FILE" roles/storage.objectViewer
# Signing without a key file goes through the IAM credentials API, which needs Token Creator on itself.
retry gcloud iam service-accounts add-iam-policy-binding "$SEARCH_BY_FILE" --project="$PROJECT_ID" \
  --member="serviceAccount:$SEARCH_BY_FILE" --role=roles/iam.serviceAccountTokenCreator >/dev/null
# Only the gateway calls search-by-file (POST /search/by-file).
invoker search-by-file "$GATEWAY"

# lost_pet reads sightings, files/<id> and config/model. Read only: the query photo is never stored.
project_role "$LOST_PET" roles/datastore.viewer
# Embeds the query photo with Vertex AI, the model that embedded every sighting.
project_role "$LOST_PET" roles/aiplatform.user
# Signed URLs for originals and thumbnails, as for search_by_file.
bucket_role "$MEDIA_BUCKET" "$LOST_PET" roles/storage.objectViewer
bucket_role "$DERIVED_BUCKET" "$LOST_PET" roles/storage.objectViewer
retry gcloud iam service-accounts add-iam-policy-binding "$LOST_PET" --project="$PROJECT_ID" \
  --member="serviceAccount:$LOST_PET" --role=roles/iam.serviceAccountTokenCreator >/dev/null
# Only the gateway calls lost-pet (POST /search/lost-pet). No AWS role: it never calls Rekognition.
invoker lost-pet "$GATEWAY"

# The AWS role trusts these IDs (aws/iam/rekognition-detect-trust.json, cross-cloud link 4).
echo "Unique IDs for the AWS trust policy:"
for email in "$TAGGING" "$SEARCH_BY_FILE"; do
  echo "  $email $(gcloud iam service-accounts describe "$email" --project="$PROJECT_ID" --format='value(uniqueId)')"
done
