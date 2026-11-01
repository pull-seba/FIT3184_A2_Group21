import { Component, inject, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';

import { ApiService } from '../../api/api.service';
import { TagsAction } from '../../components/gallery/actions/tags/tags';
import { FileSummary } from '../../components/gallery/file-summary';
import { Gallery } from '../../components/gallery/gallery';
import { TAG_NAMES } from '../../components/gallery/tags';

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
  ],
  templateUrl: './search.html',
  styleUrl: './search.css',
})
export class Search {
  private readonly api = inject(ApiService);
  readonly tagNames = TAG_NAMES;
  readonly results = signal<FileSummary[]>([]);
  // Set when results arrive, so the heading always names the search they came from.
  readonly resultsFor = signal('');
  readonly fullSize = signal<FullSize | null>(null);
  readonly searching = signal(false);
  readonly lookingUp = signal(false);
  readonly error = signal('');

  searchTags(form: HTMLFormElement): void {
    const query: Record<string, number> = {};
    new FormData(form).forEach((count, tag) => {
      if (count) query[tag] = Number(count);
    });
    if (Object.keys(query).length === 0) {
      this.error.set('Enter a minimum count for at least one tag.');
      return;
    }
    const asked = Object.entries(query)
      .map(([tag, count]) => `${tag} ≥ ${count}`)
      .join(' and ');
    void this.showResults(asked, this.api.post('/search/tags', query));
  }

  searchSpecies(name: string): void {
    void this.showResults(`any ${name}`, this.api.get('/search/species', { name }));
  }

  private async showResults(
    asked: string,
    request: Promise<{ results: FileSummary[] }>,
  ): Promise<void> {
    this.searching.set(true);
    this.error.set('');
    try {
      this.results.set((await request).results);
      this.resultsFor.set(asked);
    } catch (err) {
      this.error.set(err instanceof Error ? err.message : String(err));
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
      this.error.set(err instanceof Error ? err.message : String(err));
    } finally {
      this.lookingUp.set(false);
    }
  }
}
