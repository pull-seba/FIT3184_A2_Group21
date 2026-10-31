"""Accepted uploads from docs/contracts/storage-layout.md, in one place so
upload_init, process_upload and tagging can't drift apart. Owner: member 2."""

import re

MB = 1024 * 1024
MEDIA_KEY = re.compile(r"(?P<file_id>[0-9a-f]{64})\.(?P<ext>[a-z0-9]+)")

# Content type -> (key extension, size limit in bytes).
ACCEPTED = {
    "image/jpeg": ("jpg", 20 * MB),
    "image/png": ("png", 20 * MB),
    "image/webp": ("webp", 20 * MB),
    "video/mp4": ("mp4", 200 * MB),
    "video/quicktime": ("mov", 200 * MB),
}


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
