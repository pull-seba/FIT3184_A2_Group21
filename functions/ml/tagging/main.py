"""tagging: species tags with counts for every uploaded image and video.

Owner: member 3. Rubric 2.1.3. Triggers: see README.md.
"""

import base64
import hashlib
import json
import re

import functions_framework
from google.api_core import exceptions
from google.cloud import firestore, storage

from ecoguard_common.logs import log
from ecoguard_common.uploads import MEDIA_KEY, rejection_reason
from ecoguard_ml import BadImage, detect

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


def tag_file(file_id: str, images: list[bytes]):
    config = detect.model_config(db)
    doc = db.collection("files").document(file_id)
    record = doc.get().to_dict() or {}
    if (
        record.get("model_version") == config["version"]
        and (record.get("pipeline") or {}).get("tagging") == "done"
    ):
        log("INFO", "already tagged, repeat event ignored", file_id=file_id)
        return

    # Any other error (throttling, network, federation) is raised, so
    # Eventarc or Pub/Sub delivers the event again.
    try:
        results = [detect.analyse(image, config) for image in images]
    except BadImage as error:
        doc.set({"pipeline": {"tagging": "failed"}}, merge=True)
        log("ERROR", "image can't be tagged", file_id=file_id, error=str(error))
        return

    tags = max_per_tag([counts for counts, _ in results])
    write_tags(doc, tags, config["version"])
    log(
        "INFO",
        "tagged",
        file_id=file_id,
        tags=tags,
        images=len(results),
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
    tag_file(file_id, [content])


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
    tag_file(file_id, frames)
