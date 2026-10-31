import { Component, inject, OnInit, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatCheckboxModule } from '@angular/material/checkbox';

import tagList from '../../../../../shared/tags.json';
import { ApiService } from '../../api/api.service';

// GET and PUT /notifications/subscriptions (docs/contracts/api-routes.md).
interface Subscriptions {
  tags: string[];
}

@Component({
  selector: 'app-notifications',
  imports: [MatButtonModule, MatCheckboxModule],
  templateUrl: './notifications.html',
  styleUrl: './notifications.css',
})
export class Notifications implements OnInit {
  private readonly api = inject(ApiService);

  // One list of tag names for the whole app, so these match what tagging produces.
  readonly tags = tagList.tags.map((tag) => tag.name);
  readonly chosen = signal<string[]>([]);
  readonly loading = signal(true);
  readonly loaded = signal(false);
  readonly saving = signal(false);
  readonly message = signal('');
  readonly failed = signal(false);

  async ngOnInit(): Promise<void> {
    try {
      const { tags } = await this.api.get<Subscriptions>('/notifications/subscriptions');
      this.chosen.set(tags);
      this.loaded.set(true);
    } catch {
      this.show("Your alerts couldn't be loaded. Please try again.", true);
    } finally {
      this.loading.set(false);
    }
  }

  toggle(tag: string, checked: boolean): void {
    this.chosen.update((tags) => (checked ? [...tags, tag] : tags.filter((t) => t !== tag)));
    this.message.set('');
  }

  async save(): Promise<void> {
    this.saving.set(true);
    this.message.set('');
    try {
      await this.api.put('/notifications/subscriptions', { tags: this.chosen() });
      // SNS holds a new subscription until its owner confirms it from the email it sends.
      this.show(
        this.chosen().length
          ? 'Saved. If this is your first alert, confirm it from the email AWS sends you.'
          : "Saved. You won't get any alerts.",
        false,
      );
    } catch {
      this.show("Your alerts couldn't be saved. Please try again.", true);
    } finally {
      this.saving.set(false);
    }
  }

  private show(text: string, failed: boolean): void {
    this.message.set(text);
    this.failed.set(failed);
  }
}
