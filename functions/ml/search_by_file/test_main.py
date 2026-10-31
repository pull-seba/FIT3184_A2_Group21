"""Tests mock every cloud client; nothing here touches the shared project or
calls Rekognition."""

import base64
import json
from datetime import datetime, timedelta, timezone
from unittest import mock

import flask
import pytest

from ecoguard_ml import BadImage, detect

with (
    mock.patch("google.cloud.firestore.Client"),
    mock.patch("google.cloud.storage.Client"),
    mock.patch(
        "google.auth.default", return_value=(mock.Mock(), "test-project")
    ),
):
    import main

app = flask.Flask(__name__)

PHOTO = b"pretend these are the bytes of a fox photo"
PHOTO_BASE64 = base64.b64encode(PHOTO).decode()
CONFIG = {"version": "2026-10-29.1", "detector": "rekognition"}
SIGNED = "https://signed.example"
UPLOADED = datetime(2026, 10, 26, 9, 43, tzinfo=timezone.utc)
MB = 1024 * 1024


def gateway_headers(sub="test-user", email="test@example.com"):
    """What API Gateway adds after it verifies a Cognito ID token."""
    raw = json.dumps({"sub": sub, "email": email}).encode()
    return {
        "X-Apigateway-Api-Userinfo": base64.urlsafe_b64encode(raw)
        .decode()
        .rstrip("=")
    }


def search_body(file_base64=PHOTO_BASE64, content_type="image/jpeg"):
    return {"file_base64": file_base64, "content_type": content_type}


def call(json_body=None, data=None, headers=None, method="POST"):
    """(parsed body or None, status, headers)."""
    if headers is None:
        headers = gateway_headers()
    with app.test_request_context(
        "/search/by-file",
        method=method,
        json=json_body,
        data=data,
        headers=headers,
    ):
        body, status, response_headers = main.handler(flask.request)
        return (json.loads(body) if body else None), status, response_headers


def record(tags, uploaded_at=UPLOADED, status="active"):
    return {
        "file_type": "image",
        "media_bucket": "ecoguard-g21-media",
        "media_key": "x.jpg",
        "thumbnail_key": "thumbs/x.jpg",
        "tags": tags,
        "uploaded_at": uploaded_at,
        "status": status,
    }


@pytest.fixture(autouse=True)
def clouds(monkeypatch):
    """Fresh Firestore and Storage fakes for every test."""
    db, gcs = mock.Mock(), mock.Mock()
    gcs.bucket.return_value.blob.return_value.generate_signed_url.return_value = SIGNED
    monkeypatch.setattr(main, "db", db)
    monkeypatch.setattr(main, "gcs", gcs)
    monkeypatch.setattr(
        main,
        "credentials",
        mock.Mock(valid=True, service_account_email="fn@test", token="tok"),
    )
    return db, gcs


@pytest.fixture
def db(clouds):
    return clouds[0]


@pytest.fixture
def gcs(clouds):
    return clouds[1]


@pytest.fixture(autouse=True)
def config(monkeypatch):
    monkeypatch.setattr(main, "model_config", mock.Mock(get=lambda: CONFIG))


@pytest.fixture(autouse=True)
def analyse(monkeypatch):
    """Rekognition replaced: every photo shows one fox."""
    analyse = mock.Mock(return_value=({"fox": 1}, []))
    monkeypatch.setattr(main.detect, "analyse", analyse)
    return analyse


def firestore_returns(db, **records_by_id):
    db.collection.return_value.where.return_value.stream.return_value = [
        mock.Mock(id=file_id, **{"to_dict.return_value": data})
        for file_id, data in records_by_id.items()
    ]


def narrowed_by(db):
    sent = db.collection.return_value.where.call_args.kwargs["filter"]
    return sent.field_path, sent.op_string, sent.value


def ids(body):
    return [result["file_id"] for result in body["results"]]


# ---------- gateway and CORS ----------


def test_rejects_request_without_gateway_claims(analyse):
    body, status, headers = call(search_body(), headers={})
    assert (status, body["error"]["code"]) == (401, "unauthenticated")
    assert headers["Access-Control-Allow-Origin"] == "*"
    analyse.assert_not_called()


def test_preflight_is_204_with_cors_headers_and_no_token():
    body, status, headers = call(method="OPTIONS", headers={})
    assert (body, status) == (None, 204)
    assert headers == {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, PUT, OPTIONS",
        "Access-Control-Allow-Headers": "Authorization, Content-Type",
    }


# ---------- bad input, rejected before detection or Firestore ----------


@pytest.mark.parametrize(
    "json_body, data, status, code",
    [
        (None, "not json", 400, "bad_json"),
        (["not", "an", "object"], None, 400, "bad_json"),
        ({"content_type": "image/jpeg"}, None, 400, "bad_file"),
        (search_body(file_base64=123), None, 400, "bad_file"),
        ({"file_base64": PHOTO_BASE64}, None, 400, "bad_content_type"),
        (search_body(file_base64="not base64!!"), None, 400, "bad_base64"),
        (search_body(content_type="video/mp4"), None, 415, "unsupported_type"),
        (search_body(content_type="image/heic"), None, 415, "unsupported_type"),
    ],
)
def test_bad_input_is_rejected_before_detection(
    json_body, data, status, code, analyse, db
):
    body, got_status, headers = call(json_body, data)
    assert (got_status, body["error"]["code"]) == (status, code)
    assert headers["Access-Control-Allow-Origin"] == "*"
    analyse.assert_not_called()
    db.collection.assert_not_called()


def test_photo_over_20_mb_is_413(analyse):
    too_big = base64.b64encode(b"\0" * (20 * MB + 1)).decode()
    body, status, _ = call(search_body(file_base64=too_big))
    assert (status, body["error"]["code"]) == (413, "too_large")
    analyse.assert_not_called()


def test_unreadable_image_is_400_bad_image(analyse, db):
    analyse.side_effect = BadImage("cannot identify image file")
    body, status, _ = call(search_body())
    assert (status, body["error"]["code"]) == (400, "bad_image")
    db.collection.assert_not_called()


def test_detector_failure_is_500(analyse):
    analyse.side_effect = RuntimeError("throttled")
    body, status, _ = call(search_body())
    assert (status, body["error"]["code"]) == (500, "internal")


# ---------- matching ----------


def test_photo_is_analysed_with_the_current_model_config(analyse):
    call(search_body())
    analyse.assert_called_once_with(PHOTO, CONFIG)


def test_matches_by_species_not_by_count(analyse, db):
    analyse.return_value = ({"fox": 2}, [])
    firestore_returns(db, one_fox=record({"fox": 1}))
    body, status, _ = call(search_body())
    assert status == 200
    assert body["detected_tags"] == {"fox": 2}  # the real count is reported
    assert ids(body) == ["one_fox"]  # but a file with one fox matches
    assert narrowed_by(db) == ("tags.fox", ">=", 1)


def test_every_detected_species_must_be_in_the_file(analyse, db):
    analyse.return_value = ({"fox": 1, "cat": 1}, [])
    firestore_returns(
        db,
        both=record({"fox": 1, "cat": 2}),
        fox_only=record({"fox": 3}),
        deleting=record({"fox": 1, "cat": 1}, status="deleting"),
        no_status=record({"fox": 1, "cat": 1}, status=None),
        untagged=record({}),
    )
    body, _, _ = call(search_body())
    assert ids(body) == ["both"]


def test_nothing_detected_returns_no_results_without_firestore(
    analyse, db, gcs
):
    analyse.return_value = ({}, [])
    body, status, _ = call(search_body())
    assert status == 200
    assert body == {"detected_tags": {}, "results": []}
    db.collection.assert_not_called()
    gcs.bucket.assert_not_called()


def test_results_are_newest_first_file_summaries(db):
    firestore_returns(
        db,
        older=record({"fox": 1}),
        newer=record({"fox": 1}, UPLOADED + timedelta(days=1)),
    )
    body, _, headers = call(search_body())
    assert ids(body) == ["newer", "older"]
    assert headers["Access-Control-Allow-Origin"] == "*"
    newest = body["results"][0]
    assert set(newest) == {
        "file_id",
        "file_type",
        "url",
        "thumbnail_url",
        "tags",
        "uploaded_at",
    }
    assert newest["url"] == SIGNED
    assert newest["thumbnail_url"] == SIGNED
    assert newest["uploaded_at"] == "2026-10-27T09:43:00Z"


# ---------- the query photo is never stored (rubric 2.2.3) ----------

# Every Firestore and Cloud Storage call that writes, deletes or copies.
WRITE_CALLS = {
    "set",
    "update",
    "delete",
    "create",
    "add",
    "batch",
    "bulk_writer",
    "transaction",
    "copy_blob",
}


def called_names(fake):
    """Each method name in a fake's calls: "collection().where().stream"
    gives collection, where and stream."""
    return {
        part.removesuffix("()")
        for name, _, _ in fake.mock_calls
        for part in name.split(".")
        if part
    }


def test_a_full_search_makes_no_write_to_firestore_or_storage(
    monkeypatch, db, gcs
):
    # config/model read through the fake database too, as when deployed.
    db.document.return_value.get.return_value = mock.Mock(
        exists=True, to_dict=lambda: CONFIG
    )
    monkeypatch.setattr(main, "model_config", detect.ModelConfig(db))
    firestore_returns(db, match=record({"fox": 1}))

    body, status, _ = call(search_body())
    assert (status, ids(body)) == (200, ["match"])

    names = called_names(db) | called_names(gcs)
    # The search really ran: config read, files queried, URLs signed.
    assert {"document", "stream", "generate_signed_url"} <= names
    written = {
        name
        for name in names
        if name in WRITE_CALLS or name.startswith("upload_from_")
    }
    assert written == set()
