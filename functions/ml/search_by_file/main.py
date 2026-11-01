"""search_by_file: finds stored files showing the same species as a photo
the user sends (POST /search/by-file).

Owner: member 3. Rubric 2.2.3. Route: docs/contracts/api-routes.md.

The photo is tagged in memory by the same detector and config/model as
uploads (ecoguard_ml.detect), then matched against files/ by species. It is
never written anywhere: this function makes no Cloud Storage or Firestore
write, and logs only the detected tags and the result count.
"""

import base64
import binascii
import json
from datetime import timedelta, timezone

import functions_framework
import google.auth
from google.auth.transport import requests as google_requests
from google.cloud import firestore, storage

from ecoguard_common.auth import get_user
from ecoguard_common.logs import log
from ecoguard_common.tag_match import matches
from ecoguard_common.uploads import ACCEPTED
from ecoguard_ml import BadImage, detect

db = firestore.Client()  # created once per instance, reused across requests
gcs = storage.Client()
credentials, _ = google.auth.default()

DERIVED_BUCKET = "ecoguard-g21-derived"
DOWNLOAD_URL_MINUTES = 60
# Videos are accepted uploads but not searchable by file.
IMAGE_TYPES = [kind for kind in ACCEPTED if kind.startswith("image/")]

# From infra/gateway/README.md. The browser's preflight reaches us with no
# token, so it is answered before the gateway user check.
CORS = {
    "Access-Control-Allow-Origin": "*",  # safe: every real call needs a token
    "Access-Control-Allow-Methods": "GET, POST, PUT, OPTIONS",
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


def species_query(detected: dict[str, int]) -> dict[str, int]:
    """The spec asks for every file that contains "that set of tags", so each
    species in the photo becomes a minimum of 1: a photo of two foxes finds a
    file with one fox. detected_tags in the response keeps the real counts."""
    return dict.fromkeys(detected, 1)


# search(), signed_get_url() and file_summary() are copied from member 4's
# search/tag_query (search() without its date window), so FileSummary is
# built the same way on every route. Move them into ecoguard_common after
# the demo.


def search(query: dict[str, int]) -> list[tuple[str, dict]]:
    # Range filters on several tags need a composite index for every
    # combination, so Firestore narrows by one tag and matches() checks all.
    tag, count = next(iter(query.items()))
    field = firestore.Client.field_path("tags", tag)  # names can have spaces
    candidates = (
        db.collection("files")
        .where(filter=firestore.FieldFilter(field, ">=", count))
        .stream()
    )
    matching = []
    for candidate in candidates:
        record = candidate.to_dict()
        if matches(record, query):
            matching.append((candidate.id, record))
    matching.sort(key=lambda match: match[1]["uploaded_at"], reverse=True)
    return matching


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


def file_summary(file_id: str, record: dict) -> dict:
    thumbnail_key = record.get("thumbnail_key")
    return {
        "file_id": file_id,
        "file_type": record["file_type"],
        "url": signed_get_url(record["media_bucket"], record["media_key"]),
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

    if get_user(request) is None:
        # Cloud Run only accepts the gateway, so this means a misconfigured deploy.
        return error(
            401,
            "unauthenticated",
            "Request did not come through the API gateway",
        )

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return error(400, "bad_json", "Body must be a JSON object")
    file_base64 = body.get("file_base64")
    content_type = body.get("content_type")
    if not isinstance(file_base64, str) or not file_base64:
        return error(400, "bad_file", "file_base64 is required")
    if not isinstance(content_type, str):
        return error(400, "bad_content_type", "content_type is required")
    if content_type not in IMAGE_TYPES:
        return error(
            415, "unsupported_type", "Accepted types: " + ", ".join(IMAGE_TYPES)
        )
    try:
        # validate=True rejects stray characters instead of skipping them.
        data = base64.b64decode(file_base64, validate=True)
    except binascii.Error:
        return error(400, "bad_base64", "file_base64 is not valid base64")
    _, size_limit = ACCEPTED[content_type]
    if len(data) > size_limit:
        return error(
            413,
            "too_large",
            f"Images are limited to {size_limit // (1024 * 1024)} MB",
        )

    try:
        detected, _ = detect.analyse(data, detect.model_config(db))
        query = species_query(detected)
        # No species, nothing to match: Firestore isn't queried.
        matching = search(query) if query else []
        results = [
            file_summary(file_id, record) for file_id, record in matching
        ]
    except BadImage as exc:
        log("INFO", "query photo can't be read", error=str(exc))
        return error(400, "bad_image", "The file could not be read as an image")
    except Exception as exc:
        log("ERROR", f"search_by_file failed: {type(exc).__name__}: {exc}")
        return error(500, "internal", "Search failed")

    log("INFO", "search by file", detected_tags=detected, results=len(results))
    return respond({"detected_tags": detected, "results": results})
