import base64
import json
from unittest import mock

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

SIGNED = "https://signed.example"
FILE_ID = "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
SIGNED_THUMBNAIL_URL = (
    "https://storage.googleapis.com/ecoguard-g21-derived/thumbs/"
    f"{FILE_ID}.jpg?X-Goog-Algorithm=GOOG4-RSA-SHA256&X-Goog-Signature=abc"
)


def gateway_headers(sub="test-user", email="test@example.com"):
    raw = json.dumps({"sub": sub, "email": email}).encode()
    return {
        "X-Apigateway-Api-Userinfo": base64.urlsafe_b64encode(raw)
        .decode()
        .rstrip("=")
    }


def call(json_body=None, data=None, headers=None):
    if headers is None:
        headers = gateway_headers()
    with app.test_request_context(
        "/search/thumbnail",
        method="POST",
        json=json_body,
        data=data,
        headers=headers,
    ):
        body, status, _ = main.handler(flask.request)
        return json.loads(body), status


def record(media_key=f"{FILE_ID}.jpg", file_type="image", status="active"):
    return {
        "file_type": file_type,
        "media_bucket": "ecoguard-g21-media",
        "media_key": media_key,
        "thumbnail_key": f"thumbs/{FILE_ID}.jpg",
        "status": status,
    }


@pytest.fixture(autouse=True)
def clouds(monkeypatch):
    db, gcs = mock.Mock(), mock.Mock()
    gcs.bucket.return_value.blob.return_value.generate_signed_url.return_value = SIGNED
    monkeypatch.setattr(main, "db", db)
    monkeypatch.setattr(main, "gcs", gcs)
    monkeypatch.setattr(
        main,
        "credentials",
        mock.Mock(valid=True, service_account_email="fn@test", token="tok"),
    )
    return db


def firestore_returns(db, stored):
    document = db.collection.return_value.document
    document.return_value.get.return_value.to_dict.return_value = stored


def signed_key():
    return main.gcs.bucket.return_value.blob.call_args.args[0]


def test_answers_cors_preflight_without_a_token():
    with app.test_request_context("/search/thumbnail", method="OPTIONS"):
        body, status, headers = main.handler(flask.request)
    assert (body, status) == ("", 204)
    assert headers["Access-Control-Allow-Origin"] == "*"
    assert "POST" in headers["Access-Control-Allow-Methods"]
    assert "Authorization" in headers["Access-Control-Allow-Headers"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"json": {"thumbnail_url": SIGNED_THUMBNAIL_URL}},  # 401
        {"data": "not json", "headers": gateway_headers()},  # 400
        {
            "json": {"thumbnail_url": SIGNED_THUMBNAIL_URL},
            "headers": gateway_headers(),
        },  # 200
    ],
)
def test_every_response_allows_the_app_origin(clouds, kwargs):
    firestore_returns(clouds, record())
    with app.test_request_context("/search/thumbnail", method="POST", **kwargs):
        _, _, headers = main.handler(flask.request)
    assert headers["Access-Control-Allow-Origin"] == "*"


def test_rejects_request_without_gateway_claims():
    _, status = call({"thumbnail_url": SIGNED_THUMBNAIL_URL}, headers={})
    assert status == 401


@pytest.mark.parametrize(
    "json_body, data, code",
    [
        (None, "not json", "bad_json"),
        ([SIGNED_THUMBNAIL_URL], None, "bad_json"),
        ({}, None, "bad_url"),
        ({"thumbnail_url": 7}, None, "bad_url"),
    ],
)
def test_bad_input_is_400_before_firestore(clouds, json_body, data, code):
    body, status = call(json_body, data)
    assert (status, body["error"]["code"]) == (400, code)
    clouds.collection.assert_not_called()


@pytest.mark.parametrize("extension", ["jpg", "png", "webp"])
def test_signed_thumbnail_url_gives_the_original(clouds, extension):
    firestore_returns(clouds, record(f"{FILE_ID}.{extension}"))
    body, status = call({"thumbnail_url": SIGNED_THUMBNAIL_URL})
    assert status == 200
    assert body == {"file_id": FILE_ID, "file_type": "image", "url": SIGNED}
    clouds.collection.return_value.document.assert_called_once_with(FILE_ID)
    main.gcs.bucket.assert_called_once_with("ecoguard-g21-media")
    assert signed_key() == f"{FILE_ID}.{extension}"


def test_video_poster_gives_the_video(clouds):
    firestore_returns(clouds, record(f"{FILE_ID}.mp4", file_type="video"))
    body, _ = call({"thumbnail_url": SIGNED_THUMBNAIL_URL})
    assert body["file_type"] == "video"
    assert signed_key() == f"{FILE_ID}.mp4"


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/cat.jpg",
        f"https://storage.googleapis.com/other-bucket/thumbs/{FILE_ID}.jpg",
    ],
    ids=["not cloud storage", "not our bucket"],
)
def test_url_that_is_not_ours_is_404(clouds, url):
    body, status = call({"thumbnail_url": url})
    assert (status, body["error"]["code"]) == (404, "not_found")
    clouds.collection.assert_not_called()


@pytest.mark.parametrize(
    "stored",
    [None, record(status="deleting"), {"tags": {"fox": 1}}],
    ids=["missing", "deleting", "tagged before its upload record"],
)
def test_missing_or_inactive_file_is_404(clouds, stored):
    firestore_returns(clouds, stored)
    body, status = call({"thumbnail_url": SIGNED_THUMBNAIL_URL})
    assert (status, body["error"]["code"]) == (404, "not_found")
    main.gcs.bucket.assert_not_called()


def test_firestore_failure_is_500(clouds):
    clouds.collection.return_value.document.return_value.get.side_effect = (
        RuntimeError("unavailable")
    )
    _, status = call({"thumbnail_url": SIGNED_THUMBNAIL_URL})
    assert status == 500
