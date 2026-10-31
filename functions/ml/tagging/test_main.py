"""Tests mock every cloud client; nothing here touches the shared project or
calls Rekognition."""

import base64
import hashlib
import json
from unittest import mock

import pytest
from cloudevents.http import CloudEvent
from google.api_core import exceptions
from google.cloud import firestore

from ecoguard_ml import BadImage

with (
    mock.patch("google.cloud.firestore.Client"),
    mock.patch("google.cloud.storage.Client"),
):
    import main

CONTENT = b"pretend these are the bytes of fox-cam3.jpg"
SHA = hashlib.sha256(CONTENT).hexdigest()
CONFIG = {"version": "2026-10-29.1", "detector": "rekognition"}


def object_data(**overrides):
    """The Cloud Storage object an Eventarc finalized event carries."""
    data = {
        "bucket": "ecoguard-g21-media",
        "name": f"{SHA}.jpg",
        "generation": "1761471780000000",
        "contentType": "image/jpeg",
        "size": str(len(CONTENT)),
        "metadata": {"uploaded-by": "cognito-sub-1", "is-public": "true"},
    }
    data.update(overrides)
    return data


def finalized(data):
    return CloudEvent(
        {
            "type": "google.cloud.storage.object.v1.finalized",
            "source": "//storage.googleapis.com/projects/_/buckets/media",
        },
        data,
    )


def frames_ready(message):
    data = base64.b64encode(json.dumps(message).encode()).decode()
    return CloudEvent(
        {
            "type": "google.cloud.pubsub.topic.v1.messagePublished",
            "source": "//pubsub.googleapis.com/projects/p/topics/frames-ready",
        },
        {"message": {"data": data}},
    )


@pytest.fixture(autouse=True)
def db(monkeypatch):
    """A fresh Firestore fake for every test, holding no document."""
    db = mock.Mock()
    db.collection.return_value.document.return_value.get.return_value = (
        mock.Mock(to_dict=lambda: None)
    )
    monkeypatch.setattr(main, "db", db)
    return db


@pytest.fixture(autouse=True)
def gcs(monkeypatch):
    """A fresh Storage fake: every object holds CONTENT."""
    gcs = mock.Mock()
    gcs.bucket.return_value.blob.return_value.download_as_bytes.return_value = (
        CONTENT
    )
    monkeypatch.setattr(main, "gcs", gcs)
    return gcs


@pytest.fixture(autouse=True)
def config(monkeypatch):
    monkeypatch.setattr(main, "model_config", mock.Mock(get=lambda: CONFIG))


@pytest.fixture(autouse=True)
def analyse(monkeypatch):
    """Rekognition replaced: every image has one fox."""
    analyse = mock.Mock(return_value=({"fox": 1}, []))
    monkeypatch.setattr(main.detect, "analyse", analyse)
    return analyse


@pytest.fixture(autouse=True)
def write_tags(monkeypatch):
    write_tags = mock.Mock()
    monkeypatch.setattr(main, "write_tags", write_tags)
    return write_tags


def doc(db):
    return db.collection.return_value.document.return_value


def stored_record(db, record):
    doc(db).get.return_value = mock.Mock(to_dict=lambda: record)


# ---------- uploads ----------


def test_image_upload_is_tagged(db, analyse, write_tags):
    main.on_upload(finalized(object_data()))
    analyse.assert_called_once_with(CONTENT, CONFIG)
    db.collection.assert_called_with("files")
    db.collection.return_value.document.assert_called_with(SHA)
    write_tags.assert_called_once_with(doc(db), {"fox": 1}, CONFIG["version"])


@pytest.mark.parametrize(
    "content_type,ext", [("image/png", "png"), ("image/webp", "webp")]
)
def test_png_and_webp_uploads_are_tagged(content_type, ext, write_tags):
    data = object_data(name=f"{SHA}.{ext}", contentType=content_type)
    main.on_upload(finalized(data))
    write_tags.assert_called_once()


def test_video_upload_waits_for_frames_ready(gcs, analyse):
    data = object_data(name=f"{SHA}.mp4", contentType="video/mp4")
    main.on_upload(finalized(data))
    analyse.assert_not_called()
    gcs.bucket.assert_not_called()


@pytest.mark.parametrize(
    "overrides",
    [
        {"name": "fox-cam3.jpg"},  # not <sha256>.<ext>
        {"name": f"{SHA}.png"},  # extension doesn't match the type
        {"contentType": "image/heic"},  # not accepted
        {"size": str(21 * 1024 * 1024)},  # over 20 MB
        {"metadata": {}},  # no uploaded-by: not from upload_init
    ],
)
def test_objects_process_upload_will_reject_are_skipped(overrides, analyse):
    main.on_upload(finalized(object_data(**overrides)))
    analyse.assert_not_called()


def test_bytes_that_dont_hash_to_their_key_are_not_tagged(gcs, analyse):
    blob = gcs.bucket.return_value.blob.return_value
    blob.download_as_bytes.return_value = b"different bytes"
    main.on_upload(finalized(object_data()))
    analyse.assert_not_called()


def test_object_deleted_before_tagging_is_ignored(gcs, write_tags):
    blob = gcs.bucket.return_value.blob.return_value
    blob.download_as_bytes.side_effect = exceptions.NotFound("gone")
    main.on_upload(finalized(object_data()))
    write_tags.assert_not_called()


def test_reads_the_exact_generation_that_triggered(gcs):
    main.on_upload(finalized(object_data()))
    gcs.bucket.return_value.blob.assert_called_once_with(
        f"{SHA}.jpg", generation=1761471780000000
    )


# ---------- idempotency and errors ----------


def test_repeat_event_with_the_same_model_does_nothing(db, analyse):
    stored_record(
        db,
        {"model_version": CONFIG["version"], "pipeline": {"tagging": "done"}},
    )
    main.on_upload(finalized(object_data()))
    analyse.assert_not_called()


def test_file_tagged_by_an_older_model_is_tagged_again(db, write_tags):
    stored_record(
        db, {"model_version": "2026-10-01.1", "pipeline": {"tagging": "done"}}
    )
    main.on_upload(finalized(object_data()))
    write_tags.assert_called_once()


def test_unreadable_image_is_marked_failed_not_retried(db, analyse, write_tags):
    analyse.side_effect = BadImage("cannot identify image file")
    main.on_upload(finalized(object_data()))
    doc(db).set.assert_called_once_with(
        {"pipeline": {"tagging": "failed"}}, merge=True
    )
    write_tags.assert_not_called()


def test_other_errors_raise_so_the_event_is_retried(analyse):
    analyse.side_effect = RuntimeError("throttled")
    with pytest.raises(RuntimeError):
        main.on_upload(finalized(object_data()))


# ---------- videos: frames-ready ----------


def frame_message(count=3):
    return {
        "file_id": SHA,
        "bucket": "ecoguard-g21-derived",
        "frame_keys": [f"frames/{SHA}/{i:04d}.jpg" for i in range(count)],
        "duration_s": 24.0,
    }


def test_video_count_is_the_maximum_in_any_one_frame(analyse, write_tags):
    analyse.side_effect = [
        ({"fox": 1}, []),
        ({"fox": 2, "rabbit": 1}, []),
        ({"fox": 1}, []),
    ]
    main.on_frames_ready(frames_ready(frame_message()))
    # fox is 2 (frame 2), not 1 + 2 + 1 = 4
    write_tags.assert_called_once()
    assert write_tags.call_args.args[1] == {"fox": 2, "rabbit": 1}


def test_frames_are_read_from_the_derived_bucket(gcs, analyse):
    main.on_frames_ready(frames_ready(frame_message(2)))
    gcs.bucket.assert_called_once_with("ecoguard-g21-derived")
    keys = [c.args[0] for c in gcs.bucket.return_value.blob.call_args_list]
    assert keys == [f"frames/{SHA}/0000.jpg", f"frames/{SHA}/0001.jpg"]
    assert analyse.call_count == 2


@pytest.mark.parametrize(
    "message",
    [
        {**frame_message(), "file_id": "not-a-hash"},
        {**frame_message(), "frame_keys": ["frames/someone-else/0000.jpg"]},
        {**frame_message(), "frame_keys": []},
    ],
)
def test_malformed_frames_ready_is_ignored(message, analyse):
    main.on_frames_ready(frames_ready(message))
    analyse.assert_not_called()


def test_frames_deleted_before_tagging_are_ignored(gcs, write_tags):
    blob = gcs.bucket.return_value.blob.return_value
    blob.download_as_bytes.side_effect = exceptions.NotFound("gone")
    main.on_frames_ready(frames_ready(frame_message()))
    write_tags.assert_not_called()


# ---------- the tags write ----------


def test_max_per_tag_with_one_image_is_its_own_tags():
    assert main.max_per_tag([{"fox": 2}]) == {"fox": 2}
    assert main.max_per_tag([]) == {}


def test_manual_tags_survive_re_tagging_with_their_count():
    record = {"tags": {"fox": 1, "cat": 1, "rabbit": 2}, "manual_tags": ["cat"]}
    # the model now sees one dog: rabbit (automatic) goes, cat (manual) stays
    assert main.keep_manual_tags({"dog": 1}, record) == {"dog": 1, "cat": 1}


def test_manual_count_wins_over_the_detected_count():
    record = {"tags": {"fox": 3}, "manual_tags": ["fox"]}
    assert main.keep_manual_tags({"fox": 1}, record) == {"fox": 3}


def test_first_tagging_of_a_new_record():
    assert main.keep_manual_tags({"fox": 2}, {}) == {"fox": 2}


def test_tags_write_replaces_only_tagging_fields(db):
    """The body of the transactional write, run with a fake transaction
    (to_wrap is the function @firestore.transactional wrapped)."""
    transaction = mock.Mock()
    stored_record(db, {"tags": {"cat": 1}, "manual_tags": ["cat"]})

    main._write_tags.to_wrap(transaction, doc(db), {"fox": 2}, "v9")

    transaction.set.assert_called_once_with(
        doc(db),
        {
            "tags": {"fox": 2, "cat": 1},
            "model_version": "v9",
            "tagged_at": firestore.SERVER_TIMESTAMP,
            "pipeline": {"tagging": "done"},
        },
        merge=["tags", "model_version", "tagged_at", "pipeline.tagging"],
    )
    doc(db).get.assert_called_once_with(transaction=transaction)
