"""process_upload: runs when a file lands in the media bucket. Re-hashes it to prove its key really is
its SHA-256, then writes the file's base record. Anything that isn't a valid upload is deleted with no
record, so it never counts as a duplicate or shows in queries.

Owner: member 2. Rubric: 2.1.1 (2.1.2 adds thumbnails and frames here). Trigger: see README.md.

Idempotent: Eventarc can deliver the same event twice, so a file that already has its verified record
is left alone, and deleting an object that's already gone counts as done.
"""
import hashlib
import json
import re
import urllib.parse

import functions_framework
from google.api_core import exceptions
from google.cloud import firestore, storage

# Created once per instance, reused across events.
db = firestore.Client()
gcs = storage.Client()

MB = 1024 * 1024
# Accepted uploads (docs/contracts/storage-layout.md), the same table as upload_init's:
# content type -> (key extension, size limit).
ACCEPTED = {
    "image/jpeg": ("jpg", 20 * MB),
    "image/png": ("png", 20 * MB),
    "image/webp": ("webp", 20 * MB),
    "video/mp4": ("mp4", 200 * MB),
    "video/quicktime": ("mov", 200 * MB),
}
MEDIA_KEY = re.compile(r"([0-9a-f]{64})\.([a-z0-9]+)")  # <file_id>.<ext>


def log(severity: str, message: str, **fields):
    """One JSON line per event, which Cloud Logging parses. Never log signed URLs or tokens."""
    print(json.dumps({"severity": severity, "message": message, **fields}), flush=True)


def problem_with(name: str, content_type, size: int, metadata: dict):
    """Why the object isn't a valid upload, from the event alone, or None. Runs before any download."""
    key = MEDIA_KEY.fullmatch(name)
    if not key:
        return "bad_key"
    if content_type not in ACCEPTED or ACCEPTED[content_type][0] != key.group(2):
        return "bad_type"
    # upload_init only saw the size the browser claimed; this is the size actually stored.
    if size > ACCEPTED[content_type][1]:
        return "too_large"
    # upload_init signs this header into every upload URL, so without it the file didn't come through it.
    if not metadata.get("uploaded-by"):
        return "no_uploader"
    return None


def sha256_of(blob) -> str:
    """Streams the object in chunks, so a 200 MB video is never in memory at once. raw_download hashes
    exactly the stored bytes, even if a client set a Content-Encoding."""
    with blob.open("rb", raw_download=True) as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def reject(blob, key: str, reason: str):
    """Deletes an object that isn't a valid upload. The blob is pinned to the event's generation, so this
    can only ever delete the exact object that fired the event."""
    try:
        blob.delete()
    except exceptions.NotFound:
        pass  # a repeat event: already deleted
    log("WARNING", "upload rejected and deleted", key=key, reason=reason)


def base_record(file_id: str, data: dict) -> dict:
    """The fields process_upload owns (docs/contracts/firestore-schema.md), from the event's object."""
    metadata = data.get("metadata") or {}
    content_type = data["contentType"]
    return {
        "file_id": file_id,
        "file_type": content_type.split("/")[0],  # "image" or "video": every accepted type starts with one
        "content_type": content_type,
        # upload_init URL-encodes it, since metadata headers must be plain ASCII.
        "original_filename": urllib.parse.unquote(metadata.get("original-filename", data["name"])),
        "size_bytes": int(data["size"]),
        "media_bucket": data["bucket"],
        "media_key": data["name"],
        "media_uri": f"gs://{data['bucket']}/{data['name']}",
        "uploaded_by": metadata["uploaded-by"],
        "uploaded_at": firestore.SERVER_TIMESTAMP,
        # The schema's default is public; anything other than "true" or a missing value is private.
        "is_public": metadata.get("is-public", "true") == "true",
        "status": "active",
    }


@functions_framework.cloud_event
def handler(event):
    data = event.data  # the Cloud Storage object; numbers arrive as strings
    name = data["name"]
    blob = gcs.bucket(data["bucket"]).blob(name, generation=int(data["generation"]))
    try:
        reason = problem_with(name, data.get("contentType"), int(data["size"]), data.get("metadata") or {})
        if reason:
            return reject(blob, name, reason)

        file_id = MEDIA_KEY.fullmatch(name).group(1)
        doc = db.collection("files").document(file_id)
        record = doc.get().to_dict() or {}  # tagging may have created the document already
        if record.get("media_key") and record.get("status") == "active":
            if record["media_key"] == name:
                log("INFO", "already recorded, repeat event ignored", file_id=file_id)
                return
            # The same bytes uploaded at the same moment under another type: the record keeps the first.
            return reject(blob, name, "duplicate")

        try:
            actual = sha256_of(blob)
        except exceptions.NotFound:
            log("INFO", "object deleted before it was processed", file_id=file_id)
            return
        if actual != file_id:
            return reject(blob, name, "hash_mismatch")

        # Merge, so tags or anything else already on the document stay.
        doc.set(base_record(file_id, data), merge=True)
        log("INFO", "base record written", file_id=file_id)
    except Exception as exc:
        log("ERROR", f"process_upload failed: {type(exc).__name__}: {exc}", key=name)
        raise  # Eventarc retries the event (deployed with --retry); every step above is safe to repeat
