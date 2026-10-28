---
paths:
  - "aws/**"
---

# AWS: Cognito, Lex, Lambda, SNS (rubric 1.1, 1.3, 2.2.5, 2.3.3)

- One IAM role per Lambda, with policies in `aws/iam/<function>.json`. Name actions and resources explicitly; no `*` except where AWS requires it (CloudWatch Logs log streams).
- No access keys anywhere. Lambdas get credentials from their role; the browser gets them from the Cognito identity pool.
- Calls to GCP go through API Gateway with a Cognito ID token (method for the Lex Lambda in `docs/decisions.md`).
- The Pub/Sub push receiver verifies the Google OIDC token on every request: issuer `https://accounts.google.com`, audience equal to the configured endpoint, `email` equal to the push service account. Reject anything else with `401`.
- SNS topic `ecoguard-tag-alerts`: publish with message attribute `tags` as `String.Array`; each email subscription carries a filter policy on `tags`. Email bodies name the species and counts and link to the app, never to a signed URL.
- Lex V2, locale `en_AU`. Export the bot definition into `aws/lex/` so it lives in Git.
- Region `ap-southeast-2` unless `docs/decisions.md` says otherwise.
