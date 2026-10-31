"""thumbnail_lookup: finds the full-size file behind a thumbnail URL
(POST /search/thumbnail).

Owner: member 4. Rubric: 2.2.2. Route: see README.md.
"""

import json
from datetime import timedelta

import flask
import functions_framework
import google.auth
from google.auth.transport import requests as google_requests
from google.cloud import firestore, storage

from ecoguard_common.auth import get_user
from ecoguard_common.urls import file_id_from_url

db = firestore.Client()
gcs = storage.Client()
credentials, _ = google.auth.default()

DOWNLOAD_URL_MINUTES = 60

JSON_HEADERS = {"Content-Type": "application/json"}


def respond(body: dict, status: int = 200):
    return json.dumps(body), status, JSON_HEADERS


def error(status: int, code: str, message: str):
    return respond({"error": {"code": code, "message": message}}, status)


def log(severity: str, message: str, **fields):
    print(
        json.dumps({"severity": severity, "message": message, **fields}),
        flush=True,
    )


def signed_get_url(bucket: str, key: str) -> str:
    if not credentials.valid:
        # Refreshing also swaps Cloud Run's placeholder email "default" for
        # the function's real service account.
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


@functions_framework.http
def handler(request: flask.Request):
    if get_user(request) is None:
        return error(
            401,
            "unauthenticated",
            "Request did not come through the API gateway",
        )

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return error(400, "bad_json", "Body must be a JSON object")
    thumbnail_url = body.get("thumbnail_url")
    if not isinstance(thumbnail_url, str):
        return error(400, "bad_url", 'Send {"thumbnail_url": "<URL>"}')

    try:
        file_id = file_id_from_url(thumbnail_url)
    except ValueError:
        return error(404, "not_found", "No file has that thumbnail URL")

    try:
        record = db.collection("files").document(file_id).get().to_dict()
        if not record or record.get("status") != "active":
            return error(404, "not_found", "No file has that thumbnail URL")
        # Thumbnails are always .jpg but originals can be PNG, WebP or video,
        # so the key comes from the record, never from the thumbnail's name.
        url = signed_get_url(record["media_bucket"], record["media_key"])
    except Exception as exc:
        log(
            "ERROR",
            f"thumbnail_lookup failed: {type(exc).__name__}: {exc}",
            file_id=file_id,
        )
        return error(500, "internal", "Thumbnail lookup failed")
    log("INFO", "thumbnail lookup", file_id=file_id)
    return respond(
        {"file_id": file_id, "file_type": record["file_type"], "url": url}
    )
