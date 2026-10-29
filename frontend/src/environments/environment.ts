// Public identifiers only: they ship in the browser bundle, so never put a secret here.
// Fill these from the ecoguard-auth stack outputs (infra/aws/template.yaml).
export const environment = {
  region: 'us-east-1',
  userPoolId: 'us-east-1_1ni2DpRgV',
  userPoolClientId: '3gr1ln2m7ohrk1jleavngbepvk',
  // The API Gateway URL, from `gcloud api-gateway gateways describe` (infra/gateway/README.md).
  apiBase: 'https://ecoguard-gw-2qp1rpih.ue.gateway.dev',
};
