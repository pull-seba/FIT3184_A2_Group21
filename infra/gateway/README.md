# API Gateway (owner: member 1)

`openapi.yaml` puts every route in `docs/contracts/api-routes.md` behind one gateway that checks the Cognito ID token (rubric 1.2) and calls each function as its own service account (rubric 1.3).

| Setting | Value |
| --- | --- |
| Issuer | `https://cognito-idp.us-east-1.amazonaws.com/us-east-1_1ni2DpRgV` |
| Keys (JWKS) | `<issuer>/.well-known/jwks.json` |
| Audience | `3gr1ln2m7ohrk1jleavngbepvk` (the `ecoguard-web` app client) |
| Gateway service account | `ecoguard-gateway@ecoguard-g21.iam.gserviceaccount.com`, holding only `roles/run.invoker` on each function |

## What each function needs
- Deploy with `--no-allow-unauthenticated`. Only the gateway's service account may invoke it.
- Read the caller with `ecoguard_common.auth.get_user(request)`.
- Path parameters arrive as query parameters: `GET /files/abc` reaches `get-file` as `?file_id=abc`.
- Answer CORS. The app runs on another origin, so the browser sends an `OPTIONS` preflight with no token first. The gateway passes it through without a token check. Return `204` with the headers below, and add `Access-Control-Allow-Origin` to every other response too:
  ```python
  CORS = {
      "Access-Control-Allow-Origin": "*",  # safe: every real call still needs a token
      "Access-Control-Allow-Methods": "GET, POST, PUT, OPTIONS",
      "Access-Control-Allow-Headers": "Authorization, Content-Type",
  }
  if request.method == "OPTIONS":
      return "", 204, CORS
  ```

## Deploy
Run in Cloud Shell from the folder holding `openapi.yaml`.

```bash
gcloud config set project ecoguard-g21

gcloud iam service-accounts create ecoguard-gateway

gcloud api-gateway apis create ecoguard-api

gcloud api-gateway api-configs create ecoguard-config-v1 \
  --api=ecoguard-api \
  --openapi-spec=openapi.yaml \
  --backend-auth-service-account=ecoguard-gateway@ecoguard-g21.iam.gserviceaccount.com

gcloud api-gateway gateways create ecoguard-gw \
  --api=ecoguard-api \
  --api-config=ecoguard-config-v1 \
  --location=us-east1

gcloud api-gateway gateways describe ecoguard-gw --location=us-east1
```

Let the gateway call each function once it's deployed (needs Cloud Run Admin):

```bash
gcloud functions add-invoker-policy-binding tag-query \
  --region=us-east1 \
  --member=serviceAccount:ecoguard-gateway@ecoguard-g21.iam.gserviceaccount.com
```

Configs can't be edited. After changing `openapi.yaml`, create `ecoguard-config-v2` the same way, then:

```bash
gcloud api-gateway gateways update ecoguard-gw \
  --api=ecoguard-api \
  --api-config=ecoguard-config-v2 \
  --location=us-east1
```

## Check
```bash
API_BASE=https://<defaultHostname> scripts/check-no-token.sh
```
Every route should return `401` without a token and with a bad one.
