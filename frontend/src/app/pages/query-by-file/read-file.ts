// Shared by the search by file and lost pet pages: checks a chosen photo, turns it into the base64
// the search routes take (docs/contracts/api-routes.md) and words a failed search for people.

// The photo types and size the app accepts everywhere (docs/decisions.md, 27 Oct).
export const PHOTO_TYPES = ['image/jpeg', 'image/png', 'image/webp'];
const MAX_BYTES = 20 * 1024 * 1024;
const MAX_SIDE = 1024;

// Why the page won't send this photo, or null if it's fine. Checked before sending, so a wrong
// file never leaves the browser.
export function photoProblem(file: File): string | null {
  if (!PHOTO_TYPES.includes(file.type)) return 'Choose a JPEG, PNG or WebP photo.';
  if (file.size > MAX_BYTES) return 'That photo is over 20 MB. Choose a smaller one.';
  return null;
}

// The contract says images inside JSON are resized in the browser to about 1024 px first, so the
// photo is redrawn on a canvas no bigger than that and saved as JPEG. That keeps the request small
// and drops the photo's metadata, such as where it was taken. The result is always JPEG.
export async function readPhoto(file: File): Promise<string> {
  let image: ImageBitmap;
  try {
    image = await createImageBitmap(file);
  } catch {
    throw new Error("This photo couldn't be read. Try another JPEG, PNG or WebP photo.");
  }
  const scale = Math.min(1, MAX_SIDE / Math.max(image.width, image.height));
  const canvas = document.createElement('canvas');
  canvas.width = Math.round(image.width * scale);
  canvas.height = Math.round(image.height * scale);
  canvas.getContext('2d')!.drawImage(image, 0, 0, canvas.width, canvas.height);
  image.close();
  // A data URL is "data:image/jpeg;base64,<base64>"; the API wants only the part after the comma.
  return canvas.toDataURL('image/jpeg', 0.9).split(',')[1];
}

// The message to show when a search fails. ApiError and readPhoto's errors already have one for
// people; fetch rejects with a TypeError when the network is down, and "Failed to fetch" isn't one.
export function problem(err: unknown): string {
  if (err instanceof TypeError) {
    return "Can't reach the server. Check your connection and try again.";
  }
  return err instanceof Error ? err.message : String(err);
}
