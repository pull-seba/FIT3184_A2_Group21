#!/usr/bin/env bash
# Member 4's GCP resources: one service account per search function holding only the roles in its
# README, then each function's deploy and the gateway's Invoker grant on it.
# Run after setup.sh and member 2's ingestion.sh (buckets). Needs Project IAM Admin, Service Account
# Admin and Cloud Run Admin (or Owner). Safe to re-run.
# Usage: infra/gcp/search.sh
set -euo pipefail

PROJECT_ID=${PROJECT_ID:-ecoguard-g21}
REGION=${REGION:-us-east1}
MEDIA_BUCKET="$PROJECT_ID-media"
DERIVED_BUCKET="$PROJECT_ID-derived"
GATEWAY="ecoguard-gateway@$PROJECT_ID.iam.gserviceaccount.com"
ROOT=$(cd "$(dirname "$0")/../.." && pwd)

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
# Signing without a key file goes through the IAM credentials API, which needs Token Creator on itself.
signs_urls() {
  retry gcloud iam service-accounts add-iam-policy-binding "$1" --project="$PROJECT_ID" \
    --member="serviceAccount:$1" --role=roles/iam.serviceAccountTokenCreator >/dev/null
}

TAG_QUERY=$(service_account fn-tag-query "tag_query (member 4)")
THUMBNAIL_LOOKUP=$(service_account fn-thumbnail-lookup "thumbnail_lookup (member 4)")
BULK_TAGS=$(service_account fn-bulk-tags "bulk_tags (member 4)")

# tag_query reads records and signs GET URLs for originals and thumbnails.
project_role "$TAG_QUERY" roles/datastore.viewer
bucket_role "$MEDIA_BUCKET" "$TAG_QUERY" roles/storage.objectViewer
bucket_role "$DERIVED_BUCKET" "$TAG_QUERY" roles/storage.objectViewer
signs_urls "$TAG_QUERY"

# thumbnail_lookup reads records and signs GET URLs for originals only.
project_role "$THUMBNAIL_LOOKUP" roles/datastore.viewer
bucket_role "$MEDIA_BUCKET" "$THUMBNAIL_LOOKUP" roles/storage.objectViewer
signs_urls "$THUMBNAIL_LOOKUP"

# bulk_tags reads each file's status and updates its tags. It signs nothing and touches no bucket.
project_role "$BULK_TAGS" roles/datastore.user

deploy() {
  local folder="$ROOT/functions/search/$1" name=${1//_/-}
  # Gitignored copies of the shared package and the tag list tag_match reads.
  cp -r "$ROOT/shared/python/ecoguard_common" "$folder/"
  cp "$ROOT/shared/tags.json" "$folder/ecoguard_common/"
  gcloud functions deploy "$name" --project="$PROJECT_ID" --region="$REGION" \
    --gen2 --runtime=python312 --source="$folder" --entry-point=handler --trigger-http \
    --no-allow-unauthenticated --service-account="$2"
  # Only the gateway may call it (infra/gateway/README.md).
  gcloud run services add-iam-policy-binding "$name" --project="$PROJECT_ID" --region="$REGION" \
    --member="serviceAccount:$GATEWAY" --role=roles/run.invoker >/dev/null
}

deploy tag_query "$TAG_QUERY"
deploy thumbnail_lookup "$THUMBNAIL_LOOKUP"
deploy bulk_tags "$BULK_TAGS"

echo "Search functions deployed: tag-query, thumbnail-lookup, bulk-tags"
