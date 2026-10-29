import { Component, computed, input } from '@angular/core';
import { MatChipsModule } from '@angular/material/chips';
import { TAG_GROUP } from '../tags';

@Component({
  selector: 'app-tag-chips',
  imports: [MatChipsModule],
  template: `
    <mat-chip-set>
      @for (tag of tagList(); track tag.name) {
        <mat-chip [class]="'tag-' + tag.group">{{ tag.name }} ×{{ tag.count }}</mat-chip>
      } @empty {
        <mat-chip disabled>untagged</mat-chip>
      }
    </mat-chip-set>
  `,
})
export class TagChips {
  readonly tags = input.required<Record<string, number>>();

  readonly tagList = computed(() =>
    Object.entries(this.tags()).map(([name, count]) => ({
      name,
      count,
      group: TAG_GROUP.get(name) ?? 'either',
    })),
  );
}
