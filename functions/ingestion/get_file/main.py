"""get_file: one file's FileSummary plus how far its processing has got, so
the upload page can show each upload going from thumbnail to tags.

Owner: member 2. Rubric: 3.1. Route: GET /files/{file_id} (see README.md).
"""

import json
import re
from datetime import timedelta, timezone

import functions_framework
import google.auth
from google.auth.transport import requests as google_requests
from google.cloud import firestore, storage

from ecoguard_common.auth import get_user
from ecoguard_common.logs import log
from ecoguard_common.urls import DERIVED_BUCKET

db = firestore.Client()  # created once per instance, reused across requests
gcs = storage.Client()
credentials, _ = google.auth.default()

SHA256_HEX = re.compile(r"[0-9a-f]{64}")
DOWNLOAD_URL_MINUTES = 60

# The browser calls from the app's origin, so it sends a preflight first
# (infra/gateway/README.md). "*" is safe: every real call still needs a token.
CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "Authorization, Content-Type",
}
JSON_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
}


def respond(body: dict, status: int = 200):
    return json.dumps(body), status, JSON_HEADERS


def error(status: int, code: str, message: str):
    """Error shape from docs/contracts/api-routes.md."""
    return respond({"error": {"code": code, "message": message}}, status)


def signed_get_url(bucket: str, key: str) -> str:
    """V4 signed GET URL, signed through IAM with no key file. The URL reads
    with this function's own service account, which needs Token Creator on
    itself (README.md)."""
    if not credentials.valid:
        # On Cloud Run this also replaces the placeholder email "default" with the real one.
        credentials.refresh(google_requests.Request())
    return (
        gcs.bucket(bucket)
        .blob(key)
        .generate_signed_url(
            version="v4",
            expiration=timedelta(minutes=DOWNLOAD_URL_MINUTES),
            method="GET",
            service_account_email=credentials.service_account_email,
            access_token=credentials.token,
        )
    )


def file_summary(file_id: str, record: dict) -> dict:
    """FileSummary (docs/contracts/api-routes.md) with fresh signed URLs."""
    thumbnail_key = record.get("thumbnail_key")
    return {
        "file_id": file_id,
        "file_type": record["file_type"],
        "url": signed_get_url(record["media_bucket"], record["media_key"]),
        # None until process_upload has made it, or if it couldn't.
        "thumbnail_url": signed_get_url(DERIVED_BUCKET, thumbnail_key)
        if thumbnail_key
        else None,
        "tags": record.get("tags", {}),
        "uploaded_at": record["uploaded_at"]
        .astimezone(timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


@functions_framework.http
def handler(request):
    if request.method == "OPTIONS":
        return "", 204, CORS

    user = get_user(request)
    if user is None:
        # Cloud Run only accepts the gateway, so this means a misconfigured deploy.
        return error(
            401,
            "unauthenticated",
            "Request did not come through the API gateway",
        )

    # The gateway passes the path's {file_id} as a query parameter.
    file_id = request.args.get("file_id", "")
    if not SHA256_HEX.fullmatch(file_id):
        return error(
            400, "bad_file_id", "file_id must be 64 lowercase hex characters"
        )

    try:
        record = db.collection("files").document(file_id).get().to_dict() or {}
        # Only an active record is a file: not one being deleted, nor one
        # tagging wrote before process_upload verified the upload.
        if record.get("status") != "active":
            return error(404, "not_found", "No such file")
        summary = file_summary(file_id, record)
        # Each step adds its own key when it finishes ("done" or "failed").
        return respond({**summary, "pipeline": record.get("pipeline", {})})
    except Exception as exc:  # anything unexpected is a 500, logged with the file_id (api-routes.md)
        log(
            "ERROR",
            f"get_file failed: {type(exc).__name__}: {exc}",
            file_id=file_id,
        )
        return error(500, "internal", "Could not load the file")
