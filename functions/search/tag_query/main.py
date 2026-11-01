"""tag_query: finds files by tags with minimum counts, combined with AND
(POST /search/tags), or by one species (GET /search/species?name=cat).

Owner: member 4. Rubric: 2.2.1. Routes: see README.md.
"""

import json
from collections.abc import Mapping
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import flask
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

db = firestore.Client()
gcs = storage.Client()
credentials, _ = google.auth.default()

DERIVED_BUCKET = "ecoguard-g21-derived"
DOWNLOAD_URL_MINUTES = 60
KNOWN_TAGS = known_tags()
MELBOURNE = ZoneInfo("Australia/Melbourne")

# The browser calls from the app's origin, so it sends a preflight first
# (infra/gateway/README.md). "*" is safe: every real call still needs a token.
CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Authorization, Content-Type",
}
JSON_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
}


def respond(body: dict, status: int = 200):
    return json.dumps(body), status, JSON_HEADERS


def error(status: int, code: str, message: str):
    return respond({"error": {"code": code, "message": message}}, status)


def log(severity: str, message: str, **fields):
    print(
        json.dumps({"severity": severity, "message": message, **fields}),
        flush=True,
    )


def melbourne_midnight(iso_day: str) -> datetime:
    try:
        day = date.fromisoformat(iso_day)
    except ValueError:
        raise QueryError(
            "bad_date", f"Dates must be YYYY-MM-DD, not '{iso_day}'"
        ) from None
    return datetime.combine(day, time(), MELBOURNE)


def date_window(
    args: Mapping[str, str],
) -> tuple[datetime | None, datetime | None]:
    start = melbourne_midnight(args["from"]) if "from" in args else None
    end = (
        melbourne_midnight(args["to"]) + timedelta(days=1)
        if "to" in args
        else None
    )
    return start, end


def search(
    query: dict[str, int], start: datetime | None, end: datetime | None
) -> list[tuple[str, dict]]:
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
        if not matches(record, query):
            continue
        uploaded_at = record["uploaded_at"]
        if (start and uploaded_at < start) or (end and uploaded_at >= end):
            continue
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
def handler(request: flask.Request):
    if request.method == "OPTIONS":
        return "", 204, CORS

    if get_user(request) is None:
        return error(
            401,
            "unauthenticated",
            "Request did not come through the API gateway",
        )

    if request.method == "GET":
        species = request.args.get("name")
        if not species:
            return error(400, "bad_query", "Name the species, as ?name=cat")
        raw_query = [species]
    else:
        raw_query = request.get_json(silent=True)
        if raw_query is None:
            return error(400, "bad_json", "Body must be JSON")

    try:
        query = parse_query(raw_query, KNOWN_TAGS)
        start, end = date_window(request.args)
    except QueryError as exc:
        return error(400, *exc.args)

    try:
        matching = search(query, start, end)
        results = [
            file_summary(file_id, record) for file_id, record in matching
        ]
    except Exception as exc:
        log(
            "ERROR",
            f"tag_query failed: {type(exc).__name__}: {exc}",
            query=query,
        )
        return error(500, "internal", "Search failed")
    log("INFO", "tag query", query=query, results=len(results))
    return respond({"results": results})
