import { Component, computed, inject, OnDestroy, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';

import { ApiService } from '../../api/api.service';
import { DeleteAction } from '../../components/gallery/actions/delete/delete';
import { Gallery } from '../../components/gallery/gallery';
import { FileSummary } from '../../components/gallery/file-summary';
import {
  PHOTO_TYPES,
  photoProblem,
  problem,
  readFrames,
  readPhoto,
  VIDEO_TYPES,
  videoProblem,
} from './read-file';

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
  readonly accepted = [...PHOTO_TYPES, ...VIDEO_TYPES].join(',');
  readonly file = signal<File | null>(null);
  readonly isVideo = computed(() => VIDEO_TYPES.includes(this.file()?.type ?? ''));
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
    const reason = VIDEO_TYPES.includes(file.type) ? videoProblem(file) : photoProblem(file);
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
      const response = this.isVideo()
        ? await this.searchVideo(file)
        : await this.searchImage(await readPhoto(file));
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

  private searchImage(base64: string): Promise<ByFileResponse> {
    return this.api.post<ByFileResponse>('/search/by-file', {
      file_base64: base64,
      content_type: 'image/jpeg', // readPhoto and readFrames always send JPEG
    });
  }

  // The route takes images, so a video is searched by its frames. A tag's count is its highest
  // in any one frame, never the sum. Each species found then needs a minimum of 1, the same rule
  // search_by_file uses for a photo, and all of them must be in a file (AND).
  private async searchVideo(file: File): Promise<ByFileResponse> {
    const detected: Record<string, number> = {};
    for (const frame of await readFrames(file)) {
      const { detected_tags } = await this.searchImage(frame);
      for (const [tag, count] of Object.entries(detected_tags)) {
        detected[tag] = Math.max(detected[tag] ?? 0, count);
      }
    }
    const tags = Object.keys(detected);
    if (!tags.length) return { detected_tags: detected, results: [] };
    const { results } = await this.api.post<{ results: FileSummary[] }>('/search/tags', tags);
    return { detected_tags: detected, results };
  }

  // The preview is an object URL pointing at the file in memory; revoking the old one frees it.
  private setFile(file: File | null): void {
    const old = this.preview();
    if (old) URL.revokeObjectURL(old);
    this.file.set(file);
    this.preview.set(file ? URL.createObjectURL(file) : null);
  }
}
