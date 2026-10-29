import { Injectable, signal } from '@angular/core';
import {
  AuthenticationDetails,
  CognitoUser,
  CognitoUserAttribute,
  CognitoUserPool,
  CognitoUserSession,
} from 'amazon-cognito-identity-js';

import { environment } from '../../environments/environment';

export interface UserClaims {
  sub: string;
  email: string;
  given_name: string;
  family_name: string;
}

export type SignInResult = 'SIGNED_IN' | 'NEW_PASSWORD_REQUIRED';

// Promise wrappers around amazon-cognito-identity-js. Sign-in uses SRP, so the password itself
// is never sent to Cognito. The library keeps the tokens in localStorage and refreshes them.
@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly pool = new CognitoUserPool({
    UserPoolId: environment.userPoolId,
    ClientId: environment.userPoolClientId,
  });

  readonly user = signal<UserClaims | null>(null);

  // Set while an invited user must replace their temporary password.
  private challengeUser: CognitoUser | null = null;
  requiredAttributes: string[] = [];

  signUp(email: string, password: string, firstName: string, lastName: string): Promise<void> {
    const attributes = [
      new CognitoUserAttribute({ Name: 'email', Value: email }),
      new CognitoUserAttribute({ Name: 'given_name', Value: firstName }),
      new CognitoUserAttribute({ Name: 'family_name', Value: lastName }),
    ];
    return new Promise((resolve, reject) =>
      this.pool.signUp(email, password, attributes, [], (err) => (err ? reject(err) : resolve())),
    );
  }

  confirmSignUp(email: string, code: string): Promise<void> {
    return new Promise((resolve, reject) =>
      this.cognitoUser(email).confirmRegistration(code, true, (err) => (err ? reject(err) : resolve())),
    );
  }

  resendCode(email: string): Promise<void> {
    return new Promise((resolve, reject) =>
      this.cognitoUser(email).resendConfirmationCode((err) => (err ? reject(err) : resolve())),
    );
  }

  signIn(email: string, password: string): Promise<SignInResult> {
    const user = this.cognitoUser(email);
    const details = new AuthenticationDetails({ Username: email, Password: password });
    return new Promise((resolve, reject) =>
      user.authenticateUser(details, {
        onSuccess: (session) => {
          this.user.set(claimsOf(session));
          resolve('SIGNED_IN');
        },
        onFailure: reject,
        // Users created by an admin sign in with an emailed temporary password and must change it.
        newPasswordRequired: (_userAttributes, requiredAttributes) => {
          this.challengeUser = user;
          this.requiredAttributes = requiredAttributes ?? [];
          resolve('NEW_PASSWORD_REQUIRED');
        },
      }),
    );
  }

  completeNewPassword(password: string, attributes: Record<string, string>): Promise<void> {
    const user = this.challengeUser;
    if (!user) return Promise.reject(new Error('Sign in with your temporary password first.'));
    return new Promise((resolve, reject) =>
      user.completeNewPasswordChallenge(password, attributes, {
        onSuccess: (session) => {
          this.challengeUser = null;
          this.user.set(claimsOf(session));
          resolve();
        },
        onFailure: reject,
      }),
    );
  }

  async loadUser(): Promise<UserClaims | null> {
    const session = await this.session();
    this.user.set(session ? claimsOf(session) : null);
    return this.user();
  }

  // Send the ID token, not the access token: only it has the `aud` claim the gateway checks.
  async getIdToken(): Promise<string | null> {
    const session = await this.session();
    return session ? session.getIdToken().getJwtToken() : null;
  }

  // Revokes the tokens server-side on every device, then clears local storage. Local sign-out
  // still happens if the revoke call fails, so the user is never left half signed in.
  async signOut(): Promise<void> {
    const user = this.pool.getCurrentUser();
    if (user && (await this.session())) {
      await new Promise<void>((resolve) =>
        user.globalSignOut({ onSuccess: () => resolve(), onFailure: () => resolve() }),
      );
    }
    user?.signOut();
    this.user.set(null);
  }

  forgotPassword(email: string): Promise<void> {
    return new Promise((resolve, reject) =>
      this.cognitoUser(email).forgotPassword({
        onSuccess: () => resolve(),
        inputVerificationCode: () => resolve(),
        onFailure: reject,
      }),
    );
  }

  confirmForgotPassword(email: string, code: string, password: string): Promise<void> {
    return new Promise((resolve, reject) =>
      this.cognitoUser(email).confirmPassword(code, password, {
        onSuccess: () => resolve(),
        onFailure: reject,
      }),
    );
  }

  private session(): Promise<CognitoUserSession | null> {
    const user = this.pool.getCurrentUser();
    if (!user) return Promise.resolve(null);
    return new Promise((resolve) =>
      user.getSession((err: Error | null, session: CognitoUserSession | null) =>
        resolve(!err && session?.isValid() ? session : null),
      ),
    );
  }

  private cognitoUser(email: string): CognitoUser {
    return new CognitoUser({ Username: email, Pool: this.pool });
  }
}

function claimsOf(session: CognitoUserSession): UserClaims {
  return session.getIdToken().payload as UserClaims;
}
