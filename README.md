# FIT3184_A2_Group21
Aussie EcoGuard is a multi-cloud serverless platform tracking pests and lost pets. Built across AWS and a second cloud, it uses Cognito for security. Media uploads trigger functions to auto-tag species using ML. Users can search via APIs, use a chatbot to find pets, and receive email alerts.

## Setup

### 1. Deploy the AWS stack
Requires the [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html) and AWS credentials (in Learner Lab: AWS Details -> AWS CLI, paste into `~/.aws/credentials`).

```sh
cd infra/aws
sam build
sam deploy --guided   # stack name: ecoguard (lowercase), region: us-east-1
```

Later deploys only need `sam deploy`.

### 2. Point the frontend at the user pool
Copy the `UserPoolId` and `UserPoolClientId` stack outputs into `frontend/js/config.js`. These are public identifiers, not secrets. They change if the stack is deleted and redeployed.

### 3. Run the frontend
The pages use ES modules, which browsers block when opened straight from disk, so serve them over HTTP:

```sh
cd frontend
python -m http.server 8000
```

Then open http://localhost:8000/signup.html.

## Testing authentication

| Flow | Steps |
|---|---|
| Sign up | `signup.html` -> enter first name, last name, email, password -> enter the code emailed by Cognito -> redirected to sign in |
| Sign in / sign out | `login.html` -> sign in -> home page shows your name and email -> **Sign out** |
| Temporary password | Create a user in the Cognito console (User pools -> `ecoguard-users` -> Create user, "Send an email invitation") or with the CLI below. Sign in with the emailed temporary password and you are asked to choose a new one. |
| Forgot password | `login.html` -> **Forgot password?** -> enter the emailed code and a new password |
| Protected pages | Sign out, then open `index.html` directly -> redirected to `signup.html` |

```sh
aws cognito-idp admin-create-user --user-pool-id <UserPoolId> --username someone@example.com \
  --user-attributes Name=email,Value=someone@example.com Name=email_verified,Value=true \
                    Name=given_name,Value=Test Name=family_name,Value=User
```

Cognito's default email sender is limited to about 50 emails per day, so avoid creating throwaway accounts.

## Calling protected APIs
Use `getIdToken()` from `frontend/js/auth.js` and send the token with each request:

```js
const token = await getIdToken();
const response = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
```

AWS endpoints validate it with an API Gateway Cognito authorizer; GCP endpoints must verify the JWT themselves against the user pool's JWKS (`https://cognito-idp.<region>.amazonaws.com/<UserPoolId>/.well-known/jwks.json`).
