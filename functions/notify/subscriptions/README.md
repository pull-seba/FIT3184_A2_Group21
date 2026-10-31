# subscriptions

Owner: member 1 · Rubric: 2.3.3

## What it does
Backs the Alerts page. `GET /notifications/subscriptions` returns the caller's alert tags, and `PUT` with `{"tags": ["fox", "cane toad"]}` replaces them. Both answer `{"tags": [...]}`. Tags are checked against `shared/tags.json` (`400 unknown_tag`).

The tags are the filter policy on the caller's SNS email subscription to `ecoguard-tag-alerts`, so SNS is the one place they live. The email comes only from the verified ID token.

| Caller's state | `PUT` with tags | `PUT` with no tags |
| --- | --- | --- |
| Not subscribed | Subscribes with the filter; SNS sends a confirmation email | Nothing |
| Unconfirmed | Same tags: nothing changes. Different tags: `409 confirm_first` | Nothing |
| Confirmed | Replaces the filter | Unsubscribes |

Known limitation: SNS gives no ARN for an unconfirmed subscription, so `GET` returns no tags until the email is confirmed.

## Trigger
HTTP, through API Gateway only (`--no-allow-unauthenticated`).

## Cross-cloud auth
No AWS keys. The function gets a Google ID token for its own service account, with the role ARN as the audience, and AWS STS swaps it (`AssumeRoleWithWebIdentity`) for one-hour credentials on `ecoguard-subscriptions`. The role trusts only this service account (`aws/iam/subscriptions-trust.json`) and can only manage subscriptions on this topic (`aws/iam/subscriptions.json`).

## Service account
`fn-subscriptions@ecoguard-g21.iam.gserviceaccount.com` holds no GCP roles: it reads no GCP data, and only needs its own identity to get the token.

## Environment
| Name | Value |
| --- | --- |
| `SUBSCRIPTIONS_ROLE_ARN` | `SubscriptionsRoleArn` output of the `ecoguard-notify` stack |
| `TOPIC_ARN` | `TopicArn` output of the `ecoguard-notify` stack |

## Test
```bash
python -m pytest
```

## Deploy (a person runs this)
1. Create the service account and get its unique ID:
   ```bash
   gcloud iam service-accounts create fn-subscriptions --project=ecoguard-g21
   gcloud iam service-accounts describe fn-subscriptions@ecoguard-g21.iam.gserviceaccount.com --format='value(uniqueId)'
   ```
2. Create the AWS role from the repo root. The stack keeps its other parameters, and the Lambda's pasted code stays because its `Code` in the template hasn't changed:
   ```bash
   aws cloudformation deploy --template-file aws/notify/template.yaml --stack-name ecoguard-notify --region us-east-1 \
     --capabilities CAPABILITY_NAMED_IAM --parameter-overrides SubscriptionsAccountId=<unique ID>
   aws cloudformation describe-stacks --stack-name ecoguard-notify --region us-east-1 --query "Stacks[0].Outputs"
   ```
3. Deploy the function from this folder, and let only the gateway call it:
   ```bash
   cp -r ../../../shared/python/ecoguard_common .   # gitignored copy of the shared package
   cp ../../../shared/tags.json ecoguard_common/    # the tag list tag_match reads
   gcloud functions deploy subscriptions \
     --gen2 --runtime=python312 --region=us-east1 \
     --source=. --entry-point=handler --trigger-http --no-allow-unauthenticated \
     --service-account=fn-subscriptions@ecoguard-g21.iam.gserviceaccount.com \
     --set-env-vars=SUBSCRIPTIONS_ROLE_ARN=<role ARN>,TOPIC_ARN=<topic ARN>
   gcloud functions add-invoker-policy-binding subscriptions \
     --region=us-east1 \
     --member=serviceAccount:ecoguard-gateway@ecoguard-g21.iam.gserviceaccount.com
   ```

The gateway already routes to this function, so `infra/gateway/openapi.yaml` doesn't change.
