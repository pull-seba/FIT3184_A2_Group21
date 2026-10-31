import { Component, inject, signal } from '@angular/core';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';

import { AuthService } from '../../../auth/auth.service';
import { field, FormState, passwordsMatch } from '../../../auth/form-state';

@Component({
  selector: 'app-sign-in',
  imports: [RouterLink],
  templateUrl: './sign-in.html',
})
export class SignIn {
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);
  readonly form = new FormState();
  readonly step = signal<'sign-in' | 'new-password'>('sign-in');

  constructor() {
    // Set by the sign-up and forgot-password pages after they succeed.
    const params = inject(ActivatedRoute).snapshot.queryParamMap;
    if (params.has('verified')) this.form.success('Email verified. You can now sign in.');
    if (params.has('reset')) this.form.success('Password changed. Sign in with your new password.');
  }

  // Only ask for the attributes Cognito says an invited user is missing.
  needs(attribute: string): boolean {
    return this.auth.requiredAttributes.includes(attribute);
  }

  signIn = async (data: FormData) => {
    const email = field(data, 'email');
    try {
      const result = await this.auth.signIn(email, String(data.get('password')));
      if (result === 'NEW_PASSWORD_REQUIRED') {
        this.step.set('new-password');
        return;
      }
    } catch (err) {
      // Signed up but never entered the code: send them back to the verify step.
      if ((err as { code?: string }).code === 'UserNotConfirmedException') {
        await this.router.navigate(['/sign-up'], { queryParams: { verify: email } });
        return;
      }
      throw err;
    }
    await this.router.navigateByUrl('/');
  };

  setNewPassword = async (data: FormData) => {
    passwordsMatch(data);
    const attributes: Record<string, string> = {};
    for (const name of this.auth.requiredAttributes) attributes[name] = field(data, name);
    await this.auth.completeNewPassword(String(data.get('password')), attributes);
    await this.router.navigateByUrl('/');
  };
}
