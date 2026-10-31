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
  // Kept in memory only, so the user is signed in straight after verifying. Lost on reload,
  // and empty when sign-in sent the user here, so those cases fall back to the sign-in page.
  private password = '';

  constructor() {
    // Sign-in sends unverified users here with ?verify=<email>.
    this.email.set(inject(ActivatedRoute).snapshot.queryParamMap.get('verify') ?? '');
  }

  signUp = async (data: FormData) => {
    passwordsMatch(data);
    const email = field(data, 'email');
    const password = String(data.get('password'));
    await this.auth.signUp(email, password, field(data, 'firstName'), field(data, 'lastName'));
    this.password = password;
    this.email.set(email);
    this.form.success('Account created. Check your email for the verification code.');
  };

  verify = async (data: FormData) => {
    await this.auth.confirmSignUp(this.email(), field(data, 'code'));
    if (!this.password) {
      await this.router.navigate(['/sign-in'], { queryParams: { verified: 1 } });
      return;
    }
    await this.auth.signIn(this.email(), this.password);
    this.password = '';
    await this.router.navigateByUrl('/');
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
