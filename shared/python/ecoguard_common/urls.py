"""Turns any URL of one of our files into its file ID, as
docs/contracts/storage-layout.md ("URL to file ID") describes. The thumbnail
lookup, bulk tagging and delete all use it, so they accept the same URLs.
Owner: member 2."""

import re
from urllib.parse import unquote, urlsplit

from ecoguard_common.uploads import ACCEPTED

MEDIA_BUCKET = "ecoguard-g21-media"
DERIVED_BUCKET = "ecoguard-g21-derived"

FILE_ID = r"(?P<file_id>[0-9a-f]{64})"
EXTENSIONS = "|".join(extension for extension, _ in ACCEPTED.values())

# The keys we hand out URLs for, by bucket: the original and its thumbnail.
KEYS = {
    MEDIA_BUCKET: rf"{FILE_ID}\.({EXTENSIONS})",
    DERIVED_BUCKET: rf"thumbs/{FILE_ID}\.jpg",
}


def file_id_from_url(url: str) -> str:
    """Raises ValueError for any URL that isn't ours. The message never repeats
    the URL: callers may log it, and a signed URL must not reach the logs."""
    parts = urlsplit(url.strip())
    path = unquote(parts.path)
    if parts.scheme == "gs":
        bucket, key = parts.netloc, path.removeprefix("/")
    elif parts.scheme == "https" and parts.netloc == "storage.googleapis.com":
        bucket, _, key = path.removeprefix("/").partition("/")
    else:
        raise ValueError("not a Cloud Storage URL")

    if bucket not in KEYS:
        raise ValueError("not one of our buckets")
    match = re.fullmatch(KEYS[bucket], key)
    if not match:
        raise ValueError("not a key one of our files uses")
    return match["file_id"]
