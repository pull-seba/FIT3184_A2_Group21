import { Component, computed, inject, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatSelectModule } from '@angular/material/select';
import { MatSnackBar } from '@angular/material/snack-bar';

import { ApiService } from '../../../../api/api.service';
import { problem } from '../../../../pages/query-by-file/read-file';
import { Gallery } from '../../gallery';
import { TAG_NAMES } from '../../tags';

// The gallery's bulk tag action. Put it inside <app-gallery [(files)]="...">: it shows in the
// toolbar when files are selected, and updates their tag chips in the gallery's list.
@Component({
  selector: 'app-tags-action',
  imports: [MatButtonModule, MatFormFieldModule, MatIconModule, MatSelectModule],
  template: `
    <mat-form-field appearance="outline" subscriptSizing="dynamic">
      <mat-label>Tags</mat-label>
      <mat-select multiple [value]="tags()" (selectionChange)="tags.set($event.value)">
        @for (name of tagNames; track name) {
          <mat-option [value]="name">{{ name }}</mat-option>
        }
      </mat-select>
    </mat-form-field>
    <button mat-button type="button" [disabled]="!canChange()" (click)="change(true)">
      <mat-icon>add</mat-icon>
      Add
    </button>
    <button mat-button type="button" [disabled]="!canChange()" (click)="change(false)">
      <mat-icon>remove</mat-icon>
      Remove
    </button>
  `,
  styles: `
    /* The controls join the gallery toolbar's own row. */
    :host {
      display: contents;
    }
  `,
})
export class TagsAction {
  // Projected into the gallery, so it can reach the gallery's selection and list.
  private readonly gallery = inject(Gallery);
  private readonly api = inject(ApiService);
  private readonly snackBar = inject(MatSnackBar);
  readonly tagNames = TAG_NAMES;
  readonly tags = signal<string[]>([]);
  readonly busy = signal(false);
  readonly canChange = computed(() => this.tags().length > 0 && !this.busy());

  async change(adding: boolean): Promise<void> {
    const files = this.gallery.selected();
    const tags = this.tags();
    this.busy.set(true);
    try {
      // One result per URL, in the request's order (docs/contracts/api-routes.md).
      const { results } = await this.api.post<{ results: { status: string }[] }>('/tags/bulk', {
        urls: files.map((file) => file.url),
        tags,
        operation: adding ? 1 : 0,
      });
      const updated = new Set(
        files.filter((_, i) => results[i].status === 'updated').map((file) => file.file_id),
      );
      this.gallery.files.update((all) =>
        all.map((file) =>
          updated.has(file.file_id)
            ? { ...file, tags: changedTags(file.tags, tags, adding) }
            : file,
        ),
      );
      this.snackBar.open(
        `${adding ? 'Added' : 'Removed'} ${tags.join(', ')}: ${updated.size} of ${files.length} files.`,
        'OK',
        { duration: 6000 },
      );
    } catch (err) {
      this.snackBar.open(problem(err), 'OK');
    } finally {
      this.busy.set(false);
    }
  }
}

// What bulk_tags just stored: adding keeps an existing count and sets 1 where the tag is absent.
function changedTags(current: Record<string, number>, tags: string[], adding: boolean) {
  const changed = { ...current };
  for (const tag of tags) {
    if (adding) changed[tag] ??= 1;
    else delete changed[tag];
  }
  return changed;
}
