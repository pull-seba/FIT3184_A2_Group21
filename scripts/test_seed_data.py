"""Tests for seed_data.py. Run from the repo root: python -m pytest scripts"""

import hashlib
import re
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

import cv2
import numpy as np
import pytest
from google.api_core import exceptions

import seed_data
from ecoguard_common.tag_match import known_tags, matches

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 29, 12, 0, tzinfo=seed_data.MELBOURNE)


@pytest.fixture(scope="module")
def built():
    """Every seed's (record, objects), built once: the videos take a moment."""
    return [
        seed_data.build(index, seed, NOW)
        for index, seed in enumerate(seed_data.SEEDS)
    ]


def records(built):
    return [record for record, _ in built]


def names(records):
    return {record["original_filename"].split(".")[0] for record in records}


def found(built, query):
    """The seeds a correct tag search returns."""
    return names(r for r in records(built) if matches(r, query))


def schema_fields():
    """The field names in the schema's files table."""
    schema = (ROOT / "docs/contracts/firestore-schema.md").read_text()
    files_table = schema.split("## `files/{file_id}`")[1].split("\n## ")[0]
    return set(re.findall(r"^\| `([a-z_.]+)` \|", files_table, re.MULTILINE))


def test_records_use_only_schema_fields(built):
    allowed = schema_fields()
    for record in records(built):
        fields = {key for key in record if key != "pipeline"}
        fields |= {f"pipeline.{step}" for step in record["pipeline"]}
        assert fields <= allowed, fields - allowed


def test_tags_are_in_the_tag_list_with_counts_of_at_least_1(built):
    for record in records(built):
        for tag, count in record["tags"].items():
            assert tag in known_tags()
            assert count >= 1


def test_file_id_is_the_sha256_of_the_redrawn_original(built):
    # Redrawing gives the same bytes, so a re-run updates the same records.
    for index, seed in enumerate(seed_data.SEEDS):
        data, _ = seed_data.original(index, seed)
        assert built[index][0]["file_id"] == hashlib.sha256(data).hexdigest()


def test_every_seed_has_its_own_file_id(built):
    ids = [record["file_id"] for record in records(built)]
    assert len(set(ids)) == len(seed_data.SEEDS) == 20


def test_keys_and_addresses_follow_the_storage_layout(built):
    for record, objects in built:
        file_id = record["file_id"]
        extension = record["original_filename"].split(".")[1]
        assert record["media_key"] == f"{file_id}.{extension}"
        assert record["media_uri"] == (
            f"gs://ecoguard-g21-media/{file_id}.{extension}"
        )
        assert record["thumbnail_key"] == f"thumbs/{file_id}.jpg"
        assert record["thumbnail_uri"] == (
            f"gs://ecoguard-g21-derived/thumbs/{file_id}.jpg"
        )
        assert record["content_type"] in seed_data.ACCEPTED
        assert record["seed"] is True
        assert record["status"] == "active"
        assert all(
            key == record["thumbnail_key"]
            or key.startswith(f"frames/{file_id}/")
            for key in objects
        )


def test_formats_cover_jpeg_png_webp_and_video(built):
    types = {record["content_type"] for record in records(built)}
    assert types == {"image/jpeg", "image/png", "image/webp", "video/mp4"}


def test_thumbnails_fit_in_320_and_keep_the_aspect_ratio(built):
    for index, (record, objects) in enumerate(built):
        data = objects[record["thumbnail_key"]]
        thumbnail = cv2.imdecode(
            np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR
        )
        height, width = thumbnail.shape[:2]
        if record["file_type"] == "video":
            original_width, original_height = seed_data.VIDEO_SIZE
        else:
            sizes = seed_data.SIZES
            original_width, original_height = sizes[index % len(sizes)]
        assert max(width, height) == 320
        assert width / height == pytest.approx(
            original_width / original_height, rel=0.01
        )


def test_videos_have_a_poster_and_a_frame_every_10_seconds(built):
    videos = [(r, o) for r, o in built if r["file_type"] == "video"]
    assert len(videos) == 2
    for record, objects in videos:
        file_id = record["file_id"]
        assert record["duration_s"] == 25
        assert record["frame_keys"] == [
            f"frames/{file_id}/0000.jpg",
            f"frames/{file_id}/0001.jpg",
            f"frames/{file_id}/0002.jpg",
        ]
        assert set(record["frame_keys"]) | {record["thumbnail_key"]} == set(
            objects
        )
        assert record["pipeline"]["frames"] == "done"


def test_fox_2_needs_at_least_two_foxes(built):
    assert found(built, {"fox": 2}) == {"fox-2", "fox-3", "fox-video"}


def test_pig_and_toad_need_both_tags_and_both_counts(built):
    query = {"feral pig": 1, "cane toad": 3}
    assert found(built, query) == {
        "pig-toad",
        "pig-toad-more",
        "pig-toad-video",
    }

    # The rubric's 50% cases would visibly return more.
    with_or = names(
        r
        for r in records(built)
        if any(r["tags"].get(tag, 0) >= count for tag, count in query.items())
    )
    ignoring_counts = names(
        r for r in records(built) if all(tag in r["tags"] for tag in query)
    )
    assert {"toad-only", "pig-only"} <= with_or
    assert "pig-toad-short" in ignoring_counts


def test_foxes_spotted_yesterday_differ_from_all_foxes(built):
    yesterday = {
        r["original_filename"].split(".")[0]
        for r in records(built)
        if "fox" in r["tags"]
        and r["uploaded_at"].date() == (NOW - timedelta(days=1)).date()
    }
    assert yesterday == {"fox-2", "fox-3", "fox-video"}
    assert found(built, {"fox": 1}) > yesterday


def test_some_cats_and_dogs_are_not_public(built):
    pets = [r for r in records(built) if {"cat", "dog"} & set(r["tags"])]
    assert {r["is_public"] for r in pets} == {True, False}


def test_load_stores_every_object_then_merges_each_record():
    db, derived = mock.Mock(), mock.Mock()
    order = []
    upload = derived.blob.return_value.upload_from_string
    upload.side_effect = lambda *args, **kwargs: order.append("object")
    doc = db.collection.return_value.document.return_value
    doc.set.side_effect = lambda *args, **kwargs: order.append("record")

    seed_data.load(db, derived)

    db.collection.assert_called_with("files")
    assert doc.set.call_count == 20
    for call in doc.set.call_args_list:
        assert call.kwargs == {"merge": True}
        assert call.args[0]["seed"] is True
    # 20 thumbnails and 3 frames for each of the 2 videos.
    assert upload.call_count == 26
    assert order[0] == "object" and order[-1] == "record"


def test_remove_deletes_seeds_with_their_objects_and_sightings():
    file_id = "ab" * 32
    seeded = mock.Mock(id=file_id)
    sighting = mock.Mock()
    files, sightings = mock.Mock(), mock.Mock()
    files.where.return_value.stream.return_value = [seeded]
    sightings.where.return_value.stream.return_value = [sighting]
    db = mock.Mock()
    db.collection.side_effect = {"files": files, "sightings": sightings}.get
    derived = mock.Mock()
    frame = mock.Mock()
    derived.list_blobs.return_value = [frame]
    # A thumbnail an earlier run already deleted doesn't stop the run.
    derived.blob.return_value.delete.side_effect = exceptions.NotFound("gone")

    seed_data.remove(db, derived)

    seed_filter = files.where.call_args.kwargs["filter"]
    assert (seed_filter.field_path, seed_filter.value) == ("seed", True)
    derived.list_blobs.assert_called_once_with(prefix=f"frames/{file_id}/")
    frame.delete.assert_called_once()
    derived.blob.assert_called_once_with(f"thumbs/{file_id}.jpg")
    sighting_filter = sightings.where.call_args.kwargs["filter"]
    assert sighting_filter.value == file_id
    sighting.reference.delete.assert_called_once()
    seeded.reference.delete.assert_called_once()
