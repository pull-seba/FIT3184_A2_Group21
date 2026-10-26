# Member 1: identity and cross-cloud

Name and ID: (add)

You own 14 marks alone (1.1, 1.2, 1.3, 2.3.3) and share 3.1 (auth screens) and 3.4 (shell and routing). Every endpoint and every page depends on your gateway and auth guard, and your role review on Saturday decides 1.3.

## What you own
- `infra/gateway/openapi.yaml` and `docs/contracts/api-routes.md` (route JSON comes from each route's owner)
- Cognito user pool, app client and identity pool; `aws/iam/`; `aws/notify/`; `functions/notify/`
- `shared/python/ecoguard_common/auth.py`
- `frontend/` shell, routing, auth guard, `src/app/api/` client, auth pages, notifications page

## Steps by phase
| Phase | Steps |
| --- | --- |
| Contracts, Mon 26 | Shared AWS account and GCP project with everyone added; gateway spec with every route stubbed; app framework chosen |
| Foundations, to Tue 27 | Cognito pool and client; gateway JWT check; app shell and guard; shared API client that attaches the ID token |
| Pipeline, Wed 28 to Fri 30 | `on_tags_changed` Firestore trigger; Pub/Sub push to the AWS Lambda with OIDC; SNS with per-tag filter policies; Lex token path with member 4; identity pool for the Lex widget; notification settings page |
| Integrate, Sat 31 | Every page inside the shell; review every service account and IAM role; `scripts/check-no-token.sh` passes |

## Watch out for
- Gateway `securityDefinitions`: issuer `https://cognito-idp.<region>.amazonaws.com/<user-pool-id>`, JWKS `<issuer>/.well-known/jwks.json`, audience = the app client ID. That audience only matches ID tokens.
- The spec asks for email verification and a temporary password change; self sign-up gives no temporary password. Ask on Ed early (see `docs/decisions.md`).
- Cloud Run services must be deployed with `--no-allow-unauthenticated`; only the gateway's service account gets `run.invoker`.
- The AWS notify Lambda must verify the Google OIDC token: issuer, audience and the push service account's email.

## Who waits on you
| Who | What | Needed by |
| --- | --- | --- |
| All | Shared accounts | Mon 26 |
| 2, 3, 4 | Gateway routes passing claims | Tue 27 |
| 4 | Identity pool for the widget; Lex token method | Wed 28 |
| All | App shell and API client | Thu 29 |
| All | Role review | Sat 31 |
