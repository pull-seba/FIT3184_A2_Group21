import { Component, inject, signal } from '@angular/core';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';

import { ApiError, ApiService } from '../../api/api.service';
import { DeleteAction } from '../../components/gallery/actions/delete/delete';
import { Gallery } from '../../components/gallery/gallery';
import { FileSummary } from '../../components/gallery/file-summary';

// docs/contracts/storage-layout.md, "Accepted uploads". upload_init rejects anything else anyway;
// this only narrows the file picker.
const ACCEPTED = 'image/jpeg,image/png,image/webp,video/mp4,video/quicktime';

const POLL_MS = 2000;
const MAX_POLLS = 90; // 3 minutes, enough to tag a 60 s clip

// What the page shows while it waits for each pipeline step.
const WAITING_FOR: Record<string, string> = {
  thumbnail: 'Making the thumbnail…',
  frames: 'Taking video frames…',
  tagging: 'Finding animals…',
};

// POST /uploads/init (docs/contracts/api-routes.md).
type InitResponse =
  | { status: 'duplicate'; file: FileSummary }
  | { status: 'upload'; file_id: string; upload_url: string; headers: Record<string, string> };

// GET /files/{file_id}: a FileSummary plus each finished step, "done" or "failed".
type FileProgress = FileSummary & { pipeline: Record<string, 'done' | 'failed'> };

type Step = 'checking' | 'uploading' | 'processing' | 'done' | 'duplicate' | 'error';

// One chosen file's progress, shown as a row while it uploads and processes.
class UploadRow {
  readonly step = signal<Step>('checking');
  readonly text = signal('Checking for duplicates…');
  readonly percent = signal(0);

  constructor(readonly file: File) {}

  set(step: Step, text: string): void {
    this.step.set(step);
    this.text.set(text);
  }
}

@Component({
  selector: 'app-upload',
  imports: [MatCheckboxModule, MatIconModule, MatProgressBarModule, Gallery, DeleteAction],
  templateUrl: './upload.html',
  styleUrl: './upload.css',
})
export class Upload {
  private readonly api = inject(ApiService);
  readonly accepted = ACCEPTED;
  readonly isPublic = signal(true);
  readonly rows = signal<UploadRow[]>([]);
  // Processed files and duplicates, newest first, shown in the shared gallery.
  readonly uploaded = signal<FileSummary[]>([]);
  readonly icons: Record<Step, string> = {
    checking: 'fingerprint',
    uploading: 'cloud_upload',
    processing: 'hourglass_top',
    done: 'check_circle',
    duplicate: 'content_copy',
    error: 'error',
  };

  choose(event: Event): void {
    const input = event.target as HTMLInputElement;
    const rows = Array.from(input.files ?? [], (file) => new UploadRow(file));
    input.value = ''; // so choosing the same file again still fires (change)
    this.rows.update((existing) => [...rows, ...existing]);
    // All at once: each row shows its own progress.
    for (const row of rows) void this.upload(row, this.isPublic());
  }

  private async upload(row: UploadRow, isPublic: boolean): Promise<void> {
    try {
      const { file } = row;
      const init = await this.api.post<InitResponse>('/uploads/init', {
        sha256: await sha256(file),
        filename: file.name,
        content_type: file.type,
        size_bytes: file.size,
        is_public: isPublic,
      });
      if (init.status === 'duplicate') {
        row.set('duplicate', 'Already uploaded, so it was skipped.');
        this.show(init.file);
        return;
      }

      row.set('uploading', 'Uploading…');
      const status = await put(init.upload_url, init.headers, file, (percent) =>
        row.percent.set(percent),
      );
      // 412: the object arrived after init checked, e.g. the same file in two tabs (storage-layout.md).
      if (status === 412) {
        row.set('duplicate', 'Already uploaded, so it was skipped.');
        return;
      }
      await this.waitForProcessing(row, init.file_id);
    } catch (err) {
      row.set('error', err instanceof Error ? err.message : String(err));
    }
  }

  // Polls GET /files/{id} until every step the file needs has finished, so the row updates without
  // a refresh. A 404 means process_upload hasn't verified the upload yet.
  private async waitForProcessing(row: UploadRow, fileId: string): Promise<void> {
    row.set('processing', 'Checking the upload…');
    for (let poll = 0; poll < MAX_POLLS; poll++) {
      await new Promise((resolve) => setTimeout(resolve, POLL_MS));
      let file: FileProgress;
      try {
        file = await this.api.get<FileProgress>(`/files/${fileId}`);
      } catch (err) {
        if (err instanceof ApiError && err.status === 404) continue;
        throw err;
      }

      const steps =
        file.file_type === 'video' ? ['thumbnail', 'frames', 'tagging'] : ['thumbnail', 'tagging'];
      const failed = steps.filter((step) => file.pipeline[step] === 'failed');
      const waiting = steps.find((step) => !file.pipeline[step]);
      // A failed step ends the wait: a video whose frames failed never gets tagged.
      if (waiting && failed.length === 0) {
        row.text.set(WAITING_FOR[waiting]);
        continue;
      }
      if (failed.length > 0) {
        row.set('error', `Uploaded, but its ${failed.join(' and ')} failed.`);
      } else {
        row.set('done', 'Uploaded and tagged.');
      }
      this.show(file);
      return;
    }
    row.set('done', "Uploaded. It's still processing and will show in search when it's ready.");
  }

  private show(file: FileSummary): void {
    this.uploaded.update((files) => [
      file,
      ...files.filter((other) => other.file_id !== file.file_id),
    ]);
  }
}

// The file's ID: the lowercase hex SHA-256 of its bytes, which upload_init checks for duplicates.
async function sha256(file: File): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', await file.arrayBuffer());
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('');
}

// fetch can't report upload progress, so the PUT uses XMLHttpRequest. It goes straight to Cloud
// Storage through the signed URL, not to the gateway, so it doesn't go through ApiService.
function put(
  url: string,
  headers: Record<string, string>,
  file: File,
  onProgress: (percent: number) => void,
): Promise<number> {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open('PUT', url);
    // Exactly the headers upload_init signed: Cloud Storage refuses the upload if any differ.
    for (const [name, value] of Object.entries(headers)) request.setRequestHeader(name, value);
    request.upload.onprogress = (event) =>
      onProgress(Math.round((100 * event.loaded) / event.total));
    request.onload = () =>
      request.status < 300 || request.status === 412
        ? resolve(request.status)
        : reject(new Error(`Upload failed (${request.status}). Try again.`));
    request.onerror = () =>
      reject(new Error('Upload failed. Check your connection and try again.'));
    request.send(file);
  });
}
