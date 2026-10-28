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
    firestore_returns(
        clouds,
        meets_both=record({"feral pig": 1, "cane toad": 3}),
        pig_only=record({"feral pig": 2}),
        too_few_toads=record({"feral pig": 1, "cane toad": 2}),
        deleting=record({"feral pig": 1, "cane toad": 3}, status="deleting"),
    )
    body, status = call(json_body={"feral pig": 1, "cane toad": 3})
    assert status == 200
    assert ids(body) == ["meets_both"]
    assert narrowed_by(clouds) in {
        ("tags.`feral pig`", ">=", 1),
        ("tags.`cane toad`", ">=", 3),
    }


def test_species_route_means_at_least_one(clouds):
    firestore_returns(clouds, cat=record({"cat": 1}))
    body, status = call("GET", "/search/species?name=%20Cat")
    assert status == 200
    assert ids(body) == ["cat"]
    assert narrowed_by(clouds) == ("tags.cat", ">=", 1)


@pytest.mark.parametrize(
    "day, expected",
    [("2026-10-27", ["late_27th"]), ("2026-10-28", ["early_28th"])],
)
def test_dates_are_melbourne_days(clouds, day, expected):
    firestore_returns(
        clouds,
        late_27th=record(
            {"fox": 1}, datetime(2026, 10, 27, 23, 30, tzinfo=main.MELBOURNE)
        ),
        early_28th=record(
            {"fox": 1}, datetime(2026, 10, 28, 0, 30, tzinfo=main.MELBOURNE)
        ),
    )
    body, _ = call(path=f"/search/tags?from={day}&to={day}", json_body=["fox"])
    assert ids(body) == expected


def test_results_are_newest_first_with_signed_urls(clouds):
    firestore_returns(
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
