"""tagging: species tags with counts for every uploaded image and video.

Owner: member 3. Rubric 2.1.3. Triggers: docs/contracts/events.md.

Two entry points in one folder, deployed as two functions (README.md):
- on_upload: the media bucket's object-finalized event. Tags images and
  returns at once for videos, which wait for their frames.
- on_frames_ready: the frames-ready message process_upload publishes for a
  video. Tags each frame and keeps each tag's highest count in any one frame.

Both are idempotent (Eventarc and Pub/Sub can deliver twice): a repeat event
for a file already tagged with the current config/model version does nothing.
Errors that a retry could fix are raised so the event is delivered again;
an image Rekognition can't read is marked pipeline.tagging = "failed".
"""

import base64
import hashlib
import json
import re

import functions_framework
from google.api_core import exceptions
from google.cloud import firestore, storage

from ecoguard_common.logs import log
from ecoguard_common.uploads import ACCEPTED
from ecoguard_ml import BadImage, detect

db = firestore.Client()  # created once per instance, reused across events
gcs = storage.Client()

FILE_ID = re.compile(r"[0-9a-f]{64}")
MEDIA_KEY = re.compile(r"(?P<file_id>[0-9a-f]{64})\.(?P<ext>[a-z0-9]+)")
# The only fields tagging writes (firestore-schema.md). set() with this list
# replaces exactly these, so an automatic tag the model no longer finds goes
# away, and works whether or not process_upload has written the record yet.
TAGGING_FIELDS = ["tags", "model_version", "tagged_at", "pipeline.tagging"]


def upload_file_id(data: dict) -> str | None:
    """The file ID if the object looks like an upload_init upload, else
    None. process_upload deletes anything else, so tagging skips it."""
    match = MEDIA_KEY.fullmatch(data["name"])
    accepted = ACCEPTED.get(data.get("contentType", ""))
    if not match or not accepted or accepted[0] != match["ext"]:
        return None
    if int(data["size"]) > accepted[1]:
        return None
    if not (data.get("metadata") or {}).get("uploaded-by"):
        return None
    return match["file_id"]


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
    """Tag one file from its image, or from a video's frames."""
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
        # Per image or frame: the labels each count came from.
        labels=[detect.animal_labels(labels) for _, labels in results],
    )


@functions_framework.cloud_event
def on_upload(event):
    data = event.data  # the Cloud Storage object; numbers arrive as strings
    file_id = upload_file_id(data)
    if file_id is None:
        log("INFO", "not a valid upload, ignored", key=data["name"])
        return
    if data["contentType"].startswith("video/"):
        log("INFO", "video: tagged from frames-ready", file_id=file_id)
        return

    blob = gcs.bucket(data["bucket"]).blob(
        data["name"], generation=int(data["generation"])
    )
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
    """Payload: {"file_id", "bucket", "frame_keys", "duration_s"}."""
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
