# API Gateway (owner: member 1)

`openapi.yaml` puts every route in `docs/contracts/api-routes.md` behind one gateway that checks the Cognito ID token (rubric 1.2) and calls each function as its own service account (rubric 1.3).

| Setting | Value |
| --- | --- |
| Issuer | `https://cognito-idp.ap-southeast-2.amazonaws.com/ap-southeast-2_weshSSPb9` |
| Keys (JWKS) | `<issuer>/.well-known/jwks.json` |
| Audience | `7s4r5iv4324nk32ummfigup6o8` (the `ecoguard-web` app client) |
| Gateway service account | `api-gateway@ecoguard-g21.iam.gserviceaccount.com`, holding only `roles/run.invoker` on each function |

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
A person runs these and approves each one. A config can't be edited, so each change gets a new config name (`-v2`, `-v3`, ...) and the gateway is updated to use it.

```bash
PROJECT=ecoguard-g21
REGION=us-east1
SA=api-gateway@$PROJECT.iam.gserviceaccount.com

# Once: the gateway's own service account, allowed to invoke each function and nothing else.
gcloud iam service-accounts create api-gateway --project=$PROJECT --display-name="API Gateway"
for fn in upload-init get-file delete-files tag-query thumbnail-lookup search-by-file lost-pet bulk-tags subscriptions; do
  gcloud functions add-invoker-policy-binding $fn --project=$PROJECT --region=$REGION --member=serviceAccount:$SA
done   # skip any function that isn't deployed yet, and run it for that function once it is

# Once: the API and the gateway.
gcloud api-gateway apis create ecoguard-api --project=$PROJECT
gcloud api-gateway api-configs create ecoguard-config-v1 --project=$PROJECT --api=ecoguard-api \
  --openapi-spec=infra/gateway/openapi.yaml --backend-auth-service-account=$SA
gcloud api-gateway gateways create ecoguard-gw --project=$PROJECT --location=$REGION \
  --api=ecoguard-api --api-config=ecoguard-config-v1

# Every later change to openapi.yaml.
gcloud api-gateway api-configs create ecoguard-config-v2 --project=$PROJECT --api=ecoguard-api \
  --openapi-spec=infra/gateway/openapi.yaml --backend-auth-service-account=$SA
gcloud api-gateway gateways update ecoguard-gw --project=$PROJECT --location=$REGION \
  --api=ecoguard-api --api-config=ecoguard-config-v2

# The gateway URL, for API_BASE and the frontend environment.
gcloud api-gateway gateways describe ecoguard-gw --project=$PROJECT --location=$REGION --format='value(defaultHostname)'
```

## Check
```bash
API_BASE=https://<defaultHostname> scripts/check-no-token.sh
```
Every route must return `401` without a token and with a bad one. `OPTIONS` isn't checked: it reaches the function, which returns only CORS headers and never reads data.
