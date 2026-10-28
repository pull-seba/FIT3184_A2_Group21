"""tag_query: finds files by tags with minimum counts, combined with AND
(POST /search/tags), or by one species (GET /search/species?name=cat).

Owner: member 4. Rubric: 2.2.1. Routes: see README.md.
"""

import json
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import functions_framework
import google.auth
from google.auth.transport import requests as google_requests
from google.cloud import firestore, storage

from ecoguard_common.auth import get_user
from ecoguard_common.tag_match import (
    QueryError,
    known_tags,
    matches,
    parse_query,
)

# Created once per instance, reused across requests.
db = firestore.Client()
gcs = storage.Client()
credentials, _ = google.auth.default()

DERIVED_BUCKET = "ecoguard-g21-derived"
DOWNLOAD_URL_MINUTES = 60
KNOWN_TAGS = known_tags()
# from and to are calendar days in Melbourne, so the chatbot's "yesterday"
# is the user's yesterday, not UTC's.
MELBOURNE = ZoneInfo("Australia/Melbourne")

JSON_HEADERS = {"Content-Type": "application/json"}


def respond(body: dict, status: int = 200):
    return json.dumps(body), status, JSON_HEADERS


def error(status: int, code: str, message: str):
    """Error shape from docs/contracts/api-routes.md."""
    return respond({"error": {"code": code, "message": message}}, status)


def log(severity: str, message: str, **fields):
    """One JSON line per event, which Cloud Logging parses. Never log signed
    URLs or tokens."""
    print(
        json.dumps({"severity": severity, "message": message, **fields}),
        flush=True,
    )


def day_start(text: str) -> datetime:
    """Midnight in Melbourne at the start of a YYYY-MM-DD day."""
    try:
        day = date.fromisoformat(text)
    except ValueError:
        raise QueryError(
            "bad_date", f"Dates must be YYYY-MM-DD, not '{text}'"
        ) from None
    return datetime.combine(day, time(), MELBOURNE)


def date_window(args) -> tuple:
    """(start, end) from the optional from and to query parameters. Both days
    are inclusive, so end is the midnight after the to day."""
    start = day_start(args["from"]) if "from" in args else None
    end = day_start(args["to"]) + timedelta(days=1) if "to" in args else None
    return start, end


def search(query: dict[str, int], start, end) -> list[tuple[str, dict]]:
    """(file_id, record) for every file that matches the whole query and was
    uploaded in [start, end), newest first."""
    # Firestore can't combine range filters on several tags without a
    # composite index for every combination, so it narrows by one tag and
    # matches() checks every tag and count. Fine at demo scale; if it reads
    # too much, count() each tag first and narrow by the rarest.
    tag, count = next(iter(query.items()))
    field = firestore.Client.field_path("tags", tag)  # names can have spaces
    snapshots = (
        db.collection("files")
        .where(filter=firestore.FieldFilter(field, ">=", count))
        .stream()
    )
    found = []
    for snapshot in snapshots:
        record = snapshot.to_dict()
        if not matches(record, query):
            continue
        uploaded_at = record["uploaded_at"]
        if (start and uploaded_at < start) or (end and uploaded_at >= end):
            continue
        found.append((snapshot.id, record))
    found.sort(key=lambda item: item[1]["uploaded_at"], reverse=True)
    return found


def signed_url(bucket: str, key: str) -> str:
    """V4 signed GET URL, signed through IAM with no key file. The URL acts
    with this function's own service account, which needs Token Creator on
    itself (README.md)."""
    if not credentials.valid:
        # On Cloud Run this also replaces the placeholder email "default"
        # with the real one.
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
    thumbnail_key = record.get("thumbnail_key")  # absent until it's made
    return {
        "file_id": file_id,
        "file_type": record["file_type"],
        "url": signed_url(record["media_bucket"], record["media_key"]),
        "thumbnail_url": signed_url(DERIVED_BUCKET, thumbnail_key)
        if thumbnail_key
        else None,
        "tags": record.get("tags", {}),
        "uploaded_at": record["uploaded_at"]
        .astimezone(timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


@functions_framework.http
def handler(request):
    if get_user(request) is None:
        # Cloud Run only accepts the gateway, so this means a misconfigured
        # deploy.
        return error(
            401,
            "unauthenticated",
            "Request did not come through the API gateway",
        )

    # The gateway sends both routes here. GET /search/species?name=cat is
    # the one-tag form of POST /search/tags.
    if request.method == "GET":
        name = request.args.get("name")
        if not name:
            return error(400, "bad_query", "Name the species, as ?name=cat")
        body = [name]
    else:
        body = request.get_json(silent=True)
        if body is None:
            return error(400, "bad_json", "Body must be JSON")

    try:
        query = parse_query(body, KNOWN_TAGS)
        start, end = date_window(request.args)
    except QueryError as exc:
        code, message = exc.args
        return error(400, code, message)

    try:
        found = search(query, start, end)
        results = [file_summary(file_id, record) for file_id, record in found]
    except Exception as exc:  # anything unexpected is a 500 (api-routes.md)
        log(
            "ERROR",
            f"tag_query failed: {type(exc).__name__}: {exc}",
            query=query,
        )
        return error(500, "internal", "Search failed")
    log("INFO", "tag query", query=query, results=len(results))
    return respond({"results": results})
