#!/usr/bin/env python3
"""
Member 3 - re-tag files whose `model_version` is older than `config/model`.

Tagging only runs when a file is uploaded, so after a config push (a new
threshold, or sightings added in 2026-10-31.1) older files keep their old
tags and have no lost pet sightings. This sends each one the same event its
upload sent, straight to the deployed function:

- an image: a storage `finalized` CloudEvent to `tagging` (on_upload)
- a video: a Pub/Sub `frames-ready` CloudEvent to `tagging-frames`

Nothing else sees these events, so process_upload doesn't run again, and the
image event keeps the object's real `timeCreated`, so sightings get the true
upload date. tag_file's own check skips any file already on the current
version, so running this twice is safe. Seeded records have no original
file and are left out.

  python3 functions/ml/config/retag_stale.py           # list only
  python3 functions/ml/config/retag_stale.py --apply   # send the events

Needs `pip install google-cloud-firestore google-cloud-storage requests`,
Application Default Credentials, and a gcloud account that may invoke the
two Cloud Run services (run.invoker or run.admin).
"""

import argparse
import base64
import json
import subprocess
import uuid

PROJECT = "ecoguard-g21"
REGION = "us-east1"


def gcloud(*args):
    return subprocess.run(
        ["gcloud", *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def service_url(name):
    return gcloud(
        "functions", "describe", name, f"--region={REGION}",
        "--format=value(serviceConfig.uri)",
    )  # fmt: skip


def stale_files(db, version):
    """Active, non-seed files tagged by an older config version."""
    for doc in db.collection("files").stream():
        record = doc.to_dict()
        if record.get("seed") or record.get("status") != "active":
            continue
        if record.get("model_version") != version:
            yield record


def image_event(gcs, record):
    """The storage event on_upload reads, rebuilt from the stored object."""
    blob = gcs.bucket(record["media_bucket"]).get_blob(record["media_key"])
    data = {
        "bucket": blob.bucket.name,
        "name": blob.name,
        "contentType": blob.content_type,
        "size": str(blob.size),
        "generation": str(blob.generation),
        "timeCreated": blob.time_created.isoformat(),
        "metadata": blob.metadata or {},
    }
    headers = {
        "ce-type": "google.cloud.storage.object.v1.finalized",
        "ce-source": f"//storage.googleapis.com/projects/_/buckets/{blob.bucket.name}",
        "ce-subject": f"objects/{blob.name}",
    }
    return headers, data


def frames_event(record):
    """The frames-ready message process_upload published, wrapped the way
    Pub/Sub delivers it (events.md)."""
    derived_bucket = record["thumbnail_uri"].split("/")[2]
    message = {
        "file_id": record["file_id"],
        "bucket": derived_bucket,
        "frame_keys": record["frame_keys"],
        "duration_s": record.get("duration_s"),
    }
    data = {
        "message": {
            "data": base64.b64encode(json.dumps(message).encode()).decode(),
            "messageId": str(uuid.uuid4()),
        }
    }
    headers = {
        "ce-type": "google.cloud.pubsub.topic.v1.messagePublished",
        "ce-source": f"//pubsub.googleapis.com/projects/{PROJECT}/topics/frames-ready",
    }
    return headers, data


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--project", default=PROJECT)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    from google.cloud import firestore, storage

    db = firestore.Client(project=args.project)
    version = db.document("config/model").get().get("version")
    stale = list(stale_files(db, version))
    print(f"config/model version {version}: {len(stale)} file(s) to re-tag")
    for record in stale:
        print(
            f"  {record['file_id'][:10]}  {record['file_type']:5}  "
            f"{record.get('model_version')}  {record.get('original_filename')}"
        )
    if not args.apply or not stale:
        print("List only, nothing sent. Add --apply to re-tag.")
        return

    import requests

    gcs = storage.Client(project=args.project)
    urls = {
        "image": service_url("tagging"),
        "video": service_url("tagging-frames"),
    }
    # A gcloud user's ID token is accepted by Cloud Run for any audience.
    token = gcloud("auth", "print-identity-token")
    for record in stale:
        if record["file_type"] == "image":
            headers, data = image_event(gcs, record)
        else:
            headers, data = frames_event(record)
        headers |= {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "ce-id": str(uuid.uuid4()),
            "ce-specversion": "1.0",
        }
        response = requests.post(
            urls[record["file_type"]], headers=headers, json=data, timeout=540
        )
        print(f"  {record['file_id'][:10]}  HTTP {response.status_code}")
    print("Check: gcloud functions logs read tagging --region=us-east1")


if __name__ == "__main__":
    main()
