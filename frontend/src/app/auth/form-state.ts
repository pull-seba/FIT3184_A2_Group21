import { signal } from '@angular/core';

export interface Message {
  text: string;
  type: 'error' | 'success';
}

export class FormState {
  readonly busy = signal(false);
  readonly message = signal<Message | null>(null);

  async submit(event: Event, action: (data: FormData) => Promise<void>): Promise<void> {
    event.preventDefault();
    this.busy.set(true);
    this.message.set(null);
    try {
      await action(new FormData(event.target as HTMLFormElement));
    } catch (err) {
      this.error(err instanceof Error ? err.message : String(err));
    } finally {
      this.busy.set(false);
    }
  }

  success(text: string): void {
    this.message.set({ text, type: 'success' });
  }

  error(text: string): void {
    this.message.set({ text, type: 'error' });
  }
}

export function field(data: FormData, name: string): string {
  return String(data.get(name) ?? '').trim();
}

export function passwordsMatch(data: FormData): void {
  if (data.get('password') !== data.get('confirm')) throw new Error('Passwords do not match.');
}
