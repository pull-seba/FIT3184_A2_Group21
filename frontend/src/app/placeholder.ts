import { Component, input } from '@angular/core';

// Stands in for a page until its owner adds it, so the shell's navigation and guard can be tested
// now. Each owner replaces `Placeholder` with their component in app.routes.ts.
@Component({
  selector: 'app-placeholder',
  template: `
    <main class="card">
      <h1>{{ title() }}</h1>
      <p>This page is coming soon (member {{ owner() }}).</p>
    </main>
  `,
})
export class Placeholder {
  // Filled from the route's `data` (withComponentInputBinding in app.config.ts).
  readonly title = input.required<string>();
  readonly owner = input.required<number>();
}
