// Public identifiers only: they ship in the browser bundle, so never put a secret here.
// Fill these from the ecoguard-auth stack outputs (infra/aws/template.yaml).
export const environment = {
  region: 'us-east-1',
  userPoolId: '<UserPoolId>' /* fill in after the us-east-1 deploy */,
  userPoolClientId: '<UserPoolClientId>',
  // The API Gateway URL, from `gcloud api-gateway gateways describe` (infra/gateway/README.md).
  apiBase: 'https://REPLACE-WITH-GATEWAY-HOST.ue.gateway.dev',
};
