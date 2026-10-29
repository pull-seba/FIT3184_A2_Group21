import { DatePipe, PercentPipe } from '@angular/common';
import { Component, computed, inject, input, model, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatDialog } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { FileSummary, describe } from './file-summary';
import { TagChips } from './tag-chips/tag-chips';
import { Viewer, ViewerData } from './viewer/viewer';

@Component({
  selector: 'app-gallery',
  imports: [DatePipe, PercentPipe, MatButtonModule, MatCheckboxModule, MatIconModule, TagChips],
  templateUrl: './gallery.html',
  styleUrl: './gallery.css',
})
export class Gallery {
  readonly files = model.required<FileSummary[]>();
  readonly loading = input(false);
  readonly emptyMessage = input('No files match this search.');

  private readonly dialog = inject(MatDialog);
  private readonly selectedIds = signal(new Set<string>());
  private readonly brokenUrls = signal(new Set<string>());

  readonly selected = computed(() =>
    this.files().filter((file) => this.selectedIds().has(file.file_id)),
  );
  readonly allSelected = computed(
    () => this.files().length > 0 && this.selected().length === this.files().length,
  );
  readonly placeholderTiles = Array.from({ length: 8 }, (_, index) => index);
  readonly describe = describe;

  isSelected(file: FileSummary): boolean {
    return this.selectedIds().has(file.file_id);
  }

  toggle(file: FileSummary): void {
    this.selectedIds.update((ids) => {
      const next = new Set(ids);
      if (next.has(file.file_id)) {
        next.delete(file.file_id);
      } else {
        next.add(file.file_id);
      }
      return next;
    });
  }

  toggleAll(): void {
    const everyId = this.files().map((file) => file.file_id);
    this.selectedIds.set(new Set(this.allSelected() ? [] : everyId));
  }

  clearSelection(): void {
    this.selectedIds.set(new Set());
  }

  isBroken(url: string): boolean {
    return this.brokenUrls().has(url);
  }

  markBroken(url: string): void {
    this.brokenUrls.update((urls) => new Set(urls).add(url));
  }

  open(index: number): void {
    this.dialog.open<Viewer, ViewerData>(Viewer, {
      data: { files: this.files(), index },
      maxWidth: '95vw',
    });
  }
}
