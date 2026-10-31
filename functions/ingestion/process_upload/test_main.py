"""Tests mock every cloud client; nothing here touches the shared project.
The images and videos are real, drawn with OpenCV, so thumbnails and frames
are actually decoded and checked."""

import hashlib
import json
import tempfile
from pathlib import Path
from unittest import mock

import cv2
import numpy as np
import pytest
from cloudevents.http import CloudEvent
from google.api_core import exceptions
from google.cloud import firestore

from ecoguard_common.uploads import MB

with (
    mock.patch("google.cloud.firestore.Client"),
    mock.patch("google.cloud.storage.Client"),
    mock.patch("google.cloud.pubsub_v1.PublisherClient"),
):
    import main

BUCKET = "ecoguard-g21-media"
DERIVED = "ecoguard-g21-derived"
GENERATION = "1761471780000000"


def image_bytes(width, height, extension="jpg"):
    image = np.full((height, width, 3), (30, 110, 230), np.uint8)
    return cv2.imencode(f".{extension}", image)[1].tobytes()


def video_bytes(seconds, size=(160, 90)):
    """An MP4 at 1 frame per second; frame t is filled with grey level 4t,
    so a frame's brightness says which second it came from."""
    with tempfile.TemporaryDirectory() as folder:
        path = str(Path(folder) / "clip.mp4")
        writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), 1, size)
        for second in range(seconds):
            writer.write(np.full((size[1], size[0], 3), 4 * second, np.uint8))
        writer.release()
        return Path(path).read_bytes()


def sha(content):
    return hashlib.sha256(content).hexdigest()


CONTENT = image_bytes(1600, 1200)  # fox-cam3.jpg
SHA = sha(CONTENT)


def object_data(content=CONTENT, extension="jpg", **overrides):
    """The Cloud Storage object an Eventarc finalized event carries, as upload_init's URL creates it."""
    data = {
        "bucket": BUCKET,
        "name": f"{sha(content)}.{extension}",
        "generation": GENERATION,
        "contentType": "image/jpeg",
        "size": str(len(content)),
        "metadata": {
            "uploaded-by": "cognito-sub-1",
            "original-filename": "fox%20cam%283%29.jpg",
            "is-public": "true",
        },
    }
    data.update(overrides)
    return data


def video_data(content, extension="mp4", content_type="video/mp4", **overrides):
    return object_data(
        content, extension, contentType=content_type, **overrides
    )


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
    """A fresh Storage fake for every test. The media object holds CONTENT;
    whatever is saved to the derived bucket lands in gcs.saved, by key."""
    gcs = mock.Mock(saved={})
    media, derived = mock.Mock(), mock.Mock()
    gcs.bucket.side_effect = {BUCKET: media, DERIVED: derived}.get
    stored(gcs, CONTENT)

    def derived_blob(key):
        def upload(data, content_type):
            gcs.saved[key] = (data, content_type)

        return mock.Mock(upload_from_string=upload)

    derived.blob.side_effect = derived_blob
    monkeypatch.setattr(main, "gcs", gcs)
    return gcs


@pytest.fixture(autouse=True)
def publisher(monkeypatch):
    publisher = mock.Mock()
    monkeypatch.setattr(main, "publisher", publisher)
    return publisher


def stored(gcs, content):
    """Makes the media object hold these bytes."""
    blob(gcs).download_to_filename.side_effect = lambda path, **kwargs: Path(
        path
    ).write_bytes(content)


def doc(db):
    return db.collection.return_value.document.return_value


def blob(gcs):
    return gcs.bucket(BUCKET).blob.return_value


def stored_record(db, data):
    doc(db).get.return_value = mock.Mock(to_dict=lambda: data)


def writes(db):
    """Every document merge, in order."""
    for call in doc(db).set.call_args_list:
        assert call.kwargs == {"merge": True}
    return [call.args[0] for call in doc(db).set.call_args_list]


def decoded(data):
    return cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)


def published(publisher):
    topic, data = publisher.publish.call_args.args
    assert topic == "projects/ecoguard-g21/topics/frames-ready"
    return json.loads(data)


def last_log(capsys):
    return json.loads(capsys.readouterr().out.strip().splitlines()[-1])


# ---- A valid upload gets its base record ----


def test_verified_image_gets_its_base_record(db, gcs):
    main.handler(finalized(object_data()))

    db.collection.assert_called_with("files")
    db.collection.return_value.document.assert_called_with(SHA)
    assert writes(db)[0] == {
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
    }
    blob(gcs).delete.assert_not_called()


def test_reads_exactly_the_generation_that_fired_the_event(gcs):
    main.handler(finalized(object_data()))
    gcs.bucket(BUCKET).blob.assert_called_with(
        f"{SHA}.jpg", generation=int(GENERATION)
    )
    _, kwargs = blob(gcs).download_to_filename.call_args
    assert kwargs == {"raw_download": True}  # the stored bytes, as hashed


def test_video_is_recorded_as_a_video(db, gcs):
    content = video_bytes(5)
    stored(gcs, content)
    main.handler(finalized(video_data(content)))
    base = writes(db)[0]
    assert base["file_type"] == "video"
    assert base["media_key"] == f"{sha(content)}.mp4"


@pytest.mark.parametrize(
    "value, expected", [("true", True), ("false", False), ("yes", False)]
)
def test_is_public_comes_from_the_object_metadata(value, expected, db):
    data = object_data()
    data["metadata"]["is-public"] = value
    main.handler(finalized(data))
    assert writes(db)[0]["is_public"] is expected


def test_is_public_defaults_to_true(db):
    data = object_data()
    del data["metadata"]["is-public"]
    main.handler(finalized(data))
    assert writes(db)[0]["is_public"] is True


def test_document_from_tagging_alone_still_gets_its_base_record(db):
    stored_record(db, {"tags": {"fox": 1}, "pipeline": {"tagging": "done"}})
    main.handler(finalized(object_data()))
    # writes() checks every write merges, which keeps the tags already there
    assert writes(db)[0]["status"] == "active"


# ---- Images get a thumbnail (rubric 2.1.2) ----


@pytest.mark.parametrize(
    "width, height, thumbnail_size",
    [
        (1600, 1200, (320, 240)),
        (1200, 1600, (240, 320)),
        (1920, 1080, (320, 180)),
    ],
)
def test_thumbnail_is_320_on_the_longest_side_with_the_aspect_ratio_kept(
    width, height, thumbnail_size, db, gcs
):
    content = image_bytes(width, height)
    stored(gcs, content)
    main.handler(finalized(object_data(content)))

    data, content_type = gcs.saved[f"thumbs/{sha(content)}.jpg"]
    assert content_type == "image/jpeg"
    thumbnail_height, thumbnail_width = decoded(data).shape[:2]
    assert (thumbnail_width, thumbnail_height) == thumbnail_size


def test_thumbnail_is_compressed(gcs):
    main.handler(finalized(object_data()))
    data, _ = gcs.saved[f"thumbs/{SHA}.jpg"]
    assert len(data) < len(CONTENT)


def test_record_gets_the_thumbnail_key_and_address_after_the_base(db):
    main.handler(finalized(object_data()))
    assert writes(db)[1] == {
        "thumbnail_key": f"thumbs/{SHA}.jpg",
        "thumbnail_uri": f"gs://{DERIVED}/thumbs/{SHA}.jpg",
        "pipeline": {"thumbnail": "done"},
    }


@pytest.mark.parametrize(
    "extension, content_type", [("png", "image/png"), ("webp", "image/webp")]
)
def test_png_and_webp_get_jpeg_thumbnails(extension, content_type, db, gcs):
    content = image_bytes(800, 600, extension)
    stored(gcs, content)
    main.handler(
        finalized(object_data(content, extension, contentType=content_type))
    )
    data, _ = gcs.saved[f"thumbs/{sha(content)}.jpg"]
    assert data[:2] == b"\xff\xd8"  # a JPEG
    assert decoded(data).shape[:2] == (240, 320)


def test_image_opencv_cannot_decode_is_recorded_as_failed(capsys, db, gcs):
    content = b"not really a jpeg"
    stored(gcs, content)
    main.handler(finalized(object_data(content)))
    assert gcs.saved == {}
    assert writes(db)[1] == {"pipeline": {"thumbnail": "failed"}}
    assert last_log(capsys)["thumbnail"] == "failed"


def test_nothing_is_written_to_the_media_bucket(gcs):
    # Only the media bucket has triggers: a thumbnail there would fire this
    # function again.
    main.handler(finalized(object_data()))
    gcs.bucket(BUCKET).blob.return_value.upload_from_string.assert_not_called()


# ---- Videos get a frame every 10 s, a poster and frames-ready ----


@pytest.mark.parametrize(
    "seconds, frame_count", [(60, 6), (61, 7), (25, 3), (10, 1), (7, 1)]
)
def test_one_frame_every_10_seconds(seconds, frame_count, gcs):
    content = video_bytes(seconds)
    stored(gcs, content)
    main.handler(finalized(video_data(content)))
    frames = [key for key in gcs.saved if key.startswith("frames/")]
    assert len(frames) == frame_count


def test_frames_are_taken_at_0_10_20_seconds(gcs):
    content = video_bytes(60)
    stored(gcs, content)
    main.handler(finalized(video_data(content)))
    for index in range(6):
        data, _ = gcs.saved[f"frames/{sha(content)}/{index:04d}.jpg"]
        # Frame t has grey level 4t, so the frame at 10i s has about 40i.
        assert decoded(data).mean() == pytest.approx(40 * index, abs=6)


def test_video_record_gets_frames_poster_and_duration(db, gcs):
    content = video_bytes(25)
    stored(gcs, content)
    main.handler(finalized(video_data(content)))
    file_id = sha(content)
    frame_keys = [f"frames/{file_id}/{i:04d}.jpg" for i in range(3)]
    assert writes(db)[1] == {
        "thumbnail_key": f"thumbs/{file_id}.jpg",
        "thumbnail_uri": f"gs://{DERIVED}/thumbs/{file_id}.jpg",
        "frame_keys": frame_keys,
        "duration_s": 25.0,
        "pipeline": {"thumbnail": "done", "frames": "done"},
    }
    poster, _ = gcs.saved[f"thumbs/{file_id}.jpg"]
    assert decoded(poster).shape[:2] == (180, 320)  # 160x90 scaled up
    assert decoded(poster).mean() == pytest.approx(0, abs=6)  # frame 0


def test_mov_videos_get_frames_too(db, gcs):
    content = video_bytes(12)
    stored(gcs, content)
    main.handler(finalized(video_data(content, "mov", "video/quicktime")))
    assert writes(db)[1]["pipeline"] == {"thumbnail": "done", "frames": "done"}


def test_frames_ready_is_published_as_events_md_says(gcs, publisher):
    content = video_bytes(14)
    stored(gcs, content)
    main.handler(finalized(video_data(content)))
    file_id = sha(content)
    assert published(publisher) == {
        "file_id": file_id,
        "bucket": DERIVED,
        "frame_keys": [
            f"frames/{file_id}/0000.jpg",
            f"frames/{file_id}/0001.jpg",
        ],
        "duration_s": 14.0,
    }
    publisher.publish.return_value.result.assert_called_once()


def test_images_publish_nothing(publisher):
    main.handler(finalized(object_data()))
    publisher.publish.assert_not_called()


def test_failed_publish_raises_and_leaves_frames_unfinished(db, gcs, publisher):
    content = video_bytes(5)
    stored(gcs, content)
    publisher.publish.return_value.result.side_effect = RuntimeError("down")
    with pytest.raises(RuntimeError):
        main.handler(finalized(video_data(content)))
    # Only the base record: the retry makes the frames and publishes again.
    assert len(writes(db)) == 1


def test_video_opencv_cannot_decode_is_recorded_as_failed(db, gcs, publisher):
    content = b"not really an mp4"
    stored(gcs, content)
    main.handler(finalized(video_data(content)))
    assert gcs.saved == {}
    publisher.publish.assert_not_called()
    assert writes(db)[1] == {
        "pipeline": {"thumbnail": "failed", "frames": "failed"}
    }


# ---- Repeat events change nothing ----


def test_repeat_event_for_a_processed_image_does_nothing(capsys, db, gcs):
    stored_record(
        db,
        {
            "media_key": f"{SHA}.jpg",
            "status": "active",
            "pipeline": {"thumbnail": "done"},
        },
    )
    main.handler(finalized(object_data()))
    blob(gcs).download_to_filename.assert_not_called()  # no second download
    doc(db).set.assert_not_called()  # uploaded_at keeps its first value
    blob(gcs).delete.assert_not_called()
    assert last_log(capsys)["severity"] == "INFO"


def test_repeat_event_for_a_processed_video_publishes_nothing(db, publisher):
    stored_record(
        db,
        {
            "media_key": f"{SHA}.mp4",
            "status": "active",
            "pipeline": {"thumbnail": "done", "frames": "failed"},
        },
    )
    main.handler(finalized(video_data(CONTENT, name=f"{SHA}.mp4")))
    publisher.publish.assert_not_called()
    doc(db).set.assert_not_called()


def test_retry_after_the_base_record_makes_only_the_thumbnail(db, gcs):
    # An earlier delivery verified the file, then failed before its thumbnail.
    stored_record(db, {"media_key": f"{SHA}.jpg", "status": "active"})
    main.handler(finalized(object_data()))
    (fields,) = writes(db)  # no second base record, so uploaded_at stays
    assert fields["pipeline"] == {"thumbnail": "done"}
    assert f"thumbs/{SHA}.jpg" in gcs.saved


def test_same_bytes_under_another_type_are_deleted_as_a_duplicate(
    capsys, db, gcs
):
    stored_record(db, {"media_key": f"{SHA}.jpg", "status": "active"})
    main.handler(
        finalized(object_data(extension="png", contentType="image/png"))
    )
    blob(gcs).delete.assert_called_once_with()
    doc(db).set.assert_not_called()
    assert last_log(capsys)["reason"] == "duplicate"


def test_file_being_deleted_is_processed_as_new(db):
    stored_record(db, {"media_key": f"{SHA}.jpg", "status": "deleting"})
    main.handler(finalized(object_data()))
    assert writes(db)[0]["status"] == "active"


def test_object_deleted_before_processing_writes_nothing(db, gcs):
    blob(gcs).download_to_filename.side_effect = exceptions.NotFound("gone")
    main.handler(finalized(object_data()))
    doc(db).set.assert_not_called()


# ---- Anything that isn't a valid upload is deleted, with no record ----


def assert_rejected(db, gcs, capsys, reason):
    blob(gcs).delete.assert_called_once_with()
    doc(db).set.assert_not_called()
    assert gcs.saved == {}
    logged = last_log(capsys)
    assert logged["severity"] == "WARNING" and logged["reason"] == reason


def test_hash_mismatch_deletes_the_object(capsys, db, gcs):
    other = sha(b"different bytes")
    main.handler(finalized(object_data(name=f"{other}.jpg")))
    assert_rejected(db, gcs, capsys, "hash_mismatch")


@pytest.mark.parametrize(
    "name",
    ["fox.jpg", f"{SHA.upper()}.jpg", f"{SHA}.jpg.exe", f"thumbs/{SHA}.jpg"],
)
def test_key_that_is_not_a_file_id_is_deleted_unread(name, capsys, db, gcs):
    main.handler(finalized(object_data(name=name)))
    assert_rejected(db, gcs, capsys, "bad_key")
    blob(gcs).download_to_filename.assert_not_called()
    db.collection.assert_not_called()


@pytest.mark.parametrize(
    "extension, content_type",
    [
        ("jpg", "image/heic"),  # not accepted
        ("jpg", "image/png"),  # type doesn't match the extension
        ("gif", "image/gif"),
        ("jpg", None),
    ],
)
def test_wrong_or_unaccepted_type_is_deleted(
    extension, content_type, capsys, db, gcs
):
    data = object_data(extension=extension, contentType=content_type)
    main.handler(finalized(data))
    assert_rejected(db, gcs, capsys, "bad_type")


def test_image_over_20_mb_is_deleted_without_downloading(capsys, db, gcs):
    # The browser can claim any size to upload_init; the stored size is the real one.
    main.handler(finalized(object_data(size=str(20 * MB + 1))))
    assert_rejected(db, gcs, capsys, "too_large")
    blob(gcs).download_to_filename.assert_not_called()


def test_video_over_20_mb_within_its_200_mb_limit_is_accepted(db, gcs):
    content = video_bytes(3)
    stored(gcs, content)
    main.handler(
        finalized(
            video_data(content, "mov", "video/quicktime", size=str(150 * MB))
        )
    )
    assert writes(db)[0]["status"] == "active"


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


def test_storage_failure_saving_a_thumbnail_is_raised(db, gcs):
    gcs.bucket(DERIVED).blob.side_effect = RuntimeError("unavailable")
    with pytest.raises(RuntimeError):
        main.handler(finalized(object_data()))
    assert len(writes(db)) == 1  # the retry makes the thumbnail
