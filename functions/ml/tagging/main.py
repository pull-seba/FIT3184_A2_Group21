"""tagging: species tags with counts for every uploaded image and video.

Owner: member 3. Rubric 2.1.3, and 2.2.4 for lost pet sightings.
Triggers: see README.md.
"""

import base64
import hashlib
import json
import re
from datetime import datetime

import functions_framework
from google.api_core import exceptions
from google.cloud import firestore, storage
from google.cloud.firestore_v1.vector import Vector

from ecoguard_common.logs import log
from ecoguard_common.uploads import MEDIA_KEY, rejection_reason
from ecoguard_ml import BadImage, detect, sightings

db = firestore.Client()
gcs = storage.Client()

FILE_ID = re.compile(r"[0-9a-f]{64}")
# The only fields tagging writes (firestore-schema.md). set() with this list
# replaces exactly these, so an automatic tag the model no longer finds goes
# away, and works whether or not process_upload has written the record yet.
TAGGING_FIELDS = ["tags", "model_version", "tagged_at", "pipeline.tagging"]


def max_per_tag(per_image: list[dict[str, int]]) -> dict[str, int]:
    """Each tag's highest count in any one image or frame. Never the sum:
    the same fox in six frames is one fox."""
    tags = {}
    for counts in per_image:
        for tag, count in counts.items():
            tags[tag] = max(tags.get(tag, 0), count)
    return tags


def keep_manual_tags(detected: dict[str, int], record: dict) -> dict[str, int]:
    """The detected tags, then every tag in manual_tags put back with its
    existing count, so re-tagging never undoes a person's edit."""
    tags = dict(detected)
    current = record.get("tags") or {}
    for name in record.get("manual_tags") or []:
        if name in current:
            tags[name] = current[name]
    return tags


@firestore.transactional
def _write_tags(transaction, doc, detected: dict[str, int], version: str):
    # Read and write in one transaction: if bulk_tags adds a manual tag
    # between them, Firestore retries this and the tag is kept.
    record = doc.get(transaction=transaction).to_dict() or {}
    transaction.set(
        doc,
        {
            "tags": keep_manual_tags(detected, record),
            "model_version": version,
            "tagged_at": firestore.SERVER_TIMESTAMP,
            "pipeline": {"tagging": "done"},
        },
        merge=TAGGING_FIELDS,
    )


def write_tags(doc, detected: dict[str, int], version: str):
    _write_tags(db.transaction(), doc, detected, version)


def write_sightings(file_id, pets, config, uploaded_at, is_public):
    """sightings/{file_id}_{n} for each pet, then deletes any numbered n or
    higher from an earlier run that found more pets. A repeat event gives
    the same IDs, so it overwrites rather than duplicates. Tagging owns
    every field, and merge=True follows the schema's rule for set()."""
    collection = db.collection("sightings")
    for n, pet in enumerate(pets):
        collection.document(f"{file_id}_{n}").set(
            {
                "file_id": file_id,
                "species": pet["species"],
                "colour": pet["colour"],
                "breed": pet["breed"],
                "embedding": Vector(pet["embedding"]),
                "embedding_model": config["embedding_model"],
                "bbox": pet["bbox"],
                "frame_index": pet["frame_index"],
                "uploaded_at": uploaded_at,
                "is_public": is_public,
                "created_at": firestore.SERVER_TIMESTAMP,
            },
            merge=True,
        )
    query = collection.where(
        filter=firestore.FieldFilter("file_id", "==", file_id)
    )
    for old in query.stream():
        if int(old.id.rsplit("_", 1)[1]) >= len(pets):
            old.reference.delete()


def tag_file(
    file_id: str,
    images: list[bytes],
    *,
    video: bool = False,
    uploaded_at=None,
    is_public: bool | None = None,
):
    """Tags and lost pet sightings for one file. An image passes its
    uploaded_at and is_public from the storage event; a video reads them
    from its files record."""
    config = detect.model_config(db)
    doc = db.collection("files").document(file_id)
    record = doc.get().to_dict() or {}
    if (
        record.get("model_version") == config["version"]
        and (record.get("pipeline") or {}).get("tagging") == "done"
    ):
        log("INFO", "already tagged, repeat event ignored", file_id=file_id)
        return

    if video:
        # frames-ready is published after process_upload wrote the record.
        uploaded_at = record.get("uploaded_at", firestore.SERVER_TIMESTAMP)
        is_public = record.get("is_public", True)

    # Any other error (throttling, network, federation, Vertex AI) is
    # raised, so Eventarc or Pub/Sub delivers the event again.
    try:
        results = [detect.analyse(image, config) for image in images]
        pets = []  # numbered on across frames: _0, _1, ... for the whole file
        for index, (image, (_, labels)) in enumerate(zip(images, results)):
            for pet in sightings.pets(image, labels, config):
                pets.append(pet | {"frame_index": index if video else None})
    except BadImage as error:
        doc.set({"pipeline": {"tagging": "failed"}}, merge=True)
        log("ERROR", "image can't be tagged", file_id=file_id, error=str(error))
        return

    # Sightings first: the check above skips a file whose tagging is "done",
    # so tags written before a failed sightings write would never be retried.
    write_sightings(file_id, pets, config, uploaded_at, is_public)
    tags = max_per_tag([counts for counts, _ in results])
    write_tags(doc, tags, config["version"])
    log(
        "INFO",
        "tagged",
        file_id=file_id,
        tags=tags,
        images=len(results),
        sightings=len(pets),
        model_version=config["version"],
        labels=[detect.animal_labels(labels) for _, labels in results],
    )


@functions_framework.cloud_event
def on_upload(event):
    data = event.data
    # process_upload deletes anything that fails this, so it isn't tagged.
    if rejection_reason(data):
        log("INFO", "not a valid upload, ignored", key=data["name"])
        return
    file_id = MEDIA_KEY.fullmatch(data["name"])["file_id"]
    if data["contentType"].startswith("video/"):
        log("INFO", "video: tagged from frames-ready", file_id=file_id)
        return

    blob = gcs.bucket(data["bucket"]).blob(data["name"])
    try:
        content = blob.download_as_bytes()
    except exceptions.NotFound:
        log("INFO", "object deleted before tagging", file_id=file_id)
        return
    # process_upload deletes bytes that don't hash to their key; tagging
    # them would leave tags behind on a file that never becomes active.
    if hashlib.sha256(content).hexdigest() != file_id:
        log("WARNING", "hash mismatch, not tagged", file_id=file_id)
        return
    # Read from the event, not files/: process_upload may not have written
    # the record yet. is_public is process_upload's rule, in base_record.
    metadata = data.get("metadata") or {}
    tag_file(
        file_id,
        [content],
        # RFC 3339 string -> datetime, so Firestore stores a timestamp
        uploaded_at=datetime.fromisoformat(data["timeCreated"]),
        is_public=metadata.get("is-public", "true") == "true",
    )


@functions_framework.cloud_event
def on_frames_ready(event):
    message = json.loads(base64.b64decode(event.data["message"]["data"]))
    file_id = message.get("file_id", "")
    frame_keys = message.get("frame_keys") or []
    if not FILE_ID.fullmatch(file_id) or not all(
        key.startswith(f"frames/{file_id}/") for key in frame_keys
    ):
        log("ERROR", "malformed frames-ready message, ignored", payload=message)
        return
    if not frame_keys:
        log("ERROR", "frames-ready with no frames, ignored", file_id=file_id)
        return

    bucket = gcs.bucket(message["bucket"])
    try:
        frames = [bucket.blob(key).download_as_bytes() for key in frame_keys]
    except exceptions.NotFound:
        log("INFO", "frames deleted before tagging", file_id=file_id)
        return
    tag_file(file_id, frames, video=True)
