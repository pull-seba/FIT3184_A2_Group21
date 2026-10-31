"""Tests mock every cloud client; nothing here touches the shared project."""

import base64
import json
from datetime import datetime
from unittest import mock
from zoneinfo import ZoneInfo

import flask
import pytest

with (
    mock.patch("google.cloud.firestore.Client"),
    mock.patch("google.cloud.storage.Client"),
    mock.patch(
        "google.auth.default", return_value=(mock.Mock(), "test-project")
    ),
):
    import main

app = flask.Flask(__name__)

SHA = "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
MEDIA = "ecoguard-g21-media"
DERIVED = "ecoguard-g21-derived"
# 8:43 pm in Melbourne (UTC+11 in daylight saving) is 9:43 am UTC.
UPLOADED = datetime(
    2026, 10, 27, 20, 43, tzinfo=ZoneInfo("Australia/Melbourne")
)


def gateway_headers(sub="test-user", email="test@example.com"):
    """What API Gateway adds after it verifies a Cognito ID token."""
    raw = json.dumps({"sub": sub, "email": email}).encode()
    return {
        "X-Apigateway-Api-Userinfo": base64.urlsafe_b64encode(raw)
        .decode()
        .rstrip("=")
    }


def call(file_id=SHA, headers=None, method="GET"):
    """The gateway passes the path's {file_id} as ?file_id=."""
    query = {} if file_id is None else {"file_id": file_id}
    with app.test_request_context(
        method=method, query_string=query, headers=headers or {}
    ):
        return main.handler(flask.request)


def get(file_id=SHA):
    body, status, _ = call(file_id, gateway_headers())
    return json.loads(body), status


def record(**overrides):
    """An active record as process_upload leaves it."""
    return {
        "file_id": SHA,
        "file_type": "image",
        "content_type": "image/jpeg",
        "media_bucket": MEDIA,
        "media_key": f"{SHA}.jpg",
        "media_uri": f"gs://{MEDIA}/{SHA}.jpg",
        "uploaded_by": "someone-else",
        "uploaded_at": UPLOADED,
        "is_public": True,
        "status": "active",
        **overrides,
    }


@pytest.fixture(autouse=True)
def db(monkeypatch):
    """A fresh Firestore fake for every test. Set db.record to give the file one."""
    db = mock.Mock()
    db.record = None
    db.collection.return_value.document.return_value.get.side_effect = lambda: (
        mock.Mock(to_dict=lambda: db.record)
    )
    monkeypatch.setattr(main, "db", db)
    return db


@pytest.fixture(autouse=True)
def gcs(monkeypatch):
    """A fresh Storage fake: each signed URL names its bucket and key, and
    gcs.signed lists (bucket, key, kwargs) for every URL signed."""
    gcs = mock.Mock()
    gcs.signed = []

    def bucket(name):
        def blob(key):
            def sign(**kwargs):
                gcs.signed.append((name, key, kwargs))
                return (
                    f"https://signed.example/{name}/{key}?X-Goog-Signature=abc"
                )

            return mock.Mock(generate_signed_url=mock.Mock(side_effect=sign))

        return mock.Mock(blob=mock.Mock(side_effect=blob))

    gcs.bucket.side_effect = bucket
    monkeypatch.setattr(main, "gcs", gcs)
    return gcs


# ---- Request checks ----


def test_rejects_request_without_gateway_claims():
    _, status, _ = call()
    assert status == 401


def test_answers_cors_preflight_without_a_token():
    body, status, headers = call(method="OPTIONS")
    assert (body, status) == ("", 204)
    assert headers["Access-Control-Allow-Origin"] == "*"
    assert "GET" in headers["Access-Control-Allow-Methods"]
    assert "Authorization" in headers["Access-Control-Allow-Headers"]


@pytest.mark.parametrize(
    "file_id",
    [None, "", SHA.upper(), SHA[:63], SHA + "0", "z" * 64, "../" + SHA[3:]],
)
def test_rejects_a_file_id_that_isnt_a_sha256(db, file_id):
    body, status = get(file_id)
    assert status == 400
    assert body["error"]["code"] == "bad_file_id"
    db.collection.assert_not_called()


@pytest.mark.parametrize(
    "kwargs",
    [
        {},  # 401
        {"file_id": "nope", "headers": gateway_headers()},  # 400
        {"headers": gateway_headers()},  # 404
    ],
)
def test_every_response_allows_the_app_origin(kwargs):
    _, _, headers = call(**kwargs)
    assert headers["Access-Control-Allow-Origin"] == "*"


# ---- Not found ----


@pytest.mark.parametrize(
    "stored",
    [
        None,  # never uploaded, or deleted
        record(status="deleting"),  # delete_files is removing it
        {"tags": {"fox": 1}, "pipeline": {"tagging": "done"}},  # tagging first
    ],
)
def test_only_an_active_record_is_found(db, stored):
    db.record = stored
    body, status = get()
    assert status == 404
    assert body == {"error": {"code": "not_found", "message": "No such file"}}


# ---- Found ----


def test_returns_the_file_summary_and_pipeline(db):
    db.record = record(
        thumbnail_key=f"thumbs/{SHA}.jpg",
        tags={"fox": 2},
        pipeline={"thumbnail": "done", "tagging": "done"},
    )
    body, status = get()
    assert status == 200
    assert body == {
        "file_id": SHA,
        "file_type": "image",
        "url": f"https://signed.example/{MEDIA}/{SHA}.jpg?X-Goog-Signature=abc",
        "thumbnail_url": f"https://signed.example/{DERIVED}/thumbs/{SHA}.jpg?X-Goog-Signature=abc",
        "tags": {"fox": 2},
        "uploaded_at": "2026-10-27T09:43:00Z",
        "pipeline": {"thumbnail": "done", "tagging": "done"},
    }


def test_shows_progress_before_processing_finishes(db):
    db.record = record()  # process_upload has verified it, nothing more yet
    body, _ = get()
    assert body["thumbnail_url"] is None
    assert body["tags"] == {}
    assert body["pipeline"] == {}


def test_video_shows_its_poster_and_frames_step(db):
    db.record = record(
        file_type="video",
        content_type="video/mp4",
        media_key=f"{SHA}.mp4",
        thumbnail_key=f"thumbs/{SHA}.jpg",
        pipeline={"thumbnail": "done", "frames": "done"},
    )
    body, _ = get()
    assert body["file_type"] == "video"
    assert body["url"].startswith(f"https://signed.example/{MEDIA}/{SHA}.mp4")
    assert body["thumbnail_url"].startswith(
        f"https://signed.example/{DERIVED}/thumbs/"
    )
    assert body["pipeline"] == {"thumbnail": "done", "frames": "done"}


def test_a_failed_step_is_reported(db):
    db.record = record(pipeline={"thumbnail": "failed"})
    body, _ = get()
    assert body["thumbnail_url"] is None
    assert body["pipeline"] == {"thumbnail": "failed"}


def test_any_signed_in_user_can_see_any_file(db):
    # Search shows every file to everyone, so reading one is not restricted.
    db.record = record(uploaded_by="the-uploader")
    _, status = get()
    assert status == 200


def test_signs_v4_get_urls_for_60_minutes_without_a_key_file(db, gcs):
    db.record = record(thumbnail_key=f"thumbs/{SHA}.jpg")
    get()
    assert [(bucket, key) for bucket, key, _ in gcs.signed] == [
        (MEDIA, f"{SHA}.jpg"),
        (DERIVED, f"thumbs/{SHA}.jpg"),
    ]
    for _, _, kwargs in gcs.signed:
        assert kwargs["version"] == "v4"
        assert kwargs["method"] == "GET"
        assert kwargs["expiration"].total_seconds() == 60 * 60
        assert (
            kwargs["service_account_email"]
            == main.credentials.service_account_email
        )
        assert kwargs["access_token"] == main.credentials.token


def test_refreshes_expired_credentials_before_signing(db, monkeypatch):
    credentials = mock.Mock(valid=False)
    monkeypatch.setattr(main, "credentials", credentials)
    db.record = record()
    get()
    credentials.refresh.assert_called_once()


def test_never_writes(db):
    db.record = record()
    get()
    document = db.collection.return_value.document.return_value
    document.set.assert_not_called()
    document.update.assert_not_called()
    document.delete.assert_not_called()


# ---- Failures ----


def test_firestore_failure_is_a_500_logged_with_the_file_id(db, capsys):
    db.collection.return_value.document.return_value.get.side_effect = (
        RuntimeError("Firestore is down")
    )
    body, status = get()
    assert status == 500
    assert body["error"]["code"] == "internal"
    line = json.loads(capsys.readouterr().out)
    assert line["severity"] == "ERROR"
    assert line["file_id"] == SHA


def test_signing_failure_is_a_500_and_logs_no_url(db, gcs, capsys):
    db.record = record()
    gcs.bucket.side_effect = RuntimeError("signing failed")
    _, status = get()
    assert status == 500
    assert "signed.example" not in capsys.readouterr().out
