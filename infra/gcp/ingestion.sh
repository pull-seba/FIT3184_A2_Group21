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

UPLOAD_INIT=$(service_account fn-upload-init "upload_init (member 2)")
PROCESS_UPLOAD=$(service_account fn-process-upload "process_upload (member 2)")
DELETE_FILES=$(service_account fn-delete-files "delete_files (member 2)")

# A signed URL acts with its signer's permissions, so upload_init needs whatever its URLs do: PUT new
# originals, and GET the original and thumbnail when it answers "duplicate" with a FileSummary.
bucket_role "$MEDIA_BUCKET" "$UPLOAD_INIT" roles/storage.objectCreator
bucket_role "$MEDIA_BUCKET" "$UPLOAD_INIT" roles/storage.objectViewer
bucket_role "$DERIVED_BUCKET" "$UPLOAD_INIT" roles/storage.objectViewer

# process_upload reads each new original to hash it and deletes rejected ones. objectUser is the
# narrowest predefined role that includes delete.
bucket_role "$MEDIA_BUCKET" "$PROCESS_UPLOAD" roles/storage.objectUser

# ---- Needs Project IAM Admin and Service Account Admin (or Owner) ----
project_role() {
  retry gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="$1" --role="$2" --condition=None >/dev/null
}
# Firestore roles can only be granted on the project. upload_init only reads (the duplicate check);
# process_upload also merges the base record.
project_role "serviceAccount:$UPLOAD_INIT" roles/datastore.viewer
project_role "serviceAccount:$PROCESS_UPLOAD" roles/datastore.user
# Signing without a key file goes through the IAM credentials API, which needs Token Creator on itself.
gcloud iam service-accounts add-iam-policy-binding "$UPLOAD_INIT" --project="$PROJECT_ID" \
  --member="serviceAccount:$UPLOAD_INIT" --role=roles/iam.serviceAccountTokenCreator >/dev/null

# The upload trigger: Cloud Storage publishes each event to Pub/Sub through its service agent (one grant
# covers every storage trigger in the project, member 3's too), and Eventarc delivers it to the function
# as process_upload's own account. Asking for the service agent creates it the first time, but in a new
# project IAM took over an hour to accept it (27 Oct), so this grant warns instead of stopping the script.
# IAM can still reject it after the grant exists, so it's skipped once the grant is there.
STORAGE_AGENT=$(gcloud storage service-agent --project="$PROJECT_ID")
has_project_role() {
  gcloud projects get-iam-policy "$PROJECT_ID" --flatten="bindings[].members" \
    --filter="bindings.role=$2 AND bindings.members=$1" --format="value(bindings.role)" | grep -q .
}
has_project_role "serviceAccount:$STORAGE_AGENT" roles/pubsub.publisher ||
  project_role "serviceAccount:$STORAGE_AGENT" roles/pubsub.publisher 2>/dev/null ||
  echo "IAM doesn't know $STORAGE_AGENT yet: wait a few minutes and re-run this script before deploying process-upload." >&2
project_role "serviceAccount:$PROCESS_UPLOAD" roles/eventarc.eventReceiver
# The function allows no unauthenticated calls, so the trigger's account needs Invoker on its service,
# which exists only after the first deploy.
if gcloud run services describe process-upload --project="$PROJECT_ID" --region="$REGION" >/dev/null 2>&1; then
  gcloud run services add-iam-policy-binding process-upload --project="$PROJECT_ID" --region="$REGION" \
    --member="serviceAccount:$PROCESS_UPLOAD" --role=roles/run.invoker >/dev/null
else
  echo "process-upload isn't deployed yet: deploy it, then re-run this script for its Invoker grant." >&2
fi

# delete_files lists and deletes each file's objects in both buckets, and deletes its record and
# sightings. objectUser is the narrowest predefined role that includes delete.
bucket_role "$MEDIA_BUCKET" "$DELETE_FILES" roles/storage.objectUser
bucket_role "$DERIVED_BUCKET" "$DELETE_FILES" roles/storage.objectUser
project_role "serviceAccount:$DELETE_FILES" roles/datastore.user

# The gateway calls each HTTP function as its own account (infra/gateway/README.md), and only it may.
GATEWAY="ecoguard-gateway@$PROJECT_ID.iam.gserviceaccount.com"
for function in upload-init delete-files; do
  if gcloud run services describe "$function" --project="$PROJECT_ID" --region="$REGION" >/dev/null 2>&1; then
    gcloud run services add-iam-policy-binding "$function" --project="$PROJECT_ID" --region="$REGION" \
      --member="serviceAccount:$GATEWAY" --role=roles/run.invoker >/dev/null
  else
    echo "$function isn't deployed yet: deploy it, then re-run this script for the gateway's Invoker grant." >&2
  fi
done

echo "Ingestion resources ready: gs://$MEDIA_BUCKET, gs://$DERIVED_BUCKET, $UPLOAD_INIT, $PROCESS_UPLOAD, $DELETE_FILES"
