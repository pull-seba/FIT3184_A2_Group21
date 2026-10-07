// Promise wrappers around amazon-cognito-identity-js (loaded from CDN as window.AmazonCognitoIdentity).
// Sign-in uses SRP, so the password itself is never sent to Cognito.
import { CONFIG } from "./config.js";

const { CognitoUserPool, CognitoUser, AuthenticationDetails, CognitoUserAttribute } = window.AmazonCognitoIdentity;
const userPool = new CognitoUserPool({ UserPoolId: CONFIG.userPoolId, ClientId: CONFIG.clientId });

const cognitoUser = (email) => new CognitoUser({ Username: email, Pool: userPool });

export function signUp(email, password, firstName, lastName) {
  const attributes = [
    new CognitoUserAttribute({ Name: "email", Value: email }),
    new CognitoUserAttribute({ Name: "given_name", Value: firstName }),
    new CognitoUserAttribute({ Name: "family_name", Value: lastName }),
  ];
  return new Promise((resolve, reject) =>
    userPool.signUp(email, password, attributes, null, (err, result) => (err ? reject(err) : resolve(result))));
}

export function confirmSignUp(email, code) {
  return new Promise((resolve, reject) =>
    cognitoUser(email).confirmRegistration(code, true, (err) => (err ? reject(err) : resolve())));
}

export function resendCode(email) {
  return new Promise((resolve, reject) =>
    cognitoUser(email).resendConfirmationCode((err) => (err ? reject(err) : resolve())));
}

// Resolves { status: "SIGNED_IN" } or, for users invited with a temporary password,
// { status: "NEW_PASSWORD_REQUIRED", requiredAttributes, completeNewPassword(password, attributes) }.
export function signIn(email, password) {
  const user = cognitoUser(email);
  const details = new AuthenticationDetails({ Username: email, Password: password });
  return new Promise((resolve, reject) => {
    user.authenticateUser(details, {
      onSuccess: () => resolve({ status: "SIGNED_IN" }),
      onFailure: reject,
      newPasswordRequired: (userAttributes, requiredAttributes) =>
        resolve({
          status: "NEW_PASSWORD_REQUIRED",
          requiredAttributes: requiredAttributes || [],
          completeNewPassword: (newPassword, attributes = {}) =>
            new Promise((done, fail) =>
              user.completeNewPasswordChallenge(newPassword, attributes, { onSuccess: () => done(), onFailure: fail })),
        }),
    });
  });
}

// Resolves the signed-in user's ID token claims (email, given_name, ...) or null.
export function currentUser() {
  const user = userPool.getCurrentUser();
  if (!user) return Promise.resolve(null);
  return new Promise((resolve) =>
    user.getSession((err, session) =>
      resolve(!err && session && session.isValid() ? session.getIdToken().payload : null)));
}

// Resolves the signed-in user's raw ID token (JWT) or null. Send it to protected APIs as
// "Authorization: Bearer <token>"; getSession refreshes it first if it has expired.
export function getIdToken() {
  const user = userPool.getCurrentUser();
  if (!user) return Promise.resolve(null);
  return new Promise((resolve) =>
    user.getSession((err, session) =>
      resolve(!err && session && session.isValid() ? session.getIdToken().getJwtToken() : null)));
}

// Revokes tokens server-side on every device, then clears local storage.
export function signOut() {
  const user = userPool.getCurrentUser();
  if (!user) return Promise.resolve();
  return new Promise((resolve) =>
    user.getSession((sessionErr) => {
      if (sessionErr) {
        user.signOut();
        return resolve();
      }
      user.globalSignOut({
        onSuccess: () => { user.signOut(); resolve(); },
        onFailure: () => { user.signOut(); resolve(); },
      });
    }));
}

export function forgotPassword(email) {
  return new Promise((resolve, reject) =>
    cognitoUser(email).forgotPassword({ onSuccess: () => resolve(), inputVerificationCode: () => resolve(), onFailure: reject }));
}

export function confirmForgotPassword(email, code, newPassword) {
  return new Promise((resolve, reject) =>
    cognitoUser(email).confirmPassword(code, newPassword, { onSuccess: () => resolve(), onFailure: reject }));
}

// Pages other than sign-up/sign-in call this first (rubric 1.2).
export async function requireAuth() {
  const claims = await currentUser();
  if (!claims) {
    window.location.replace("signup.html");
    return null;
  }
  return claims;
}
