"""Tests mock every cloud client; nothing here touches the shared project."""

import hashlib
import io
import json
from unittest import mock

import pytest
from cloudevents.http import CloudEvent
from google.api_core import exceptions
from google.cloud import firestore

from ecoguard_common.uploads import MB

with (
    mock.patch("google.cloud.firestore.Client"),
    mock.patch("google.cloud.storage.Client"),
):
    import main

CONTENT = b"pretend these are the bytes of fox-cam3.jpg"
SHA = hashlib.sha256(CONTENT).hexdigest()
BUCKET = "ecoguard-g21-media"
GENERATION = "1761471780000000"


def object_data(**overrides):
    """The Cloud Storage object an Eventarc finalized event carries, as upload_init's URL creates it."""
    data = {
        "bucket": BUCKET,
        "name": f"{SHA}.jpg",
        "generation": GENERATION,
        "contentType": "image/jpeg",
        "size": str(len(CONTENT)),
        "metadata": {
            "uploaded-by": "cognito-sub-1",
            "original-filename": "fox%20cam%283%29.jpg",
            "is-public": "true",
        },
    }
    data.update(overrides)
    return data


def finalized(data):
    return CloudEvent(
        {
            "type": "google.cloud.storage.object.v1.finalized",
            "source": f"//storage.googleapis.com/projects/_/buckets/{BUCKET}",
        },
        data,
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
    """A fresh Storage fake for every test: the object holds CONTENT."""
    gcs = mock.Mock()
    gcs.bucket.return_value.blob.return_value.open.side_effect = (
        lambda *a, **kw: io.BytesIO(CONTENT)
    )
    monkeypatch.setattr(main, "gcs", gcs)
    return gcs


def doc(db):
    return db.collection.return_value.document.return_value


def blob(gcs):
    return gcs.bucket.return_value.blob.return_value


def stored_record(db, data):
    doc(db).get.return_value = mock.Mock(to_dict=lambda: data)


def last_log(capsys):
    return json.loads(capsys.readouterr().out.strip().splitlines()[-1])


# ---- A valid upload gets its base record ----


def test_verified_image_gets_its_base_record(db, gcs):
    main.handler(finalized(object_data()))

    db.collection.assert_called_with("files")
    db.collection.return_value.document.assert_called_with(SHA)
    doc(db).set.assert_called_once_with(
        {
            "file_id": SHA,
            "file_type": "image",
            "content_type": "image/jpeg",
            "original_filename": "fox cam(3).jpg",
            "size_bytes": len(CONTENT),
            "media_bucket": BUCKET,
            "media_key": f"{SHA}.jpg",
            "media_uri": f"gs://{BUCKET}/{SHA}.jpg",
            "uploaded_by": "cognito-sub-1",
            "uploaded_at": firestore.SERVER_TIMESTAMP,
            "is_public": True,
            "status": "active",
        },
        merge=True,
    )
    blob(gcs).delete.assert_not_called()


def test_reads_exactly_the_generation_that_fired_the_event(gcs):
    main.handler(finalized(object_data()))
    gcs.bucket.assert_called_with(BUCKET)
    gcs.bucket.return_value.blob.assert_called_with(
        f"{SHA}.jpg", generation=int(GENERATION)
    )
    blob(gcs).open.assert_called_once_with("rb", raw_download=True)


def test_video_is_recorded_as_a_video(db):
    main.handler(
        finalized(object_data(name=f"{SHA}.mp4", contentType="video/mp4"))
    )
    written = doc(db).set.call_args.args[0]
    assert (
        written["file_type"] == "video" and written["media_key"] == f"{SHA}.mp4"
    )


@pytest.mark.parametrize(
    "value, expected", [("true", True), ("false", False), ("yes", False)]
)
def test_is_public_comes_from_the_object_metadata(value, expected, db):
    data = object_data()
    data["metadata"]["is-public"] = value
    main.handler(finalized(data))
    assert doc(db).set.call_args.args[0]["is_public"] is expected


def test_is_public_defaults_to_true(db):
    data = object_data()
    del data["metadata"]["is-public"]
    main.handler(finalized(data))
    assert doc(db).set.call_args.args[0]["is_public"] is True


def test_document_from_tagging_alone_still_gets_its_base_record(db):
    stored_record(
        db, {"tags": {"fox": 1}, "model_version": "yolo-1"}
    )  # no media_key
    main.handler(finalized(object_data()))
    _, kwargs = doc(db).set.call_args
    assert kwargs == {"merge": True}  # merge keeps the tags already there


# ---- Repeat events change nothing ----


def test_repeat_event_for_a_recorded_file_does_nothing(capsys, db, gcs):
    stored_record(db, {"media_key": f"{SHA}.jpg", "status": "active"})
    main.handler(finalized(object_data()))
    blob(gcs).open.assert_not_called()  # no second download
    doc(db).set.assert_not_called()  # uploaded_at keeps its first value
    blob(gcs).delete.assert_not_called()
    assert last_log(capsys)["severity"] == "INFO"


def test_same_bytes_under_another_type_are_deleted_as_a_duplicate(
    capsys, db, gcs
):
    stored_record(db, {"media_key": f"{SHA}.jpg", "status": "active"})
    main.handler(
        finalized(object_data(name=f"{SHA}.png", contentType="image/png"))
    )
    blob(gcs).delete.assert_called_once_with()
    doc(db).set.assert_not_called()
    assert last_log(capsys)["reason"] == "duplicate"


def test_file_being_deleted_is_processed_as_new(db):
    stored_record(db, {"media_key": f"{SHA}.jpg", "status": "deleting"})
    main.handler(finalized(object_data()))
    doc(db).set.assert_called_once()


def test_object_deleted_before_processing_writes_nothing(db, gcs):
    blob(gcs).open.side_effect = exceptions.NotFound("gone")
    main.handler(finalized(object_data()))
    doc(db).set.assert_not_called()


# ---- Anything that isn't a valid upload is deleted, with no record ----


def assert_rejected(db, gcs, capsys, reason):
    blob(gcs).delete.assert_called_once_with()
    doc(db).set.assert_not_called()
    logged = last_log(capsys)
    assert logged["severity"] == "WARNING" and logged["reason"] == reason


def test_hash_mismatch_deletes_the_object(capsys, db, gcs):
    other = hashlib.sha256(b"different bytes").hexdigest()
    main.handler(finalized(object_data(name=f"{other}.jpg")))
    assert_rejected(db, gcs, capsys, "hash_mismatch")


@pytest.mark.parametrize(
    "name",
    ["fox.jpg", f"{SHA.upper()}.jpg", f"{SHA}.jpg.exe", f"thumbs/{SHA}.jpg"],
)
def test_key_that_is_not_a_file_id_is_deleted_unread(name, capsys, db, gcs):
    main.handler(finalized(object_data(name=name)))
    assert_rejected(db, gcs, capsys, "bad_key")
    blob(gcs).open.assert_not_called()
    db.collection.assert_not_called()


@pytest.mark.parametrize(
    "name, content_type",
    [
        (f"{SHA}.jpg", "image/heic"),  # not accepted
        (f"{SHA}.jpg", "image/png"),  # type doesn't match the extension
        (f"{SHA}.gif", "image/gif"),
        (f"{SHA}.jpg", None),
    ],
)
def test_wrong_or_unaccepted_type_is_deleted(
    name, content_type, capsys, db, gcs
):
    main.handler(finalized(object_data(name=name, contentType=content_type)))
    assert_rejected(db, gcs, capsys, "bad_type")


def test_image_over_20_mb_is_deleted_without_downloading(capsys, db, gcs):
    # The browser can claim any size to upload_init; the stored size is the real one.
    main.handler(finalized(object_data(size=str(20 * MB + 1))))
    assert_rejected(db, gcs, capsys, "too_large")
    blob(gcs).open.assert_not_called()


def test_video_over_20_mb_within_its_200_mb_limit_is_accepted(db, gcs):
    content = b"v" * 64
    sha = hashlib.sha256(content).hexdigest()
    blob(gcs).open.side_effect = lambda *a, **kw: io.BytesIO(content)
    main.handler(
        finalized(
            object_data(
                name=f"{sha}.mov",
                contentType="video/quicktime",
                size=str(150 * MB),
            )
        )
    )
    doc(db).set.assert_called_once()


@pytest.mark.parametrize("metadata", [{}, None, {"uploaded-by": ""}])
def test_object_without_an_uploader_is_deleted(metadata, capsys, db, gcs):
    main.handler(finalized(object_data(metadata=metadata)))
    assert_rejected(db, gcs, capsys, "no_uploader")


def test_rejecting_an_object_already_deleted_is_not_an_error(capsys, gcs):
    blob(gcs).delete.side_effect = exceptions.NotFound("gone")
    main.handler(finalized(object_data(name="fox.jpg")))
    assert last_log(capsys)["severity"] == "WARNING"


# ---- Failures are retried ----


def test_firestore_failure_is_raised_so_eventarc_retries(db):
    doc(db).set.side_effect = RuntimeError("unavailable")
    with pytest.raises(RuntimeError):
        main.handler(finalized(object_data()))
