"""upload_init: blocks duplicate uploads by their SHA-256, otherwise gives the browser a signed URL to
PUT the file straight into the media bucket. Writes nothing: process_upload creates the record once the
file has really arrived.

Owner: member 2. Rubric: 2.1.1. Route: POST /uploads/init (see README.md).
"""

import json
import re
import urllib.parse
from datetime import datetime, timedelta, timezone

import functions_framework
import google.auth
from google.auth.transport import requests as google_requests
from google.cloud import firestore, storage

from ecoguard_common.auth import get_user
from ecoguard_common.logs import log
from ecoguard_common.uploads import ACCEPTED, MB

db = firestore.Client()
gcs = storage.Client()
credentials, _ = google.auth.default()

MEDIA_BUCKET = "ecoguard-g21-media"
DERIVED_BUCKET = "ecoguard-g21-derived"
SHA256_HEX = re.compile(r"[0-9a-f]{64}")
UPLOAD_URL_MINUTES = 15
DOWNLOAD_URL_MINUTES = 60

JSON_HEADERS = {"Content-Type": "application/json"}


def respond(body: dict, status: int = 200):
    return json.dumps(body), status, JSON_HEADERS


def error(status: int, code: str, message: str):
    """Error shape from docs/contracts/api-routes.md."""
    return respond({"error": {"code": code, "message": message}}, status)


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def signed_url(
    bucket: str,
    key: str,
    method: str,
    minutes: int,
    content_type=None,
    headers=None,
) -> str:
    """V4 signed URL, signed through IAM with no key file. The URL acts with this function's own
    service account, which needs Token Creator on itself (README.md)."""
    if not credentials.valid:
        # On Cloud Run this also replaces the placeholder email "default" with the real one.
        credentials.refresh(google_requests.Request())
    return (
        gcs.bucket(bucket)
        .blob(key)
        .generate_signed_url(
            version="v4",
            expiration=timedelta(minutes=minutes),
            method=method,
            content_type=content_type,
            # A copy: the library adds "Host" to the dict it's given, and the caller returns its headers
            # to the browser, which must send exactly the contract's list (browsers refuse to set Host).
            headers=dict(headers) if headers else None,
            service_account_email=credentials.service_account_email,
            access_token=credentials.token,
        )
    )


def check_request(body: dict):
    """The first problem with the request as an error response, or None if it's valid."""
    sha256 = body.get("sha256")
    if not isinstance(sha256, str) or not SHA256_HEX.fullmatch(sha256):
        return error(
            400, "bad_hash", "sha256 must be 64 lowercase hex characters"
        )

    content_type = body.get("content_type")
    if not isinstance(content_type, str):
        return error(400, "bad_content_type", "content_type is required")
    if content_type not in ACCEPTED:
        return error(
            415, "unsupported_type", "Accepted types: " + ", ".join(ACCEPTED)
        )

    size = body.get("size_bytes")
    # bool is a subclass of int in Python, so rule it out explicitly.
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        return error(
            400, "bad_size", "size_bytes must be a positive whole number"
        )
    _, size_limit = ACCEPTED[content_type]
    if size > size_limit:
        return error(
            413,
            "too_large",
            f"{content_type} files are limited to {size_limit // MB} MB",
        )

    filename = body.get("filename")
    if (
        not isinstance(filename, str)
        or not filename.strip()
        or len(filename) > 255
    ):
        return error(
            400, "bad_filename", "filename must be 1 to 255 characters"
        )

    if not isinstance(body.get("is_public", True), bool):
        return error(400, "bad_is_public", "is_public must be true or false")
    return None


def duplicate_record(file_id: str):
    """The file's record if it's active, else None."""
    record = db.collection("files").document(file_id).get().to_dict() or {}
    return record if record.get("status") == "active" else None


def file_summary(file_id: str, record: dict) -> dict:
    """FileSummary (docs/contracts/api-routes.md) with fresh signed GET URLs."""
    thumbnail_key = record.get("thumbnail_key")
    return {
        "file_id": file_id,
        "file_type": record.get("file_type"),
        "url": signed_url(
            record["media_bucket"],
            record["media_key"],
            "GET",
            DOWNLOAD_URL_MINUTES,
        ),
        "thumbnail_url": signed_url(
            DERIVED_BUCKET, thumbnail_key, "GET", DOWNLOAD_URL_MINUTES
        )
        if thumbnail_key
        else None,
        "tags": record.get("tags", {}),
        "uploaded_at": iso(record["uploaded_at"]),
    }


def upload_response(file_id: str, body: dict, uploader_sub: str) -> dict:
    content_type = body["content_type"]
    # The extension comes from the type, never from the filename.
    extension, _ = ACCEPTED[content_type]
    media_key = f"{file_id}.{extension}"
    # Signed headers: the browser must send exactly these values, so it can't change any of them.
    # process_upload reads the x-goog-meta-* ones back as the object's metadata.
    headers = {
        "x-goog-if-generation-match": "0",  # never overwrite: a 412 means the object already exists
        "x-goog-meta-uploaded-by": uploader_sub,  # from the verified token, never from the body
        "x-goog-meta-original-filename": urllib.parse.quote(
            body["filename"], safe=""
        ),
        "x-goog-meta-is-public": "true"
        if body.get("is_public", True)
        else "false",
    }
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=UPLOAD_URL_MINUTES
    )
    upload_url = signed_url(
        MEDIA_BUCKET,
        media_key,
        "PUT",
        UPLOAD_URL_MINUTES,
        content_type=content_type,
        headers=headers,
    )
    return {
        "status": "upload",
        "file_id": file_id,
        "upload_url": upload_url,
        "headers": {"Content-Type": content_type, **headers},
        "expires_at": iso(expires_at),
    }


@functions_framework.http
def handler(request):
    user = get_user(request)
    if user is None:
        # Cloud Run only accepts the gateway, so this means a misconfigured deploy.
        return error(
            401,
            "unauthenticated",
            "Request did not come through the API gateway",
        )

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return error(400, "bad_json", "Body must be a JSON object")
    problem = check_request(body)
    if problem:
        return problem

    file_id = body["sha256"]
    try:
        record = duplicate_record(file_id)
        if record:
            log("INFO", "duplicate upload blocked", file_id=file_id)
            return respond(
                {"status": "duplicate", "file": file_summary(file_id, record)}
            )
        response = upload_response(file_id, body, user["sub"])
        log("INFO", "upload URL issued", file_id=file_id)
        return respond(response)
    except Exception as exc:  # anything unexpected is a 500, logged with the file_id (api-routes.md)
        log(
            "ERROR",
            f"upload_init failed: {type(exc).__name__}: {exc}",
            file_id=file_id,
        )
        return error(500, "internal", "Could not start the upload")
