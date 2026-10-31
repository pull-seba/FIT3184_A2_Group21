#!/usr/bin/env bash
# One-off setup of the team's GCP project, run once by the project owner (needs billing admin on
# the billing account). Teammates don't run this; they only need IAM access to the project.
# Safe to re-run: each step skips what already exists.
# Usage: BILLING_ACCOUNT=XXXXXX-XXXXXX-XXXXXX infra/gcp/setup.sh
set -euo pipefail

PROJECT_ID=${PROJECT_ID:-ecoguard-g21}
BILLING_ACCOUNT=${BILLING_ACCOUNT:?set BILLING_ACCOUNT to the billing account ID}
REGION=${REGION:-us-east1} # next to the AWS side (us-east-1) and inside the Cloud Storage free tier
BUDGET=${BUDGET:-10}       # alert threshold, in the billing account's currency

gcloud projects describe "$PROJECT_ID" >/dev/null 2>&1 ||
  gcloud projects create "$PROJECT_ID" --name="Aussie EcoGuard G21"
# Re-linking an already linked project still counts against the account's project quota, so skip it.
[ "$(gcloud billing projects describe "$PROJECT_ID" --format='value(billingAccountName)')" = "billingAccounts/$BILLING_ACCOUNT" ] ||
  gcloud billing projects link "$PROJECT_ID" --billing-account="$BILLING_ACCOUNT"

# Storage + Firestore, Cloud Run functions (built by Cloud Build), upload triggers (Eventarc),
# notifications (Pub/Sub), API Gateway, signed URLs (IAM credentials), lost pet embeddings (Vertex AI)
# and the budget below.
gcloud services enable --project="$PROJECT_ID" \
  storage.googleapis.com firestore.googleapis.com \
  cloudfunctions.googleapis.com run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  eventarc.googleapis.com pubsub.googleapis.com \
  apigateway.googleapis.com servicemanagement.googleapis.com servicecontrol.googleapis.com \
  iamcredentials.googleapis.com billingbudgets.googleapis.com aiplatform.googleapis.com

gcloud firestore databases describe --project="$PROJECT_ID" >/dev/null 2>&1 ||
  gcloud firestore databases create --project="$PROJECT_ID" --location="$REGION" --type=firestore-native

# Emails the billing admins at 50%, 90% and 100% of the budget. The lookup is assigned first so a
# failed lookup stops the script instead of reading as "no budget" and creating a duplicate.
budget=$(gcloud billing budgets list --billing-account="$BILLING_ACCOUNT" --billing-project="$PROJECT_ID" \
  --filter="displayName=$PROJECT_ID" --format='value(name)')
[ -n "$budget" ] ||
  gcloud billing budgets create --billing-account="$BILLING_ACCOUNT" --billing-project="$PROJECT_ID" \
    --display-name="$PROJECT_ID" --budget-amount="$BUDGET" --filter-projects="projects/$PROJECT_ID" \
    --threshold-rule=percent=0.5 --threshold-rule=percent=0.9 --threshold-rule=percent=1.0
