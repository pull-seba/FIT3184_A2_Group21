export interface FileSummary {
  file_id: string;
  file_type: 'image' | 'video';
  url: string;
  thumbnail_url: string | null;
  tags: Record<string, number>;
  uploaded_at: string;
  score?: number;
}

export function describe(file: FileSummary): string {
  const kind = file.file_type === 'video' ? 'Video' : 'Photo';
  const tags = Object.entries(file.tags).map(([tag, count]) => `${count} ${tag}`);
  return `${kind}: ${tags.join(', ') || 'no animals tagged yet'}`;
}
