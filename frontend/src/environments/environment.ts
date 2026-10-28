// Public identifiers only: they ship in the browser bundle, so never put a secret here.
// Fill these from the ecoguard-auth stack outputs (infra/aws/template.yaml).
// The placeholder pool ID keeps the "<region>_<id>" shape so the Cognito library can still start.
export const environment = {
  region: 'ap-southeast-2',
  userPoolId: 'ap-southeast-2_REPLACEME',
  userPoolClientId: 'REPLACEME',
};
