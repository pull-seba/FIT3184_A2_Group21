// Public identifiers only: they ship in the browser bundle, so never put a secret here.
// Fill these from the ecoguard-auth stack outputs (infra/aws/template.yaml).
export const environment = {
  region: 'ap-southeast-2',
  userPoolId: 'ap-southeast-2_weshSSPb9',
  userPoolClientId: '7s4r5iv4324nk32ummfigup6o8',
  // The API Gateway URL, from `gcloud api-gateway gateways describe` (infra/gateway/README.md).
  apiBase: 'https://REPLACE-WITH-GATEWAY-HOST.ue.gateway.dev',
};
