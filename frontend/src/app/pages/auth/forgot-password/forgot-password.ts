import { Component, inject, signal } from '@angular/core';
import { Router, RouterLink } from '@angular/router';

import { AuthService } from '../../../auth/auth.service';
import { field, FormState, passwordsMatch } from '../../../auth/form-state';

@Component({
  selector: 'app-forgot-password',
  imports: [RouterLink],
  templateUrl: './forgot-password.html',
})
export class ForgotPassword {
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);
  readonly form = new FormState();
  // Set once a code has been requested; the page then shows the reset step.
  readonly email = signal('');

  request = async (data: FormData) => {
    const email = field(data, 'email');
    await this.auth.forgotPassword(email);
    this.email.set(email);
    // Same message whether or not the account exists, so the page can't be used to find accounts.
    this.form.success('If that account exists, a reset code has been emailed.');
  };

  reset = async (data: FormData) => {
    passwordsMatch(data);
    await this.auth.confirmForgotPassword(this.email(), field(data, 'code'), String(data.get('password')));
    await this.router.navigate(['/sign-in'], { queryParams: { reset: 1 } });
  };
}
