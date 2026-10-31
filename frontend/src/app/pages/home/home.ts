import { Component, inject } from '@angular/core';

import { AuthService } from '../../auth/auth.service';

// Landing page after sign-in, until the feature pages are added to the shell's navigation.
@Component({
  selector: 'app-home',
  template: `
    <main class="card">
      @if (auth.user(); as user) {
        <h1>Welcome, {{ user.given_name }}</h1>
        <p>Signed in as {{ user.given_name }} {{ user.family_name }} ({{ user.email }}).</p>
      }
    </main>
  `,
})
export class Home {
  readonly auth = inject(AuthService);
}
