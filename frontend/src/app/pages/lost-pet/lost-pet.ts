import { Component, computed, inject, OnDestroy, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';

import tagList from '../../../../../shared/tags.json';
import { ApiService } from '../../api/api.service';
import { Gallery } from '../../components/gallery/gallery';
import { FileSummary } from '../../components/gallery/file-summary';
import { PHOTO_TYPES, photoProblem, problem, readPhoto } from '../query-by-file/read-file';

// POST /search/lost-pet (docs/contracts/api-routes.md). score is null for a search without a photo.
type LostPetResult = FileSummary & { score: number | null; sighting_id: string };

@Component({
  selector: 'app-lost-pet',
  imports: [
    MatButtonModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatSelectModule,
    Gallery,
  ],
  templateUrl: './lost-pet.html',
  styleUrl: './lost-pet.css',
})
export class LostPet implements OnDestroy {
  private readonly api = inject(ApiService);
  readonly accepted = PHOTO_TYPES.join(',');
  readonly speciesList = tagList.lost_pet_species;
  readonly colourList = tagList.lost_pet_colours;
  readonly dayChoices = [7, 30, 90];

  readonly file = signal<File | null>(null);
  readonly preview = signal<string | null>(null);
  readonly species = signal(''); // '' = any species, only allowed with a photo
  readonly colour = signal(''); // '' = any colour
  readonly breed = signal(''); // '' = any breed
  readonly sinceDays = signal(30);
  readonly loading = signal(false);
  readonly error = signal('');
  readonly results = signal<FileSummary[]>([]);
  // Set when results arrive, from the search that was sent, so it can't change under them.
  readonly order = signal('');
  // The contract needs a photo or a species.
  readonly canSearch = computed(
    () => !this.loading() && (this.file() !== null || this.species() !== ''),
  );

  choose(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    input.value = ''; // so choosing the same file again still fires (change)
    if (!file) return;
    const reason = photoProblem(file);
    this.error.set(reason ?? '');
    this.setFile(reason ? null : file);
  }

  removePhoto(): void {
    this.setFile(null);
  }

  async search(): Promise<void> {
    if (!this.canSearch()) return;
    const file = this.file();
    this.loading.set(true);
    this.error.set('');
    try {
      const response = await this.api.post<{ results: LostPetResult[] }>('/search/lost-pet', {
        // undefined leaves image_base64 out of the JSON: the contract makes it optional.
        image_base64: file ? await readPhoto(file) : undefined,
        species: this.species() || null,
        colour: this.colour() || null,
        breed: this.breed().trim() || null,
        since_days: this.sinceDays(),
      });
      // The gallery draws a "% match" badge whenever score !== undefined, so a null score (a
      // search without a photo has nothing to score against) becomes undefined: no badge.
      this.results.set(
        response.results.map((result) => ({ ...result, score: result.score ?? undefined })),
      );
      this.order.set(file ? 'Best match first' : 'Newest first');
    } catch (err) {
      this.results.set([]);
      this.order.set('');
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
