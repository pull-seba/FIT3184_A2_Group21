"""Accepted uploads from docs/contracts/storage-layout.md, in one place so
upload_init and process_upload can't drift apart. Owner: member 2."""

MB = 1024 * 1024

# Content type -> (key extension, size limit in bytes).
ACCEPTED = {
    "image/jpeg": ("jpg", 20 * MB),
    "image/png": ("png", 20 * MB),
    "image/webp": ("webp", 20 * MB),
    "video/mp4": ("mp4", 200 * MB),
    "video/quicktime": ("mov", 200 * MB),
}
