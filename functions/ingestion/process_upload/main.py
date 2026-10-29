"""process_upload: runs when a file lands in the media bucket. Re-hashes it to
prove its key really is its SHA-256, then writes the file's base record.
Anything that isn't a valid upload is deleted with no record, so it never
counts as a duplicate or shows in queries.

Owner: member 2. Rubric: 2.1.1 (2.1.2 adds thumbnails and frames here).
Trigger: see README.md.

Idempotent: Eventarc can deliver the same event twice, so a file that already
has its verified record is left alone, and deleting an object that's already
gone counts as done. Any other error is left to raise: functions-framework
logs it and returns 500, so Eventarc retries (deployed with --retry).
"""

import hashlib
import re
import urllib.parse

import functions_framework
from google.api_core import exceptions
from google.cloud import firestore, storage

from ecoguard_common.logs import log
from ecoguard_common.uploads import ACCEPTED

db = firestore.Client()
gcs = storage.Client()

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


def sha256_of(blob) -> str:
    """Streams the object in chunks, so a 200 MB video is never in memory at
    once. raw_download hashes exactly the stored bytes, even if a client set a
    Content-Encoding."""
    with blob.open("rb", raw_download=True) as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


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
    doc = db.collection("files").document(file_id)
    record = doc.get().to_dict() or {}
    if record.get("status") == "active":
        if record["media_key"] == media_key:
            log(
                "INFO",
                "already recorded, repeat event ignored",
                file_id=file_id,
            )
            return
        # The same bytes uploaded at once under another type: keep the first.
        return reject(blob, media_key, "duplicate")

    try:
        actual = sha256_of(blob)
    except exceptions.NotFound:
        log("INFO", "object deleted before it was processed", file_id=file_id)
        return
    if actual != file_id:
        return reject(blob, media_key, "hash_mismatch")

    # Merge, so tags or anything else already on the document stay.
    doc.set(base_record(file_id, data), merge=True)
    log("INFO", "base record written", file_id=file_id)
