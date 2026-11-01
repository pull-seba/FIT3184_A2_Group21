import { Component, computed, inject, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatSelectModule } from '@angular/material/select';
import { MatSnackBar } from '@angular/material/snack-bar';

import { ApiService } from '../../../../api/api.service';
import { Gallery } from '../../gallery';
import { TAG_NAMES } from '../../tags';

// POST /tags/bulk: one result per URL, in the request's order (docs/contracts/api-routes.md).
interface TagResult {
  status: 'updated' | 'not_found';
}

const REMOVE = 0;
const ADD = 1;
type Operation = typeof REMOVE | typeof ADD;

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
    <button mat-button type="button" [disabled]="!canChange()" (click)="change(ADD)">
      <mat-icon>add</mat-icon>
      Add
    </button>
    <button mat-button type="button" [disabled]="!canChange()" (click)="change(REMOVE)">
      <mat-icon>remove</mat-icon>
      Remove
    </button>
  `,
  styles: `
    /* The controls join the gallery toolbar's own row. */
    :host {
      display: contents;
    }
    mat-form-field {
      width: 180px;
    }
  `,
})
export class TagsAction {
  // Projected into the gallery, so it can reach the gallery's selection and list.
  private readonly gallery = inject(Gallery);
  private readonly api = inject(ApiService);
  private readonly snackBar = inject(MatSnackBar);
  readonly tagNames = TAG_NAMES;
  readonly ADD = ADD;
  readonly REMOVE = REMOVE;
  readonly tags = signal<string[]>([]);
  readonly busy = signal(false);
  readonly canChange = computed(() => this.tags().length > 0 && !this.busy());

  async change(operation: Operation): Promise<void> {
    const files = this.gallery.selected();
    const tags = this.tags();
    this.busy.set(true);
    try {
      const { results } = await this.api.post<{ results: TagResult[] }>('/tags/bulk', {
        urls: files.map((file) => file.url),
        tags,
        operation,
      });
      const updated = new Set(
        files.filter((_, i) => results[i].status === 'updated').map((file) => file.file_id),
      );
      this.gallery.files.update((all) =>
        all.map((file) =>
          updated.has(file.file_id)
            ? { ...file, tags: changedTags(file.tags, tags, operation) }
            : file,
        ),
      );
      this.snackBar.open(summary(tags, operation, updated.size, files.length), 'OK', {
        duration: 6000,
      });
    } catch (err) {
      this.snackBar.open(err instanceof Error ? err.message : String(err), 'OK');
    } finally {
      this.busy.set(false);
    }
  }
}

// What bulk_tags just stored: adding keeps an existing count and sets 1 where the tag is absent.
function changedTags(
  current: Record<string, number>,
  tags: string[],
  operation: Operation,
): Record<string, number> {
  const changed = { ...current };
  for (const tag of tags) {
    if (operation === ADD) changed[tag] ??= 1;
    else delete changed[tag];
  }
  return changed;
}

function summary(tags: string[], operation: Operation, updated: number, sent: number): string {
  const action =
    operation === ADD ? `Added ${tags.join(', ')} to` : `Removed ${tags.join(', ')} from`;
  const missing = sent - updated;
  return (
    `${action} ${updated} ${updated === 1 ? 'file' : 'files'}.` +
    (missing ? ` ${missing} couldn't be found: it may have been deleted.` : '')
  );
}
