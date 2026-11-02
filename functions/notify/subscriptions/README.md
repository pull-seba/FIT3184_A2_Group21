# subscriptions

Owner: member 1 · Rubric: 2.3.3 · Routes: `GET` and `PUT /notifications/subscriptions`

## What it does
Reads and replaces the caller's alert tags. The tags are the filter policy on the caller's email subscription to SNS topic `ecoguard-tag-alerts` (`docs/decisions.md`, 30 Oct). The email comes from the verified ID token, so nobody can change someone else's alerts.

The function holds no AWS keys. It gets a Google ID token for its own service account and swaps it with AWS STS for one-hour credentials on role `ecoguard-subscriptions` (`aws/iam/subscriptions.json`), which can only manage that topic's subscriptions.

## Environment
Both values are in the team AWS account `620444454234`, region `us-east-1`.

| Variable | Value |
| --- | --- |
| `TOPIC_ARN` | `arn:aws:sns:us-east-1:620444454234:ecoguard-tag-alerts` (the `ecoguard-notify` stack's `TopicArn` output) |
| `SUBSCRIPTIONS_ROLE_ARN` | `arn:aws:iam::620444454234:role/ecoguard-subscriptions` |

The role can only touch the topic in its own account, so the two ARNs must share an account ID. If `TOPIC_ARN` names a topic in another account, or one that was deleted, every call returns `500` and the log shows `subscriptions failed: ... Topic does not exist`.

In the team account the role was created by hand from `aws/iam/subscriptions-trust.json` and `aws/iam/subscriptions.json` (inline policy `sns-subscriptions`), not by the stack, which has no `SubscriptionsAccountId`. So a policy change is applied to the role directly, after filling in `<account-id>`:
```bash
aws iam put-role-policy --role-name ecoguard-subscriptions --policy-name sns-subscriptions \
  --policy-document file://subscriptions.json
```
SNS checks every subscription action, including `GetSubscriptionAttributes` on one subscription, against the topic's ARN. A policy on `ecoguard-tag-alerts:*` matches nothing, and the page fails with `AuthorizationError` as soon as a subscription is confirmed.

## Service account
`fn-subscriptions@ecoguard-g21.iam.gserviceaccount.com`

It needs no GCP roles: fetching its own ID token from the metadata server needs no permission. Its unique ID, `107414905691117902383`, is the `sub` in the role's trust policy, which locks the AWS role to this one account (`aws/iam/subscriptions-trust.json`). Only the gateway's service account has `roles/run.invoker` on the service.

## Test
```bash
python -m pytest
```

## Deploy
1. Check the topic exists in the team account (AWS CloudShell, `us-east-1`):
   ```bash
   aws cloudformation describe-stacks --region us-east-1 --stack-name ecoguard-notify \
     --query "Stacks[0].Outputs[?OutputKey=='TopicArn'].OutputValue" --output text
   ```
2. In GCP Cloud Shell, from this folder, deploy with the values under Environment:
   ```bash
   cp -r ../../../shared/python/ecoguard_common .   # gitignored copy of the shared package
   gcloud functions deploy subscriptions \
     --gen2 --runtime=python312 --region=us-east1 \
     --source=. --entry-point=handler --trigger-http --no-allow-unauthenticated \
     --service-account=fn-subscriptions@ecoguard-g21.iam.gserviceaccount.com \
     --set-env-vars=TOPIC_ARN=<TopicArn>,SUBSCRIPTIONS_ROLE_ARN=<SubscriptionsRoleArn>
   ```
3. Check the deployed values match Environment:
   ```bash
   gcloud functions describe subscriptions --region=us-east1 \
     --format='value(serviceConfig.environmentVariables)'
   ```

## Try it (demo)
1. On the **Alerts** page, choose `fox` and save. AWS emails a confirmation link: confirm it.
2. Reload the page: `fox` is still selected (`GET` reads the filter policy back from SNS).
3. Upload a photo with a fox and a cat. One email arrives naming the fox; nobody subscribed only to other tags gets one.
