#!/usr/bin/env python3
"""seed_data: loads 20 test records into Firestore so search, the gallery and
the chatbot can be built before real uploads flow, and removes them again.

Owner: member 2. Roadmap: Gate 2 ("seed data is loaded and the tag query
returns seeded files").

    python scripts/seed_data.py            # load; safe to re-run
    python scripts/seed_data.py --remove   # delete every record with seed: true

Runs as you (gcloud auth application-default login). Needs
scripts/requirements.txt. After editing SEEDS, run --remove first: a changed
seed draws a different image, so it gets a new file ID.

Each seed is a placeholder image or short video drawn here. Its file ID is the
SHA-256 of those bytes, as for a real upload, but only its thumbnail (and a
video's frames) is stored, in the derived bucket. An original in the media
bucket would fire process_upload and tagging, and tagging would replace the
seeded tags, so a seed's full-size link 404s while its thumbnail works.

Records follow docs/contracts/firestore-schema.md, with seed: true and
uploaded_at in the past, so date filters such as "yesterday" find something.
"""

import argparse
import hashlib
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import cv2
import numpy as np
from google.api_core import exceptions
from google.cloud import firestore, storage

# The script isn't deployed, so it imports the shared package from the repo.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "shared/python"))
from ecoguard_common.uploads import ACCEPTED  # noqa: E402

PROJECT = "ecoguard-g21"
MEDIA_BUCKET = "ecoguard-g21-media"
DERIVED_BUCKET = "ecoguard-g21-derived"
MELBOURNE = ZoneInfo("Australia/Melbourne")
SEED_USER = "seed-data"  # stands in for an uploader's Cognito sub

CONTENT_TYPE = {extension: kind for kind, (extension, _) in ACCEPTED.items()}

# (name, extension, tags, days ago, is_public). The name is drawn on the image
# and becomes its original filename.
SEEDS = [
    # {"fox": 2} returns fox-2, fox-3 and fox-video. A search that ignores
    # counts would also return fox-1 and fox-rabbit.
    ("fox-1", "jpg", {"fox": 1}, 0, True),
    ("fox-2", "png", {"fox": 2}, 1, True),
    ("fox-3", "webp", {"fox": 3}, 1, True),
    ("fox-rabbit", "jpg", {"fox": 1, "rabbit": 2}, 2, True),
    ("fox-video", "mp4", {"fox": 2}, 1, True),
    ("rabbit-4", "png", {"rabbit": 4}, 3, True),
    ("rabbit-1", "webp", {"rabbit": 1}, 9, True),
    # {"feral pig": 1, "cane toad": 3} returns pig-toad, pig-toad-more and
    # pig-toad-video. OR would add toad-only and pig-only; ignoring counts
    # would add pig-toad-short.
    ("pig-toad", "jpg", {"feral pig": 1, "cane toad": 3}, 1, True),
    ("pig-toad-more", "webp", {"feral pig": 2, "cane toad": 4}, 4, True),
    ("pig-toad-short", "jpg", {"feral pig": 1, "cane toad": 2}, 2, True),
    ("pig-toad-video", "mp4", {"feral pig": 1, "cane toad": 3}, 5, True),
    ("toad-only", "png", {"cane toad": 3}, 5, True),
    ("pig-only", "jpg", {"feral pig": 3}, 6, True),
    # Cats and dogs for species and lost pet search, which only counts
    # public files.
    ("cat-1", "jpg", {"cat": 1}, 0, True),
    ("cat-2", "webp", {"cat": 2}, 7, True),
    ("cat-private", "jpg", {"cat": 1}, 1, False),
    ("dog-1", "png", {"dog": 1}, 2, True),
    ("dog-private", "jpg", {"dog": 1}, 8, False),
    ("cat-dog", "jpg", {"cat": 1, "dog": 1}, 3, True),
    # Tagged, but with no animals: in no search results.
    ("no-animals", "png", {}, 9, True),
]

# Image sizes take turns, so thumbnails show the aspect ratio is kept.
SIZES = [(1600, 1200), (1200, 1600), (1920, 1080)]
VIDEO_SIZE = (1280, 720)
VIDEO_SECONDS = 25  # frames at 0, 10 and 20 s

# Background colour (blue, green, red) by the seed's first tag.
COLOURS = {
    "fox": (30, 110, 230),
    "rabbit": (110, 130, 150),
    "feral pig": (150, 120, 200),
    "cane toad": (60, 120, 110),
    "cat": (140, 80, 120),
    "dog": (170, 110, 50),
}


def draw(text: str, tags: dict, size: tuple[int, int]) -> np.ndarray:
    width, height = size
    colour = COLOURS[next(iter(tags))] if tags else (90, 90, 90)
    image = np.full((height, width, 3), colour, np.uint8)
    label = ", ".join(f"{count} {tag}" for tag, count in tags.items())
    lines = (text, label or "no animals")
    # One text size for both lines: the longer fills 90% of the width, so it
    # stays readable in a 320 px thumbnail.
    font = cv2.FONT_HERSHEY_SIMPLEX
    sizes = [cv2.getTextSize(line, font, 1, 2)[0] for line in lines]
    scale = min(0.9 * width / max(w for w, _ in sizes), max(size) / 400)
    line_height = round(sizes[0][1] * scale * 2)
    for index, line in enumerate(lines):
        position = (width // 20, height // 2 + index * line_height)
        thickness = round(scale * 2)
        cv2.putText(image, line, position, font, scale, (255,) * 3, thickness)
    return image


def encode(image: np.ndarray, extension: str, quality: int = 90) -> bytes:
    params = [cv2.IMWRITE_JPEG_QUALITY, quality] if extension == "jpg" else []
    _, data = cv2.imencode(f".{extension}", image, params)
    return data.tobytes()


def thumbnail(image: np.ndarray) -> bytes:
    """As storage-layout.md says: longest side 320 px, aspect ratio kept,
    JPEG quality 80."""
    height, width = image.shape[:2]
    scale = 320 / max(width, height)
    size = (round(width * scale), round(height * scale))
    small = cv2.resize(image, size, interpolation=cv2.INTER_AREA)
    return encode(small, "jpg", quality=80)


def video(name: str, tags: dict) -> tuple[bytes, list[np.ndarray]]:
    """An MP4 at one frame per second, and its frames at 0, 10, 20 s..."""
    frames = [
        draw(f"{name} {second}s", tags, VIDEO_SIZE)
        for second in range(VIDEO_SECONDS)
    ]
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "seed.mp4"
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(str(path), fourcc, 1, VIDEO_SIZE)
        for frame in frames:
            writer.write(frame)
        writer.release()
        return path.read_bytes(), frames[::10]


def original(index: int, seed: tuple) -> tuple[bytes, list[np.ndarray]]:
    """The seed's file bytes, and the frames its thumbnail and frame keys
    come from (an image is its own single frame)."""
    name, extension, tags, _, _ = seed
    if extension == "mp4":
        return video(name, tags)
    image = draw(name, tags, SIZES[index % len(SIZES)])
    return encode(image, extension), [image]


def build(index: int, seed: tuple, now: datetime) -> tuple[dict, dict]:
    """The seed's Firestore record, and its derived-bucket objects as
    {key: JPEG bytes}."""
    name, extension, tags, days_ago, is_public = seed
    data, frames = original(index, seed)
    file_id = hashlib.sha256(data).hexdigest()
    content_type = CONTENT_TYPE[extension]
    media_key = f"{file_id}.{extension}"
    thumbnail_key = f"thumbs/{file_id}.jpg"
    # A video's poster thumbnail is its first frame.
    objects = {thumbnail_key: thumbnail(frames[0])}
    record = {
        "file_id": file_id,
        "file_type": content_type.split("/")[0],
        "content_type": content_type,
        "original_filename": f"{name}.{extension}",
        "size_bytes": len(data),
        "media_bucket": MEDIA_BUCKET,
        "media_key": media_key,
        "media_uri": f"gs://{MEDIA_BUCKET}/{media_key}",
        "thumbnail_key": thumbnail_key,
        "thumbnail_uri": f"gs://{DERIVED_BUCKET}/{thumbnail_key}",
        "uploaded_by": SEED_USER,
        # The minutes keep the order fixed for seeds on the same day.
        "uploaded_at": now - timedelta(days=days_ago, minutes=index),
        "is_public": is_public,
        "status": "active",
        "pipeline": {"thumbnail": "done", "tagging": "done"},
        "tags": tags,
        "seed": True,
    }
    if record["file_type"] == "video":
        frame_keys = [
            f"frames/{file_id}/{i:04d}.jpg" for i in range(len(frames))
        ]
        objects |= {
            key: encode(frame, "jpg") for key, frame in zip(frame_keys, frames)
        }
        record["frame_keys"] = frame_keys
        record["duration_s"] = VIDEO_SECONDS
        record["pipeline"]["frames"] = "done"
    return record, objects


def load(db, derived):
    now = datetime.now(MELBOURNE)
    for index, seed in enumerate(SEEDS):
        record, objects = build(index, seed, now)
        for key, data in objects.items():
            derived.blob(key).upload_from_string(
                data, content_type="image/jpeg"
            )
        # Objects first, so a record never points at a missing thumbnail.
        db.collection("files").document(record["file_id"]).set(
            record, merge=True
        )
        print(f"loaded {record['original_filename']:20} {record['file_id']}")
    print(f"{len(SEEDS)} seeds loaded")


def remove(db, derived):
    seeds = db.collection("files").where(
        filter=firestore.FieldFilter("seed", "==", True)
    )
    count = 0
    for doc in seeds.stream():
        for blob in derived.list_blobs(prefix=f"frames/{doc.id}/"):
            blob.delete()
        try:
            derived.blob(f"thumbs/{doc.id}.jpg").delete()
        except exceptions.NotFound:
            pass
        # As delete_files does: no sighting outlives its file.
        sightings = db.collection("sightings").where(
            filter=firestore.FieldFilter("file_id", "==", doc.id)
        )
        for sighting in sightings.stream():
            sighting.reference.delete()
        # The record goes last, so a run that fails part way can be re-run.
        doc.reference.delete()
        count += 1
    print(f"{count} seeds removed")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--remove",
        action="store_true",
        help="delete every seeded record and its objects",
    )
    args = parser.parse_args()
    db = firestore.Client(project=PROJECT)
    derived = storage.Client(project=PROJECT).bucket(DERIVED_BUCKET)
    if args.remove:
        remove(db, derived)
    else:
        load(db, derived)


if __name__ == "__main__":
    main()
