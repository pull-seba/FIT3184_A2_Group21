import { Component, inject } from '@angular/core';
import { RouterLink } from '@angular/router';

import { pages } from '../../app.routes';
import { AuthService } from '../../auth/auth.service';

// Landing page after sign-in: a link to each page, from the same list as the shell's navigation.
// app.routes also imports this file; that's safe because `pages` is only read when Home is created.
@Component({
  selector: 'app-home',
  imports: [RouterLink],
  template: `
    <main class="card">
      @if (auth.user(); as user) {
        <h1>Welcome, {{ user.given_name }}</h1>
        <p>Signed in as {{ user.given_name }} {{ user.family_name }} ({{ user.email }}).</p>
      }
      <h2>What would you like to do?</h2>
      <ul>
        @for (page of pages; track page.path) {
          <li><a [routerLink]="page.path">{{ page.title }}</a></li>
        }
      </ul>
    </main>
  `,
})
export class Home {
  readonly auth = inject(AuthService);
  readonly pages = pages;
}
