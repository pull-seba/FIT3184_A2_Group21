"""Tests mock every cloud client; nothing here touches the shared project."""

import base64
import json
from datetime import datetime, timedelta, timezone
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

SHA = "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
SIGNER = "fn-upload-init@test-project.iam.gserviceaccount.com"


def gateway_headers(sub="test-user", email="test@example.com"):
    """What API Gateway adds after it verifies a Cognito ID token."""
    raw = json.dumps({"sub": sub, "email": email}).encode()
    return {
        "X-Apigateway-Api-Userinfo": base64.urlsafe_b64encode(raw)
        .decode()
        .rstrip("=")
    }


def call(json_body=None, headers=None, data=None):
    with app.test_request_context(
        method="POST", json=json_body, data=data, headers=headers or {}
    ):
        body, status, _ = main.handler(flask.request)
        return json.loads(body), status


def init_body(**overrides):
    body = {
        "sha256": SHA,
        "filename": "fox-cam3.jpg",
        "content_type": "image/jpeg",
        "size_bytes": 2483021,
        "is_public": True,
    }
    body.update(overrides)
    return body


def fake_generate_signed_url(**kwargs):
    """Like the real library, adds Host to the headers dict it's given."""
    if kwargs.get("headers") is not None:
        kwargs["headers"]["Host"] = "storage.googleapis.com"
    return "https://signed.example"


@pytest.fixture(autouse=True)
def clouds(monkeypatch):
    """Fresh fakes for every test: Firestore has no record and every signed URL is a fixed string."""
    db, gcs = mock.Mock(), mock.Mock()
    db.collection.return_value.document.return_value.get.return_value = (
        mock.Mock(exists=False)
    )
    gcs.bucket.return_value.blob.return_value.generate_signed_url.side_effect = fake_generate_signed_url
    monkeypatch.setattr(main, "db", db)
    monkeypatch.setattr(main, "gcs", gcs)
    monkeypatch.setattr(
        main,
        "credentials",
        mock.Mock(valid=True, service_account_email=SIGNER, token="tok"),
    )
    return db, gcs


def stored_record(db, data):
    db.collection.return_value.document.return_value.get.return_value = (
        mock.Mock(exists=True, to_dict=lambda: data)
    )


def signing_calls(gcs):
    """(bucket, key, kwargs) for every URL signed, in order."""
    buckets = [c.args[0] for c in gcs.bucket.call_args_list]
    keys = [c.args[0] for c in gcs.bucket.return_value.blob.call_args_list]
    kwargs = [
        c.kwargs
        for c in gcs.bucket.return_value.blob.return_value.generate_signed_url.call_args_list
    ]
    return list(zip(buckets, keys, kwargs))


VERIFIED = {
    "media_bucket": "ecoguard-g21-media",
    "media_key": f"{SHA}.jpg",
    "status": "active",
    "file_type": "image",
    "tags": {"fox": 2},
    "uploaded_at": datetime(2026, 10, 26, 9, 43, tzinfo=timezone.utc),
}


# ---- Requests that never reach Firestore ----


def test_rejects_request_without_gateway_claims():
    _, status = call(init_body())
    assert status == 401


def test_rejects_body_that_is_not_json():
    _, status = call(data="not json", headers=gateway_headers())
    assert status == 400


@pytest.mark.parametrize(
    "sha256", [SHA[:-1], SHA.upper(), "z" * 64, 12345, None]
)
def test_rejects_bad_hash(sha256, clouds):
    body, status = call(init_body(sha256=sha256), headers=gateway_headers())
    assert status == 400 and body["error"]["code"] == "bad_hash"
    clouds[0].collection.assert_not_called()


@pytest.mark.parametrize(
    "content_type", ["image/heic", "image/gif", "application/pdf"]
)
def test_rejects_unaccepted_type(content_type):
    body, status = call(
        init_body(content_type=content_type), headers=gateway_headers()
    )
    assert status == 415 and body["error"]["code"] == "unsupported_type"


def test_rejects_image_over_20_mb():
    body, status = call(
        init_body(size_bytes=20 * main.MB + 1), headers=gateway_headers()
    )
    assert status == 413 and body["error"]["code"] == "too_large"


def test_accepts_video_over_20_mb_within_its_200_mb_limit():
    body, status = call(
        init_body(content_type="video/mp4", size_bytes=150 * main.MB),
        headers=gateway_headers(),
    )
    assert status == 200 and body["status"] == "upload"


@pytest.mark.parametrize("size", [0, -1, "2483021", 1.5, True])
def test_rejects_bad_size(size):
    _, status = call(init_body(size_bytes=size), headers=gateway_headers())
    assert status == 400


@pytest.mark.parametrize("filename", ["", "   ", None, "a" * 256])
def test_rejects_bad_filename(filename):
    _, status = call(init_body(filename=filename), headers=gateway_headers())
    assert status == 400


def test_rejects_is_public_that_is_not_boolean():
    _, status = call(init_body(is_public="yes"), headers=gateway_headers())
    assert status == 400


# ---- New files get a signed PUT URL ----


def test_new_file_gets_signed_put_url_with_contract_headers(clouds):
    body, status = call(
        init_body(), headers=gateway_headers(sub="cognito-sub-1")
    )

    assert status == 200
    assert body["status"] == "upload" and body["file_id"] == SHA
    assert body["upload_url"] == "https://signed.example"
    assert body["headers"] == {
        "Content-Type": "image/jpeg",
        "x-goog-if-generation-match": "0",
        "x-goog-meta-uploaded-by": "cognito-sub-1",
        "x-goog-meta-original-filename": "fox-cam3.jpg",
        "x-goog-meta-is-public": "true",
    }
    expires = datetime.strptime(
        body["expires_at"], "%Y-%m-%dT%H:%M:%SZ"
    ).replace(tzinfo=timezone.utc)
    assert (
        timedelta(minutes=14)
        < expires - datetime.now(timezone.utc)
        <= timedelta(minutes=15)
    )

    [(bucket, key, kwargs)] = signing_calls(clouds[1])
    assert (bucket, key) == ("ecoguard-g21-media", f"{SHA}.jpg")
    assert kwargs["version"] == "v4" and kwargs["method"] == "PUT"
    assert kwargs["expiration"] == timedelta(minutes=15)
    assert kwargs["content_type"] == "image/jpeg"
    # Everything the browser is told to send, apart from Content-Type, is part of the signature
    # (the fake adds Host to its own copy, as the real library does).
    signed = {k: v for k, v in kwargs["headers"].items() if k != "Host"}
    assert signed == {
        k: v for k, v in body["headers"].items() if k != "Content-Type"
    }
    assert (
        kwargs["service_account_email"] == SIGNER
        and kwargs["access_token"] == "tok"
    )


def test_uploader_comes_from_the_token_never_the_body():
    body, _ = call(
        init_body(uploaded_by="someone-else"),
        headers=gateway_headers(sub="real-user"),
    )
    assert body["headers"]["x-goog-meta-uploaded-by"] == "real-user"


@pytest.mark.parametrize(
    "filename, encoded",
    [
        ("my fox (1).jpg", "my%20fox%20%281%29.jpg"),
        ("café.jpg", "caf%C3%A9.jpg"),
        ("a/b.jpg", "a%2Fb.jpg"),
    ],
)
def test_original_filename_is_url_encoded(filename, encoded):
    body, _ = call(init_body(filename=filename), headers=gateway_headers())
    assert body["headers"]["x-goog-meta-original-filename"] == encoded


def test_private_upload_is_signed_as_not_public():
    body, _ = call(init_body(is_public=False), headers=gateway_headers())
    assert body["headers"]["x-goog-meta-is-public"] == "false"


def test_is_public_defaults_to_true():
    request = init_body()
    del request["is_public"]
    body, _ = call(request, headers=gateway_headers())
    assert body["headers"]["x-goog-meta-is-public"] == "true"


@pytest.mark.parametrize(
    "content_type, ext",
    [
        ("image/png", "png"),
        ("image/webp", "webp"),
        ("video/mp4", "mp4"),
        ("video/quicktime", "mov"),
    ],
)
def test_key_extension_follows_content_type_not_filename(
    content_type, ext, clouds
):
    call(
        init_body(content_type=content_type, filename="looks-like.jpg"),
        headers=gateway_headers(),
    )
    [(_, key, _)] = signing_calls(clouds[1])
    assert key == f"{SHA}.{ext}"


def test_refreshes_credentials_before_signing(clouds, monkeypatch):
    stale = mock.Mock(valid=False, service_account_email=SIGNER, token="tok")
    monkeypatch.setattr(main, "credentials", stale)
    call(init_body(), headers=gateway_headers())
    stale.refresh.assert_called_once()


# ---- Duplicates ----


def test_verified_active_record_is_a_duplicate(clouds):
    stored_record(clouds[0], {**VERIFIED, "thumbnail_key": f"thumbs/{SHA}.jpg"})
    body, status = call(
        init_body(filename="renamed.jpg"), headers=gateway_headers()
    )

    assert status == 200 and body["status"] == "duplicate"
    assert body["file"] == {
        "file_id": SHA,
        "file_type": "image",
        "url": "https://signed.example",
        "thumbnail_url": "https://signed.example",
        "tags": {"fox": 2},
        "uploaded_at": "2026-10-26T09:43:00Z",
    }
    clouds[0].collection.assert_called_with("files")
    clouds[0].collection.return_value.document.assert_called_with(SHA)
    # Only GET links for the existing original and thumbnail: no upload URL, so no trigger can fire.
    calls = signing_calls(clouds[1])
    assert [(b, k, kw["method"]) for b, k, kw in calls] == [
        ("ecoguard-g21-media", f"{SHA}.jpg", "GET"),
        ("ecoguard-g21-derived", f"thumbs/{SHA}.jpg", "GET"),
    ]
    assert all(kw["expiration"] == timedelta(minutes=60) for _, _, kw in calls)


def test_duplicate_before_its_thumbnail_exists_has_no_thumbnail_url(clouds):
    stored_record(clouds[0], VERIFIED)
    body, _ = call(init_body(), headers=gateway_headers())
    assert (
        body["status"] == "duplicate" and body["file"]["thumbnail_url"] is None
    )


def test_document_from_tagging_alone_is_not_a_duplicate(clouds):
    stored_record(
        clouds[0], {"tags": {"fox": 1}, "model_version": "yolo-1"}
    )  # no media_key
    body, _ = call(init_body(), headers=gateway_headers())
    assert body["status"] == "upload"


def test_file_being_deleted_is_not_a_duplicate(clouds):
    stored_record(clouds[0], {**VERIFIED, "status": "deleting"})
    body, _ = call(init_body(), headers=gateway_headers())
    assert body["status"] == "upload"


# ---- Failures ----


def test_firestore_failure_returns_500_in_the_error_shape(clouds, capsys):
    clouds[
        0
    ].collection.return_value.document.return_value.get.side_effect = (
        RuntimeError("unavailable")
    )
    body, status = call(init_body(), headers=gateway_headers())
    assert status == 500 and body["error"]["code"] == "internal"
    logged = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert logged["severity"] == "ERROR" and logged["file_id"] == SHA
