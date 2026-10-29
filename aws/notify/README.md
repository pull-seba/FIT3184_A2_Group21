# notify (AWS)

Owner: member 1 · Rubric: 2.3.3 · Cross-cloud link 3

## What it does
GCP Pub/Sub pushes each `tag-changes` message (from `functions/notify/on_tags_changed`) to this Lambda's URL. The Lambda checks the push carries a Google ID token for our push account, then publishes an email to SNS topic `ecoguard-tag-alerts` with message attribute `tags` set to the added tags. Each email subscription has a filter policy such as `{"tags": ["fox"]}`, so people only get alerts for tags they chose.

```
Firestore change → on_tags_changed → Pub/Sub tag-changes → (HTTPS + Google token) → this Lambda → SNS → email
```

## Security
- The function URL has no AWS auth, because Pub/Sub can't sign AWS requests. Instead every request must carry a Google ID token. The code asks Google's token-info endpoint to check its signature and expiry, then checks issuer, audience (this URL) and that `email` is the push service account. Anything else gets `401`.
- Role `ecoguard-notify` can only publish to the one topic and write its own logs (`aws/iam/notify.json`).
- Emails link to the app, never to a signed URL.

## Test
```bash
python -m pytest
```

## Deploy
1. In region `us-east-1` (N. Virginia): CloudFormation → Create stack → upload `aws/notify/template.yaml` → name `ecoguard-notify`. Note the `PushEndpoint` and `TopicArn` outputs.
2. Lambda → `ecoguard-notify` → Code: replace `index.py` with the contents of `app.py` → Deploy.
3. In GCP Cloud Shell, once `tag-changes` exists:
   ```bash
   gcloud iam service-accounts create ecoguard-pubsub-push

   gcloud pubsub subscriptions create tag-changes-to-aws \
     --topic=tag-changes \
     --push-endpoint=<PushEndpoint output from step 1> \
     --push-auth-service-account=ecoguard-pubsub-push@ecoguard-g21.iam.gserviceaccount.com
   ```

## Try it without the app
SNS → `ecoguard-tag-alerts` → Create subscription → Email, your address, filter policy `{"tags": ["fox"]}` → confirm the email. Then upload a fox photo once GCP is running.
