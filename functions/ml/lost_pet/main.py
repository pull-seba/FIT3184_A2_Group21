"""lost_pet: public sightings of cats and dogs that may be a lost pet
(POST /search/lost-pet).

Owner: member 3. Rubric 2.2.4. Route: docs/contracts/api-routes.md.

With a photo, the photo is embedded in memory by Vertex AI, with the model in
config/model that embedded every sighting, and Firestore's vector search
finds the nearest public sightings. Without a photo, sightings are filtered
by species and colour, newest first. Either way a breed, if sent, is checked
afterwards in Python. The photo is never written anywhere:
this function makes no Cloud Storage or Firestore write, and logs only the
other request fields and the result count.
"""

import base64
import binascii
import io
import json
from datetime import datetime, timedelta, timezone

import functions_framework
import google.auth
from google.auth.transport import requests as google_requests
from google.cloud import firestore, storage
from google.cloud.firestore_v1.base_vector_query import DistanceMeasure
from google.cloud.firestore_v1.vector import Vector
from PIL import Image, ImageOps

from ecoguard_common.auth import get_user
from ecoguard_common.logs import log
from ecoguard_common.tag_match import load_tags
from ecoguard_common.uploads import ACCEPTED
from ecoguard_ml import detect, embed

db = firestore.Client()  # created once per instance, reused across requests
gcs = storage.Client()
credentials, _ = google.auth.default()

TAGS = load_tags()
SPECIES = TAGS["lost_pet_species"]
COLOURS = TAGS["lost_pet_colours"]
DERIVED_BUCKET = "ecoguard-g21-derived"
DOWNLOAD_URL_MINUTES = 60
_, MAX_PHOTO_BYTES = ACCEPTED["image/jpeg"]  # 20 MB, the upload limit
PHOTO_SIDE = 1024  # the size the contract asks browsers to send
MAX_SIGHTINGS = 50
DEFAULT_SINCE_DAYS = 30
MAX_SINCE_DAYS = 365

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


class BadRequest(Exception):
    """Input the API rejects before any Firestore or Vertex AI call."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def validate(body) -> dict:
    if not isinstance(body, dict):
        raise BadRequest(400, "bad_json", "Body must be a JSON object")
    image_base64 = body.get("image_base64")
    species = body.get("species")
    colour = body.get("colour")
    if colour == "":
        colour = None  # an empty colour box means any colour
    since_days = body.get("since_days")
    if since_days is None:
        since_days = DEFAULT_SINCE_DAYS
    breed = body.get("breed")

    if image_base64 is None and species is None:
        raise BadRequest(
            400, "missing_query", "Send image_base64, species or both"
        )
    if species is not None and species not in SPECIES:
        raise BadRequest(
            400, "bad_species", "species must be one of: " + ", ".join(SPECIES)
        )
    if colour is not None and colour not in COLOURS:
        raise BadRequest(
            400, "bad_colour", "colour must be one of: " + ", ".join(COLOURS)
        )
    # bool is a subclass of int in Python, so JSON true would pass as 1.
    if (
        isinstance(since_days, bool)
        or not isinstance(since_days, int)
        or not 1 <= since_days <= MAX_SINCE_DAYS
    ):
        raise BadRequest(
            400,
            "bad_since_days",
            f"since_days must be a whole number from 1 to {MAX_SINCE_DAYS}",
        )
    if breed is not None and not isinstance(breed, str):
        raise BadRequest(400, "bad_breed", "breed must be a string or null")
    if image_base64 is not None and (
        not isinstance(image_base64, str) or not image_base64
    ):
        raise BadRequest(
            400, "bad_file", "image_base64 must be a base64 string"
        )
    return {
        "image_base64": image_base64,
        "species": species,
        "colour": colour,
        "breed": breed.strip().lower() if breed else None,
        "since_days": since_days,
    }


def shrink_photo(image_base64: str) -> bytes:
    """The photo as a JPEG of at most 1024 px, made in memory. The contract
    has no content_type for this route, so Pillow works out the format."""
    try:
        # validate=True rejects stray characters instead of skipping them.
        data = base64.b64decode(image_base64, validate=True)
    except binascii.Error:
        raise BadRequest(400, "bad_base64", "image_base64 is not valid base64")
    if len(data) > MAX_PHOTO_BYTES:
        raise BadRequest(
            413,
            "too_large",
            f"Photos are limited to {MAX_PHOTO_BYTES // (1024 * 1024)} MB",
        )
    try:
        image = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
        image.thumbnail((PHOTO_SIDE, PHOTO_SIDE))
        out = io.BytesIO()
        image.convert("RGB").save(out, "JPEG", quality=90)
    except (OSError, Image.DecompressionBombError):
        raise BadRequest(400, "bad_image", "The photo could not be read")
    return out.getvalue()


def breed_matches(sighting: dict, breed: str | None) -> bool:
    """True with no breed asked for, or when the asked words are part of the
    sighting's breed: "labrador" finds "Labrador Retriever". Breeds are
    Rekognition's own label names, so there's no fixed list to check against.
    Checked here because a Firestore filter would need new indexes."""
    return not breed or breed in (sighting.get("breed") or "").lower()


def photo_search(photo: bytes, species, colour, breed, cutoff) -> list[dict]:
    """The public sightings nearest to the photo, best first."""
    config = detect.model_config(db)
    query_vector = embed.embed_image(photo, config)
    # One query either way: there is a vector index with species and
    # is_public as pre-filters, and one with is_public alone.
    query = db.collection("sightings")
    if species:
        query = query.where(
            filter=firestore.FieldFilter("species", "==", species)
        )
    query = query.where(filter=firestore.FieldFilter("is_public", "==", True))
    nearest = query.find_nearest(
        vector_field="embedding",
        query_vector=Vector(query_vector),
        distance_measure=DistanceMeasure.COSINE,
        limit=MAX_SIGHTINGS,
        distance_result_field="distance",
    )
    found = []
    for snapshot in nearest.stream():
        sighting = snapshot.to_dict()
        # The vector indexes have no date, colour or breed field, so these
        # filters run here, on the 50 nearest.
        if sighting["uploaded_at"] < cutoff:
            continue
        if colour and sighting.get("colour") != colour:
            continue
        if not breed_matches(sighting, breed):
            continue
        found.append(
            {
                "sighting_id": snapshot.id,
                "file_id": sighting["file_id"],
                # Cosine distance is 1 - cosine similarity: 1 is identical.
                "score": round(1 - sighting["distance"], 2),
            }
        )
    # find_nearest already returns nearest first; sorting again means the
    # order doesn't rest on that.
    found.sort(key=lambda match: match["score"], reverse=True)
    return found


def description_search(species, colour, breed, cutoff) -> list[dict]:
    """Public sightings of the species (and colour) in the window, newest
    first. Matches the two sightings indexes that end in uploaded_at. Breed
    is checked afterwards, on the 50 the query returns."""
    query = (
        db.collection("sightings")
        .where(filter=firestore.FieldFilter("species", "==", species))
        .where(filter=firestore.FieldFilter("is_public", "==", True))
    )
    if colour:
        query = query.where(
            filter=firestore.FieldFilter("colour", "==", colour)
        )
    query = (
        query.where(filter=firestore.FieldFilter("uploaded_at", ">=", cutoff))
        .order_by("uploaded_at", direction=firestore.Query.DESCENDING)
        .limit(MAX_SIGHTINGS)
    )
    return [
        {
            "sighting_id": snapshot.id,
            "file_id": snapshot.to_dict()["file_id"],
            "score": None,  # no photo to compare with
        }
        for snapshot in query.stream()
        if breed_matches(snapshot.to_dict(), breed)
    ]


def best_per_file(found: list[dict]) -> list[dict]:
    """A file can hold several pets. found is best first, so the first
    sighting of each file is its best one."""
    best = {}
    for sighting in found:
        best.setdefault(sighting["file_id"], sighting)
    return list(best.values())  # dicts keep insertion order


# signed_get_url() and file_summary() are copied from member 4's
# search/tag_query, so FileSummary is built the same way on every route.
# Move them into ecoguard_common after the demo.


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


def results_for(found: list[dict]) -> list[dict]:
    """FileSummary + score and sighting_id, in found's order, for files
    that are still active."""
    best = best_per_file(found)
    if not best:
        return []
    refs = [db.collection("files").document(s["file_id"]) for s in best]
    records = {
        snapshot.id: snapshot.to_dict()
        for snapshot in db.get_all(refs)  # one round trip for every file
        if snapshot.exists
    }
    results = []
    for sighting in best:
        record = records.get(sighting["file_id"])
        # A file being deleted, or one process_upload hasn't recorded yet,
        # isn't shown: the same "active" rule as /search/tags.
        if record is None or record.get("status") != "active":
            continue
        results.append(
            file_summary(sighting["file_id"], record)
            | {
                "score": sighting["score"],
                "sighting_id": sighting["sighting_id"],
            }
        )
    return results


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

    try:
        query = validate(request.get_json(silent=True))
        photo = None
        if query["image_base64"] is not None:
            photo = shrink_photo(query["image_base64"])
    except BadRequest as bad:
        return error(bad.status, bad.code, bad.message)

    cutoff = datetime.now(timezone.utc) - timedelta(days=query["since_days"])
    try:
        if photo is not None:
            found = photo_search(
                photo,
                query["species"],
                query["colour"],
                query["breed"],
                cutoff,
            )
        else:
            found = description_search(
                query["species"], query["colour"], query["breed"], cutoff
            )
        results = results_for(found)
    except Exception as exc:
        log("ERROR", f"lost_pet failed: {type(exc).__name__}: {exc}")
        return error(500, "internal", "Search failed")

    # Never the photo, its base64 or its embedding.
    log(
        "INFO",
        "lost pet search",
        species=query["species"],
        colour=query["colour"],
        since_days=query["since_days"],
        photo=photo is not None,
        results=len(results),
    )
    return respond({"results": results})
