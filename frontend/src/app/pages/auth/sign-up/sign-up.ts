import { Component, inject, signal } from '@angular/core';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';

import { AuthService } from '../../../auth/auth.service';
import { field, FormState, passwordsMatch } from '../../../auth/form-state';

@Component({
  selector: 'app-sign-up',
  imports: [RouterLink],
  templateUrl: './sign-up.html',
})
export class SignUp {
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);
  readonly form = new FormState();
  // The address waiting for its code; set means the page shows the verify step.
  readonly email = signal('');

  constructor() {
    // Sign-in sends unverified users here with ?verify=<email>.
    this.email.set(inject(ActivatedRoute).snapshot.queryParamMap.get('verify') ?? '');
  }

  signUp = async (data: FormData) => {
    passwordsMatch(data);
    const email = field(data, 'email');
    await this.auth.signUp(email, String(data.get('password')), field(data, 'firstName'), field(data, 'lastName'));
    this.email.set(email);
    this.form.success('Account created. Check your email for the verification code.');
  };

  verify = async (data: FormData) => {
    await this.auth.confirmSignUp(this.email(), field(data, 'code'));
    await this.router.navigate(['/sign-in'], { queryParams: { verified: 1 } });
  };

  async resend(): Promise<void> {
    try {
      await this.auth.resendCode(this.email());
      this.form.success('A new code has been sent.');
    } catch (err) {
      this.form.error(err instanceof Error ? err.message : String(err));
    }
  }
}
