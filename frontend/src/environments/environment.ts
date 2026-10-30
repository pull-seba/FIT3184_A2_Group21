// Public identifiers only: they ship in the browser bundle, so never put a secret here.
// Fill these from the ecoguard-auth stack outputs (infra/aws/template.yaml).
export const environment = {
  userPoolId: 'us-east-1_1ni2DpRgV',
  userPoolClientId: '3gr1ln2m7ohrk1jleavngbepvk',
  // The API Gateway URL, from `gcloud api-gateway gateways describe` (infra/gateway/README.md).
  apiBase: 'https://ecoguard-gw-2qp1rpih.ue.gateway.dev',
  // The chat widget swaps the user's ID token for Lex-only AWS credentials here.
  identityPoolId: 'us-east-1:a8a28691-1a30-41ba-b889-8996d8cea535',
};
