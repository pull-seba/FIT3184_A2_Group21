import { Component, inject, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';

import { ApiService } from '../../api/api.service';
import { DeleteAction } from '../../components/gallery/actions/delete/delete';
import { TagsAction } from '../../components/gallery/actions/tags/tags';
import { FileSummary } from '../../components/gallery/file-summary';
import { Gallery } from '../../components/gallery/gallery';
import { TAG_NAMES } from '../../components/gallery/tags';
import { problem } from '../query-by-file/read-file';

// POST /search/thumbnail (docs/contracts/api-routes.md).
interface FullSize {
  file_type: 'image' | 'video';
  url: string;
}

@Component({
  selector: 'app-search',
  imports: [
    MatButtonModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    Gallery,
    TagsAction,
    DeleteAction,
  ],
  templateUrl: './search.html',
  styleUrl: './search.css',
})
export class Search {
  private readonly api = inject(ApiService);
  readonly tagNames = TAG_NAMES;
  readonly results = signal<FileSummary[]>([]);
  readonly searched = signal(false);
  readonly fullSize = signal<FullSize | null>(null);
  readonly searching = signal(false);
  readonly lookingUp = signal(false);
  readonly error = signal('');

  async searchTags(form: HTMLFormElement): Promise<void> {
    const query: Record<string, number> = {};
    // A blank or 0 count leaves the tag out of the query.
    new FormData(form).forEach((count, tag) => {
      if (Number(count)) query[tag] = Number(count);
    });
    this.searching.set(true);
    this.error.set('');
    try {
      const { results } = await this.api.post<{ results: FileSummary[] }>('/search/tags', query);
      this.results.set(results);
      this.searched.set(true);
    } catch (err) {
      this.error.set(problem(err));
    } finally {
      this.searching.set(false);
    }
  }

  async findFullSize(thumbnailUrl: string): Promise<void> {
    this.fullSize.set(null);
    this.lookingUp.set(true);
    this.error.set('');
    try {
      this.fullSize.set(
        await this.api.post<FullSize>('/search/thumbnail', { thumbnail_url: thumbnailUrl }),
      );
    } catch (err) {
      this.error.set(problem(err));
    } finally {
      this.lookingUp.set(false);
    }
  }
}
