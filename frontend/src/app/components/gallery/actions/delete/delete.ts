import { Component, computed, effect, inject, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatSnackBar } from '@angular/material/snack-bar';

import { ApiService } from '../../../../api/api.service';
import { Gallery } from '../../gallery';

// POST /files/delete: one result per URL, in the request's order (docs/contracts/api-routes.md).
interface DeleteResult {
  status: 'deleted' | 'not_found' | 'error';
  detail?: string;
}

// The gallery's Delete action. Put it inside <app-gallery [(files)]="...">: it shows in the
// toolbar when files are selected, and takes deleted files out of the gallery's list.
@Component({
  selector: 'app-delete-action',
  imports: [MatButtonModule, MatIconModule],
  template: `
    @if (confirming()) {
      <span>Delete {{ count() }} {{ count() === 1 ? 'file' : 'files' }} for good?</span>
      <button mat-flat-button type="button" class="danger" [disabled]="busy()" (click)="delete()">
        Delete
      </button>
      <button mat-button type="button" [disabled]="busy()" (click)="confirming.set(false)">
        Cancel
      </button>
    } @else {
      <button mat-button type="button" (click)="confirming.set(true)">
        <mat-icon>delete</mat-icon>
        Delete
      </button>
    }
  `,
  styles: `
    /* The buttons join the gallery toolbar's own row. */
    :host {
      display: contents;
    }
    .danger {
      --mat-button-filled-container-color: var(--mat-sys-error);
      --mat-button-filled-label-text-color: var(--mat-sys-on-error);
    }
  `,
})
export class DeleteAction {
  // Projected into the gallery, so it can reach the gallery's selection and list.
  private readonly gallery = inject(Gallery);
  private readonly api = inject(ApiService);
  private readonly snackBar = inject(MatSnackBar);
  readonly count = computed(() => this.gallery.selected().length);
  readonly confirming = signal(false);
  readonly busy = signal(false);

  constructor() {
    // A different selection needs a fresh confirmation.
    effect(() => {
      this.count();
      this.confirming.set(false);
    });
  }

  async delete(): Promise<void> {
    const files = this.gallery.selected();
    this.busy.set(true);
    try {
      const { results } = await this.api.post<{ results: DeleteResult[] }>('/files/delete', {
        urls: files.map((file) => file.url),
      });
      // not_found means it's already gone, so it leaves the gallery too.
      const gone = new Set(
        files.filter((_, i) => results[i].status !== 'error').map((file) => file.file_id),
      );
      this.gallery.files.update((all) => all.filter((file) => !gone.has(file.file_id)));
      this.gallery.clearSelection();
      this.snackBar.open(summary(gone.size, results), 'OK', { duration: 6000 });
    } catch (err) {
      this.snackBar.open(err instanceof Error ? err.message : String(err), 'OK');
    } finally {
      this.busy.set(false);
      this.confirming.set(false);
    }
  }
}

function summary(deleted: number, results: DeleteResult[]): string {
  const deletedText = `Deleted ${deleted} ${deleted === 1 ? 'file' : 'files'}.`;
  const failed = results.filter((result) => result.status === 'error');
  if (failed.length === 0) return deletedText;
  const reasons = [...new Set(failed.map((result) => result.detail))].join(' ');
  return `${deletedText} ${failed.length} couldn't be deleted: ${reasons}`;
}
