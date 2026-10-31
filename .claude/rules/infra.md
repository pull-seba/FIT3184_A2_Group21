---
paths:
  - "infra/**"
  - ".github/**"
---

# Infrastructure (rubric 1.2, 1.3)

- `infra/gateway/openapi.yaml` belongs to member 1. Others request routes by updating `docs/contracts/api-routes.md` in a PR.
- The gateway's Cognito security definition uses issuer `https://cognito-idp.us-east-1.amazonaws.com/<user-pool-id>`, JWKS `<issuer>/.well-known/jwks.json` and audience = the app client ID. Every path has `security`.
- Each `x-google-backend` points at a Cloud Run service deployed with `--no-allow-unauthenticated`; only the gateway's service account has `roles/run.invoker` on it.
- Buckets use uniform bucket-level access with public access prevention enforced. No `allUsers` or `allAuthenticatedUsers` binding anywhere.
- One service account per function, named `fn-<function-name-with-hyphens>` (6 to 30 characters), holding only the roles in that function's README. Never `roles/owner` or `roles/editor`.
- Firestore indexes live in `infra/gcp/firestore.indexes.json`.
- Both clouds have budget alerts.
