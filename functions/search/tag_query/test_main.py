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

SIGNED = "https://signed.example"
UPLOADED = datetime(2026, 10, 26, 9, 43, tzinfo=timezone.utc)


def gateway_headers(sub="test-user", email="test@example.com"):
    """What API Gateway adds after it verifies a Cognito ID token."""
    raw = json.dumps({"sub": sub, "email": email}).encode()
    return {
        "X-Apigateway-Api-Userinfo": base64.urlsafe_b64encode(raw)
        .decode()
        .rstrip("=")
    }


def call(
    method="POST", path="/search/tags", json_body=None, data=None, headers=None
):
    if headers is None:
        headers = gateway_headers()
    with app.test_request_context(
        path, method=method, json=json_body, data=data, headers=headers
    ):
        body, status, _ = main.handler(flask.request)
        return json.loads(body), status


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
    """Fresh fakes for every test: every signed URL is a fixed string."""
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


def stored(db, **records):
    """What Firestore returns for the one-tag query, keyed by file ID."""
    db.collection.return_value.where.return_value.stream.return_value = [
        mock.Mock(id=file_id, **{"to_dict.return_value": data})
        for file_id, data in records.items()
    ]


def narrowed_by(db):
    """(field, operator, value) of the filter tag_query sent to Firestore."""
    found = db.collection.return_value.where.call_args.kwargs["filter"]
    return found.field_path, found.op_string, found.value


def ids(body):
    return [result["file_id"] for result in body["results"]]


def test_rejects_request_without_gateway_claims():
    _, status = call(json_body={"fox": 1}, headers={})
    assert status == 401


@pytest.mark.parametrize(
    "method, path, json_body, data, code",
    [
        ("POST", "/search/tags", None, "not json", "bad_json"),
        ("POST", "/search/tags", {"foxx": 1}, None, "unknown_tag"),
        ("GET", "/search/species", None, None, "bad_query"),
        ("POST", "/search/tags?from=yesterday", ["fox"], None, "bad_date"),
    ],
)
def test_bad_input_is_400_before_firestore(
    clouds, method, path, json_body, data, code
):
    body, status = call(method, path, json_body, data)
    assert (status, body["error"]["code"]) == (400, code)
    clouds.collection.assert_not_called()


def test_tags_combine_with_and_and_counts_are_minimums(clouds):
    # Candidates Firestore returns after narrowing by one tag. Only "both"
    # meets every minimum, so OR or ignored counts would return more files.
    stored(
        clouds,
        both=record({"feral pig": 1, "cane toad": 3}),
        pig_only=record({"feral pig": 2}),
        few_toads=record({"feral pig": 1, "cane toad": 2}),
        deleting=record({"feral pig": 1, "cane toad": 3}, status="deleting"),
    )
    body, status = call(json_body={"feral pig": 1, "cane toad": 3})
    assert status == 200
    assert ids(body) == ["both"]
    # Either tag narrows correctly; names with spaces must be quoted.
    assert narrowed_by(clouds) in {
        ("tags.`feral pig`", ">=", 1),
        ("tags.`cane toad`", ">=", 3),
    }


def test_species_route_means_at_least_one(clouds):
    stored(clouds, cat=record({"cat": 1}))
    body, status = call("GET", "/search/species?name=%20Cat")
    assert status == 200
    assert ids(body) == ["cat"]
    assert narrowed_by(clouds) == ("tags.cat", ">=", 1)


@pytest.mark.parametrize(
    "day, expected",
    [("2026-10-27", ["late_27th"]), ("2026-10-28", ["early_28th"])],
)
def test_dates_are_melbourne_days(clouds, day, expected):
    # Melbourne is UTC+11 in late October.
    stored(
        clouds,
        late_27th=record(
            {"fox": 1}, datetime(2026, 10, 27, 12, 30, tzinfo=timezone.utc)
        ),
        early_28th=record(
            {"fox": 1}, datetime(2026, 10, 27, 13, 30, tzinfo=timezone.utc)
        ),
    )
    body, _ = call(path=f"/search/tags?from={day}&to={day}", json_body=["fox"])
    assert ids(body) == expected


def test_results_are_newest_first_with_signed_urls(clouds):
    stored(
        clouds,
        older=record({"fox": 1}),
        newer=record({"fox": 1}, UPLOADED + timedelta(days=1)),
    )
    body, _ = call(json_body=["fox"])
    assert ids(body) == ["newer", "older"]
    newest = body["results"][0]
    assert newest["url"] == SIGNED
    assert newest["thumbnail_url"] == SIGNED
    assert newest["uploaded_at"] == "2026-10-27T09:43:00Z"


def test_firestore_failure_is_500(clouds):
    clouds.collection.return_value.where.return_value.stream.side_effect = (
        RuntimeError("unavailable")
    )
    _, status = call(json_body={"fox": 1})
    assert status == 500
