"""delete_files: deletes files by URL, with everything made from them: the
original, its thumbnail, a video's frames, its lost pet sightings and its
record. Only the person who uploaded a file can delete it.

Owner: member 2. Rubric: 2.3.2. Route: POST /files/delete (see README.md).

Safe to repeat: the record is marked "deleting" first and removed last, and
anything already gone counts as deleted, so calling again finishes a delete
that stopped halfway.
"""

import json
from concurrent.futures import ThreadPoolExecutor

import functions_framework
from google.api_core import exceptions
from google.cloud import firestore, storage

from ecoguard_common.auth import get_user
from ecoguard_common.logs import log
from ecoguard_common.urls import DERIVED_BUCKET, MEDIA_BUCKET, file_id_from_url

db = firestore.Client()  # created once per instance, reused across requests
gcs = storage.Client()

MAX_URLS = 100
# Files are deleted a few at a time: the gateway gives up on a call after 15 s,
# and one by one, a large selection of videos would take longer.
PARALLEL_FILES = 8

# The browser calls from the app's origin, so it sends a preflight first
# (infra/gateway/README.md). "*" is safe: every real call still needs a token.
CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
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


def file_id_or_none(url: str):
    """The file a URL names, or None if it isn't one of ours."""
    try:
        return file_id_from_url(url)
    except ValueError:
        return None


def delete_objects(file_id: str) -> int:
    """Deletes the original, the thumbnail and every frame. Found by listing
    each key's prefix rather than read from the record, so objects saved
    before an interrupted process_upload wrote their keys go too."""
    deleted = 0
    for bucket, prefix in [
        (MEDIA_BUCKET, f"{file_id}."),
        (DERIVED_BUCKET, f"thumbs/{file_id}."),
        (DERIVED_BUCKET, f"frames/{file_id}/"),
    ]:
        for blob in gcs.list_blobs(bucket, prefix=prefix):
            try:
                blob.delete()
                deleted += 1
            except exceptions.NotFound:
                pass  # another call deleted it after this one listed it
    return deleted


def delete_sightings(file_id: str) -> int:
    """Deletes the file's lost pet sightings, so it stops matching searches."""
    query = db.collection("sightings").where(
        filter=firestore.FieldFilter("file_id", "==", file_id)
    )
    deleted = 0
    for sighting in query.stream():
        sighting.reference.delete()
        deleted += 1
    return deleted


def delete_file(file_id: str, caller: str) -> dict:
    """Deletes one file if the caller uploaded it. Returns its result's
    status, plus a detail for an error."""
    try:
        doc = db.collection("files").document(file_id)
        record = doc.get().to_dict()
        if record is None:
            return {"status": "not_found"}
        if record.get("uploaded_by") != caller:
            log("WARNING", "delete refused: not the uploader", file_id=file_id)
            return {
                "status": "error",
                "detail": "You can only delete files you uploaded",
            }
        # Queries and upload_init only match "active", so the file leaves
        # every result at once, even if a step below fails.
        doc.set({"status": "deleting"}, merge=True)
        objects = delete_objects(file_id)
        sightings = delete_sightings(file_id)
        doc.delete()  # last, so a retry can still find the file
        log(
            "INFO",
            "file deleted",
            file_id=file_id,
            objects=objects,
            sightings=sightings,
        )
        return {"status": "deleted"}
    except Exception as exc:  # one file failing doesn't stop the others
        log(
            "ERROR",
            f"delete failed: {type(exc).__name__}: {exc}",
            file_id=file_id,
        )
        return {"status": "error", "detail": "Could not delete it. Try again."}


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

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return error(400, "bad_json", "Body must be a JSON object")
    urls = body.get("urls")
    if (
        not isinstance(urls, list)
        or not 1 <= len(urls) <= MAX_URLS
        or not all(isinstance(url, str) for url in urls)
    ):
        return error(
            400, "bad_urls", f"urls must be a list of 1 to {MAX_URLS} URLs"
        )

    file_ids = [file_id_or_none(url) for url in urls]
    # Each file once, even when the original and its thumbnail are both sent.
    unique_ids = list(dict.fromkeys(filter(None, file_ids)))
    caller = user["sub"]
    with ThreadPoolExecutor(PARALLEL_FILES) as pool:
        outcomes = pool.map(
            lambda file_id: delete_file(file_id, caller), unique_ids
        )
        outcome_by_id = dict(zip(unique_ids, outcomes))

    # One result per URL, in the request's order (docs/contracts/api-routes.md).
    # A URL that isn't one of our files has no ID, so it is not_found.
    results = [
        {
            "url": url,
            "file_id": file_id,
            **outcome_by_id.get(file_id, {"status": "not_found"}),
        }
        for url, file_id in zip(urls, file_ids)
    ]
    return respond({"results": results})
