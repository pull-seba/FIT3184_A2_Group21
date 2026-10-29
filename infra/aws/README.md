# AWS: Cognito (owner: member 1)

`template.yaml` creates the Cognito user pool `ecoguard-users` and the web app client `ecoguard-web` (rubric 1.1).

## Deploy
A person must approve every deploy.

```sh
aws cloudformation deploy --template-file infra/aws/template.yaml --stack-name ecoguard-auth --region us-east-1
aws cloudformation describe-stacks --stack-name ecoguard-auth --region us-east-1 --query "Stacks[0].Outputs"
```

Copy `UserPoolId` and `UserPoolClientId` into `frontend/src/environments/environment.ts`. They are public identifiers, not secrets. `Issuer` and `UserPoolClientId` (the audience) go in the gateway's security definition.

## Testing authentication
Run `cd frontend && npm start` and open http://localhost:5173.

| Flow | Steps |
|---|---|
| Sign up | `/sign-up`: first name, last name, email, password, then the code Cognito emails. You're signed in and taken to the home page |
| Sign in and out | `/sign-in`: the top bar shows your name. **Sign out** revokes the tokens and returns to sign-in |
| Temporary password | Create a user with the command below, then sign in with the emailed temporary password: you're asked to choose a new one |
| Forgot password | `/sign-in`, **Forgot password?**, then the emailed code and a new password |
| Protected pages | Signed out, open http://localhost:5173/: you're redirected to `/sign-in` |

```sh
aws cognito-idp admin-create-user --region us-east-1 --user-pool-id <UserPoolId> --username someone@example.com \
  --user-attributes Name=email,Value=someone@example.com Name=email_verified,Value=true \
                    Name=given_name,Value=Test Name=family_name,Value=User
```

Cognito's default email sender allows about 50 emails a day, so avoid throwaway accounts.
