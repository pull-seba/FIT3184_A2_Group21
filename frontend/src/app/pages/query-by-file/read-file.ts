// Shared by the search by file and lost pet pages: checks a chosen photo, turns it into the base64
// the search routes take (docs/contracts/api-routes.md) and words a failed search for people.

// The photo types and size the app accepts everywhere (docs/decisions.md, 27 Oct).
export const PHOTO_TYPES = ['image/jpeg', 'image/png', 'image/webp'];
export const VIDEO_TYPES = ['video/mp4', 'video/quicktime'];
const MAX_BYTES = 20 * 1024 * 1024;
const MAX_VIDEO_BYTES = 200 * 1024 * 1024;
const MAX_SIDE = 1024;
const FRAME_SECONDS = 10; // the rate process_upload extracts frames at (rubric 2.1.2)
const MAX_FRAMES = 30; // a video over 5 minutes is sampled more thinly, so a search stays short

// Why the page won't send this photo, or null if it's fine. Checked before sending, so a wrong
// file never leaves the browser.
export function photoProblem(file: File): string | null {
  if (!PHOTO_TYPES.includes(file.type)) return 'Choose a JPEG, PNG or WebP photo.';
  if (file.size > MAX_BYTES) return 'That photo is over 20 MB. Choose a smaller one.';
  return null;
}

export function videoProblem(file: File): string | null {
  return file.size > MAX_VIDEO_BYTES ? 'That video is over 200 MB. Choose a smaller one.' : null;
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
  const photo = jpegBase64(image, image.width, image.height);
  image.close();
  return photo;
}

// One frame of the video every 10 s, each the same JPEG base64 as readPhoto's. They're drawn
// here, so the video itself never leaves the browser.
export async function readFrames(file: File): Promise<string[]> {
  const url = URL.createObjectURL(file);
  const video = document.createElement('video');
  video.muted = true;
  video.preload = 'auto';
  video.src = url;
  try {
    await reached(video, 'loadeddata');
    if (!video.videoWidth) throw new Error('no picture'); // a codec this browser can't show
    const step = Math.max(FRAME_SECONDS, video.duration / MAX_FRAMES);
    const frames: string[] = [];
    for (let time = 0; time < video.duration; time += step) {
      // Frame 0 is already on show once the video has loaded, so it needs no seek.
      if (time > 0) {
        video.currentTime = time;
        await reached(video, 'seeked');
      }
      frames.push(jpegBase64(video, video.videoWidth, video.videoHeight));
    }
    return frames;
  } catch {
    throw new Error("This video couldn't be read. Try an MP4 video.");
  } finally {
    URL.revokeObjectURL(url);
  }
}

// Waits for the video's event, or fails if the browser can't decode it.
function reached(video: HTMLVideoElement, event: string): Promise<void> {
  return new Promise((resolve, reject) => {
    video.addEventListener(event, () => resolve(), { once: true });
    video.addEventListener('error', () => reject(video.error), { once: true });
  });
}

function jpegBase64(source: CanvasImageSource, width: number, height: number): string {
  const scale = Math.min(1, MAX_SIDE / Math.max(width, height));
  const canvas = document.createElement('canvas');
  canvas.width = Math.round(width * scale);
  canvas.height = Math.round(height * scale);
  canvas.getContext('2d')!.drawImage(source, 0, 0, canvas.width, canvas.height);
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
