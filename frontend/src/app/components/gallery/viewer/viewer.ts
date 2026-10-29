import { DatePipe } from '@angular/common';
import { Component, computed, inject, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MAT_DIALOG_DATA, MatDialogModule } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { FileSummary, describe } from '../file-summary';
import { TagChips } from '../tag-chips/tag-chips';

export interface ViewerData {
  files: FileSummary[];
  index: number;
}

@Component({
  selector: 'app-viewer',
  imports: [DatePipe, MatButtonModule, MatDialogModule, MatIconModule, TagChips],
  templateUrl: './viewer.html',
  styleUrl: './viewer.css',
  host: {
    '(keydown.arrowleft)': 'onArrow($event, -1)',
    '(keydown.arrowright)': 'onArrow($event, 1)',
  },
})
export class Viewer {
  private readonly data = inject<ViewerData>(MAT_DIALOG_DATA);

  readonly index = signal(this.data.index);
  readonly file = computed(() => this.data.files[this.index()]);
  readonly count = this.data.files.length;
  readonly describe = describe;

  step(delta: number): void {
    this.index.update((index) => (index + delta + this.count) % this.count);
  }

  onArrow(event: Event, delta: number): void {
    if (!(event.target instanceof HTMLVideoElement)) {
      this.step(delta);
    }
  }
}
