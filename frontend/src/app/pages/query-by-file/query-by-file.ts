import { Component, computed, inject, OnDestroy, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';

import { ApiService } from '../../api/api.service';
import { DeleteAction } from '../../components/gallery/actions/delete/delete';
import { Gallery } from '../../components/gallery/gallery';
import { FileSummary } from '../../components/gallery/file-summary';
import { PHOTO_TYPES, photoProblem, problem, readPhoto } from './read-file';

// POST /search/by-file (docs/contracts/api-routes.md).
interface ByFileResponse {
  detected_tags: Record<string, number>;
  results: FileSummary[];
}

@Component({
  selector: 'app-query-by-file',
  imports: [MatButtonModule, MatIconModule, Gallery, DeleteAction],
  templateUrl: './query-by-file.html',
  styleUrl: './query-by-file.css',
})
export class QueryByFile implements OnDestroy {
  private readonly api = inject(ApiService);
  readonly accepted = PHOTO_TYPES.join(',');
  readonly file = signal<File | null>(null);
  readonly preview = signal<string | null>(null);
  readonly loading = signal(false);
  readonly error = signal('');
  // null until a search finishes, so "Detected" only shows for the photo that was searched.
  readonly detected = signal<Record<string, number> | null>(null);
  readonly results = signal<FileSummary[]>([]);
  // "2 fox, 1 cat": the same "count tag" form as the gallery's alt text.
  readonly detectedText = computed(() =>
    Object.entries(this.detected() ?? {})
      .map(([tag, count]) => `${count} ${tag}`)
      .join(', '),
  );

  choose(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    input.value = ''; // so choosing the same file again still fires (change)
    if (!file) return;
    const reason = photoProblem(file);
    this.error.set(reason ?? '');
    this.setFile(reason ? null : file);
    this.detected.set(null);
    this.results.set([]);
  }

  async search(): Promise<void> {
    const file = this.file();
    if (!file || this.loading()) return;
    this.loading.set(true);
    this.error.set('');
    this.detected.set(null);
    try {
      const response = await this.api.post<ByFileResponse>('/search/by-file', {
        file_base64: await readPhoto(file),
        content_type: 'image/jpeg', // readPhoto always sends JPEG
      });
      this.detected.set(response.detected_tags);
      this.results.set(response.results);
    } catch (err) {
      this.results.set([]);
      this.error.set(problem(err));
    } finally {
      this.loading.set(false);
    }
  }

  ngOnDestroy(): void {
    this.setFile(null);
  }

  // The preview is an object URL pointing at the file in memory; revoking the old one frees it.
  private setFile(file: File | null): void {
    const old = this.preview();
    if (old) URL.revokeObjectURL(old);
    this.file.set(file);
    this.preview.set(file ? URL.createObjectURL(file) : null);
  }
}
