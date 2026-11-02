# subscriptions

Owner: member 1 · Rubric: 2.3.3 · Routes: `GET` and `PUT /notifications/subscriptions`

## What it does
Reads and replaces the caller's alert tags. The tags are the filter policy on the caller's email subscription to SNS topic `ecoguard-tag-alerts` (`docs/decisions.md`, 30 Oct). The email comes from the verified ID token, so nobody can change someone else's alerts.

The function holds no AWS keys. It gets a Google ID token for its own service account and swaps it with AWS STS for one-hour credentials on role `ecoguard-subscriptions` (`aws/iam/subscriptions.json`), which can only manage that topic's subscriptions.

## Environment
Both values come from the outputs of the **same** `ecoguard-notify` CloudFormation stack (`aws/notify/template.yaml`), in the AWS account and region (`us-east-1`) where that stack is deployed.

| Variable | Stack output |
| --- | --- |
| `TOPIC_ARN` | `TopicArn` |
| `SUBSCRIPTIONS_ROLE_ARN` | `SubscriptionsRoleArn` |

The role can only touch the topic in its own account, so the two ARNs must share an account ID. If `TOPIC_ARN` names a topic in another account, or one that was deleted, every call returns `500` and the log shows `subscriptions failed: ... Topic does not exist`.

## Service account
`fn-subscriptions@ecoguard-g21.iam.gserviceaccount.com`

It needs no GCP roles: fetching its own ID token from the metadata server needs no permission. Its unique ID is the `SubscriptionsAccountId` parameter of the `ecoguard-notify` stack, which locks the AWS role to this one account (`aws/iam/subscriptions-trust.json`). Only the gateway's service account has `roles/run.invoker` on the service.

## Test
```bash
python -m pytest
```

## Deploy
1. In AWS CloudShell (`us-east-1`), print the two values:
   ```bash
   aws cloudformation describe-stacks --region us-east-1 --stack-name ecoguard-notify \
     --query "Stacks[0].Outputs[?OutputKey=='TopicArn' || OutputKey=='SubscriptionsRoleArn'].[OutputKey,OutputValue]" \
     --output table
   ```
   No `SubscriptionsRoleArn` output means the stack's `SubscriptionsAccountId` parameter is empty: update the stack with the value of `gcloud iam service-accounts describe fn-subscriptions@ecoguard-g21.iam.gserviceaccount.com --format='value(uniqueId)'`.
2. In GCP Cloud Shell, from this folder, deploy with those values:
   ```bash
   cp -r ../../../shared/python/ecoguard_common .   # gitignored copy of the shared package
   gcloud functions deploy subscriptions \
     --gen2 --runtime=python312 --region=us-east1 \
     --source=. --entry-point=handler --trigger-http --no-allow-unauthenticated \
     --service-account=fn-subscriptions@ecoguard-g21.iam.gserviceaccount.com \
     --set-env-vars=TOPIC_ARN=<TopicArn>,SUBSCRIPTIONS_ROLE_ARN=<SubscriptionsRoleArn>
   ```
3. Check the deployed values match step 1:
   ```bash
   gcloud functions describe subscriptions --region=us-east1 \
     --format='value(serviceConfig.environmentVariables)'
   ```

## Try it (demo)
1. On the **Alerts** page, choose `fox` and save. AWS emails a confirmation link: confirm it.
2. Reload the page: `fox` is still selected (`GET` reads the filter policy back from SNS).
3. Upload a photo with a fox and a cat. One email arrives naming the fox; nobody subscribed only to other tags gets one.
