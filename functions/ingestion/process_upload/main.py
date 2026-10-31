"""process_upload: runs when a file lands in the media bucket. Re-hashes it to
prove its key really is its SHA-256 and writes the file's base record, then
makes its thumbnail and, for a video, a frame every 10 s, in the derived
bucket. Anything that isn't a valid upload is deleted with no record, so it
never counts as a duplicate or shows in queries.

Owner: member 2. Rubric: 2.1.1, 2.1.2. Trigger: see README.md.

Idempotent: Eventarc can deliver the same event twice, so a verified file
isn't re-hashed, a step its record shows as finished isn't redone, and
deleting an object that's already gone counts as done. Any other error is
left to raise: functions-framework logs it and returns 500, so Eventarc
retries (deployed with --retry).
"""

import hashlib
import json
import re
import tempfile
import urllib.parse
from pathlib import Path

import cv2
import functions_framework
from google.api_core import exceptions
from google.cloud import firestore, pubsub_v1, storage

from ecoguard_common.logs import log
from ecoguard_common.uploads import ACCEPTED

db = firestore.Client()
gcs = storage.Client()
publisher = pubsub_v1.PublisherClient()

DERIVED_BUCKET = "ecoguard-g21-derived"
FRAMES_READY = "projects/ecoguard-g21/topics/frames-ready"
THUMBNAIL_SIDE = 320  # px, the longest side (storage-layout.md)
FRAME_EVERY_MS = 10_000

MEDIA_KEY = re.compile(r"(?P<file_id>[0-9a-f]{64})\.(?P<ext>[a-z0-9]+)")


def rejection_reason(data: dict):
    """Why the event's object isn't a valid upload, or None. Needs no download."""
    match = MEDIA_KEY.fullmatch(data["name"])
    if not match:
        return "bad_key"
    extension, size_limit = ACCEPTED.get(data.get("contentType"), (None, 0))
    if extension != match["ext"]:
        return "bad_type"
    # upload_init only saw the size the browser claimed; this one is stored.
    if int(data["size"]) > size_limit:
        return "too_large"
    # Every upload_init URL signs this header in.
    if not (data.get("metadata") or {}).get("uploaded-by"):
        return "no_uploader"
    return None


def sha256_of(path: str) -> str:
    """Hashes the file in chunks, so a 200 MB video is never in memory twice."""
    with open(path, "rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def reject(blob, media_key: str, reason: str):
    """Deletes an object that isn't a valid upload. The blob is pinned to the
    event's generation, so this only ever deletes the object that fired it."""
    try:
        blob.delete()
    except exceptions.NotFound:
        pass  # a repeat event: already deleted
    log(
        "WARNING",
        "upload rejected and deleted",
        media_key=media_key,
        reason=reason,
    )


def base_record(file_id: str, data: dict) -> dict:
    """The fields process_upload owns (docs/contracts/firestore-schema.md)."""
    metadata = data.get("metadata") or {}
    content_type = data["contentType"]
    media_key = data["name"]
    return {
        "file_id": file_id,
        "file_type": content_type.split("/")[0],  # "image" or "video"
        "content_type": content_type,
        # upload_init URL-encodes it: metadata headers must be plain ASCII.
        "original_filename": urllib.parse.unquote(
            metadata.get("original-filename", media_key)
        ),
        "size_bytes": int(data["size"]),
        "media_bucket": data["bucket"],
        "media_key": media_key,
        "media_uri": f"gs://{data['bucket']}/{media_key}",
        "uploaded_by": metadata["uploaded-by"],
        "uploaded_at": firestore.SERVER_TIMESTAMP,
        "is_public": metadata.get("is-public", "true") == "true",
        "status": "active",
    }


def finished(record: dict, file_type: str) -> bool:
    """Whether an earlier delivery finished every step this file needs.
    "failed" counts: the same bytes would fail again."""
    steps = ["thumbnail"] if file_type == "image" else ["thumbnail", "frames"]
    return all(step in record.get("pipeline", {}) for step in steps)


def jpeg(image, quality: int = 90) -> bytes:
    _, data = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return data.tobytes()


def thumbnail(image) -> bytes:
    """Longest side 320 px with the aspect ratio kept, JPEG quality 80.
    INTER_AREA averages the pixels it drops, so shrinking stays smooth."""
    height, width = image.shape[:2]
    scale = THUMBNAIL_SIDE / max(width, height)
    size = (round(width * scale), round(height * scale))
    return jpeg(cv2.resize(image, size, interpolation=cv2.INTER_AREA), 80)


def save(key: str, data: bytes):
    gcs.bucket(DERIVED_BUCKET).blob(key).upload_from_string(
        data, content_type="image/jpeg"
    )


def thumbnail_fields(file_id: str, image) -> dict:
    key = f"thumbs/{file_id}.jpg"
    save(key, thumbnail(image))
    return {
        "thumbnail_key": key,
        "thumbnail_uri": f"gs://{DERIVED_BUCKET}/{key}",
        "pipeline": {"thumbnail": "done"},
    }


def image_fields(file_id: str, path: str) -> dict:
    image = cv2.imread(path)  # None when OpenCV can't decode the bytes
    if image is None:
        log("WARNING", "image could not be decoded", file_id=file_id)
        return {"pipeline": {"thumbnail": "failed"}}
    return thumbnail_fields(file_id, image)


def frames_every_10s(path: str) -> tuple[list, float]:
    """The frames at 0, 10, 20 s and so on, and the duration in seconds.
    Seeks to each one rather than decoding every frame. A clip under 10 s
    still gives its first frame."""
    video = cv2.VideoCapture(path)
    fps = video.get(cv2.CAP_PROP_FPS)
    duration_ms = video.get(cv2.CAP_PROP_FRAME_COUNT) / fps * 1000 if fps else 0
    frames = []
    for position_ms in range(0, max(int(duration_ms), 1), FRAME_EVERY_MS):
        video.set(cv2.CAP_PROP_POS_MSEC, position_ms)
        ok, frame = video.read()
        if not ok:
            break
        frames.append(frame)
    video.release()
    return frames, round(duration_ms / 1000, 1)


def video_fields(file_id: str, path: str) -> dict:
    frames, duration_s = frames_every_10s(path)
    if not frames:
        log("WARNING", "video could not be decoded", file_id=file_id)
        return {"pipeline": {"thumbnail": "failed", "frames": "failed"}}
    frame_keys = [f"frames/{file_id}/{i:04d}.jpg" for i in range(len(frames))]
    for key, frame in zip(frame_keys, frames):
        save(key, jpeg(frame))
    fields = thumbnail_fields(file_id, frames[0])  # the poster: the first frame
    # Published before the record says "done": if this delivery fails after
    # publishing, the retry publishes again, and tagging handles repeats.
    message = {
        "file_id": file_id,
        "bucket": DERIVED_BUCKET,
        "frame_keys": frame_keys,
        "duration_s": duration_s,
    }
    # result() waits for Pub/Sub, so a failed publish raises and is retried.
    publisher.publish(FRAMES_READY, json.dumps(message).encode()).result()
    fields |= {"frame_keys": frame_keys, "duration_s": duration_s}
    fields["pipeline"]["frames"] = "done"
    return fields


@functions_framework.cloud_event
def handler(event):
    data = event.data  # the Cloud Storage object; numbers arrive as strings
    media_key = data["name"]
    blob = gcs.bucket(data["bucket"]).blob(
        media_key, generation=int(data["generation"])
    )
    reason = rejection_reason(data)
    if reason:
        return reject(blob, media_key, reason)

    file_id = MEDIA_KEY.fullmatch(media_key)["file_id"]
    file_type = data["contentType"].split("/")[0]
    doc = db.collection("files").document(file_id)
    record = doc.get().to_dict() or {}
    verified = record.get("status") == "active"
    if verified and record["media_key"] != media_key:
        # The same bytes uploaded at once under another type: keep the first.
        return reject(blob, media_key, "duplicate")
    if verified and finished(record, file_type):
        log("INFO", "already processed, repeat event ignored", file_id=file_id)
        return

    # /tmp is memory on Cloud Run, so the download goes as soon as it's used.
    with tempfile.TemporaryDirectory() as folder:
        path = str(Path(folder) / media_key)
        try:
            blob.download_to_filename(path, raw_download=True)
        except exceptions.NotFound:
            log(
                "INFO",
                "object deleted before it was processed",
                file_id=file_id,
            )
            return
        if not verified:
            if sha256_of(path) != file_id:
                return reject(blob, media_key, "hash_mismatch")
            # Merge, so tags or anything else already on the document stay.
            doc.set(base_record(file_id, data), merge=True)
            log("INFO", "base record written", file_id=file_id)
        if file_type == "image":
            fields = image_fields(file_id, path)
        else:
            fields = video_fields(file_id, path)
    doc.set(fields, merge=True)
    log("INFO", "derived files written", file_id=file_id, **fields["pipeline"])
