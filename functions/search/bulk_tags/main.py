"""bulk_tags: adds or removes tags across many files at once
(POST /tags/bulk).

Owner: member 4. Rubric: 2.3.1. Route: see README.md.
"""

import itertools
import json

import flask
import functions_framework
from google.cloud import firestore

from ecoguard_common.auth import get_user
from ecoguard_common.tag_match import QueryError, known_tags, parse_query
from ecoguard_common.urls import file_id_from_url

db = firestore.Client()

KNOWN_TAGS = known_tags()
MAX_BATCH_WRITES = 500

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


def file_id_or_none(url: str) -> str | None:
    try:
        return file_id_from_url(url)
    except ValueError:
        return None


def tag_changes(tags: list[str], operation: int) -> dict:
    paths = [firestore.Client.field_path("tags", tag) for tag in tags]
    if operation == 1:
        # Counts are at least 1, so Maximum(1) keeps an existing count and
        # sets 1 only where the tag is absent, with no read first.
        changes = dict.fromkeys(paths, firestore.Maximum(1))
        changes["manual_tags"] = firestore.ArrayUnion(tags)
    else:
        changes = dict.fromkeys(paths, firestore.DELETE_FIELD)
        changes["manual_tags"] = firestore.ArrayRemove(tags)
    return changes


def active_file_ids(file_ids: set[str]) -> set[str]:
    if not file_ids:
        return set()
    files = db.collection("files")
    snapshots = db.get_all(
        [files.document(file_id) for file_id in file_ids],
        field_paths=["status"],
    )
    return {
        snapshot.id
        for snapshot in snapshots
        if snapshot.exists and snapshot.to_dict().get("status") == "active"
    }


def write_in_batches(file_ids: list[str], changes: dict):
    files = db.collection("files")
    for chunk in itertools.batched(file_ids, MAX_BATCH_WRITES):
        batch = db.batch()
        for file_id in chunk:
            batch.update(files.document(file_id), changes)
        batch.commit()


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
    urls = body.get("urls")
    if (
        not isinstance(urls, list)
        or not urls
        or not all(isinstance(url, str) for url in urls)
    ):
        return error(400, "bad_urls", "urls must be a non-empty list of URLs")
    operation = body.get("operation")
    # type() rather than isinstance(): JSON true would pass as the int 1.
    if type(operation) is not int or operation not in (0, 1):
        return error(
            400, "bad_operation", "operation must be 1 (add) or 0 (remove)"
        )
    try:
        tags = list(parse_query(body.get("tags"), KNOWN_TAGS))
    except QueryError as exc:
        return error(400, *exc.args)

    file_ids = [file_id_or_none(url) for url in urls]
    found = {file_id for file_id in file_ids if file_id}
    try:
        updated = active_file_ids(found)
        write_in_batches(sorted(updated), tag_changes(tags, operation))
    except Exception as exc:
        log(
            "ERROR",
            f"bulk_tags failed: {type(exc).__name__}: {exc}",
            file_ids=sorted(found),
        )
        return error(500, "internal", "Bulk tag update failed")
    log(
        "INFO",
        "bulk tags",
        operation=operation,
        tags=tags,
        file_ids=sorted(updated),
    )
    return respond(
        {
            "results": [
                {
                    "url": url,
                    "file_id": file_id,
                    "status": "updated" if file_id in updated else "not_found",
                }
                for url, file_id in zip(urls, file_ids)
            ]
        }
    )
