"""Tests mock every cloud client; nothing here touches the shared project or
calls Vertex AI."""

import base64
import io
import json
from datetime import datetime, timedelta, timezone
from unittest import mock

import flask
import pytest
from google.cloud.firestore_v1.base_vector_query import DistanceMeasure
from google.cloud.firestore_v1.vector import Vector
from PIL import Image

from ecoguard_ml import detect

with (
    mock.patch("google.cloud.firestore.Client"),
    mock.patch("google.cloud.storage.Client"),
    mock.patch(
        "google.auth.default", return_value=(mock.Mock(), "test-project")
    ),
):
    import main

# The real config reader, kept before the config fixture replaces it.
REAL_MODEL_CONFIG = detect.model_config

app = flask.Flask(__name__)

CONFIG = {
    "version": "2026-10-31.1",
    "embedding_model": "multimodalembedding@001",
    "embedding_dimension": 1408,
    "embedding_location": "us-east1",
}
QUERY_VECTOR = [0.1, 0.2, 0.3]
SIGNED = "https://signed.example"
NOW = datetime.now(timezone.utc)
RECENT = NOW - timedelta(days=1)
OLD = NOW - timedelta(days=40)  # outside the default 30 days
MB = 1024 * 1024


def jpeg(width=40, height=30, kind="JPEG"):
    out = io.BytesIO()
    Image.new("RGB", (width, height), "orange").save(out, kind)
    return out.getvalue()


PHOTO_BASE64 = base64.b64encode(jpeg()).decode()


def gateway_headers(sub="test-user", email="test@example.com"):
    """What API Gateway adds after it verifies a Cognito ID token."""
    raw = json.dumps({"sub": sub, "email": email}).encode()
    return {
        "X-Apigateway-Api-Userinfo": base64.urlsafe_b64encode(raw)
        .decode()
        .rstrip("=")
    }


def call(json_body=None, data=None, headers=None, method="POST"):
    """(parsed body or None, status, headers)."""
    if headers is None:
        headers = gateway_headers()
    with app.test_request_context(
        "/search/lost-pet",
        method=method,
        json=json_body,
        data=data,
        headers=headers,
    ):
        body, status, response_headers = main.handler(flask.request)
        return (json.loads(body) if body else None), status, response_headers


def file_record(uploaded_at=RECENT, status="active"):
    return {
        "file_type": "image",
        "media_bucket": "ecoguard-g21-media",
        "media_key": "x.jpg",
        "thumbnail_key": "thumbs/x.jpg",
        "tags": {"cat": 1},
        "uploaded_at": uploaded_at,
        "status": status,
    }


def sighting(file_id, n=0, distance=None, colour="ginger", uploaded_at=RECENT):
    """A sightings snapshot as Firestore streams it. find_nearest adds the
    distance field named by distance_result_field."""
    data = {
        "file_id": file_id,
        "species": "cat",
        "colour": colour,
        "breed": None,
        "uploaded_at": uploaded_at,
        "is_public": True,
    }
    if distance is not None:
        data["distance"] = distance
    return mock.Mock(id=f"{file_id}_{n}", **{"to_dict.return_value": data})


@pytest.fixture(autouse=True)
def clouds(monkeypatch):
    """Fresh Firestore and Storage fakes for every test.

    db.collection("sightings") is db.sightings, a query whose where(),
    find_nearest(), order_by() and limit() return itself, so a chain of any
    length ends in db.sightings.stream(). db.collection("files") is
    db.files, whose document(id) is the string "files/<id>"."""
    db, gcs = mock.Mock(), mock.Mock()
    db.collection.side_effect = lambda name: getattr(db, name)
    query = db.sightings
    for method in ("where", "find_nearest", "order_by", "limit"):
        getattr(query, method).return_value = query
    query.stream.return_value = []
    db.files.document.side_effect = lambda file_id: f"files/{file_id}"
    db.get_all.return_value = []
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
    model_config = mock.Mock(return_value=CONFIG)
    monkeypatch.setattr(main.detect, "model_config", model_config)
    return model_config


@pytest.fixture(autouse=True)
def embed_image(monkeypatch):
    """Vertex AI replaced: every photo embeds to QUERY_VECTOR."""
    embed_image = mock.Mock(return_value=QUERY_VECTOR)
    monkeypatch.setattr(main.embed, "embed_image", embed_image)
    return embed_image


def firestore_returns(db, sightings=(), files=None):
    """sightings streamed by the query; files/<id> records for get_all."""
    db.sightings.stream.return_value = list(sightings)
    files = files or {}

    def get_all(refs):
        for ref in refs:
            file_id = ref.removeprefix("files/")
            yield mock.Mock(
                id=file_id,
                exists=file_id in files,
                **{"to_dict.return_value": files.get(file_id)},
            )

    db.get_all.side_effect = get_all


def filters_sent(db):
    """(field, op, value) for each where() on the sightings query."""
    sent = [c.kwargs["filter"] for c in db.sightings.where.call_args_list]
    return [(f.field_path, f.op_string, f.value) for f in sent]


def ids(body):
    return [result["file_id"] for result in body["results"]]


# ---------- gateway and CORS ----------


def test_rejects_request_without_gateway_claims(embed_image, db):
    body, status, headers = call({"species": "cat"}, headers={})
    assert (status, body["error"]["code"]) == (401, "unauthenticated")
    assert headers["Access-Control-Allow-Origin"] == "*"
    embed_image.assert_not_called()
    db.collection.assert_not_called()


def test_preflight_is_204_with_cors_headers_and_no_token():
    body, status, headers = call(method="OPTIONS", headers={})
    assert (body, status) == (None, 204)
    assert headers == {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, PUT, OPTIONS",
        "Access-Control-Allow-Headers": "Authorization, Content-Type",
    }


# ---------- bad input, rejected before Vertex AI or Firestore ----------


@pytest.mark.parametrize(
    "json_body, data, status, code",
    [
        (None, "not json", 400, "bad_json"),
        (["not", "an", "object"], None, 400, "bad_json"),
        ({}, None, 400, "missing_query"),
        ({"colour": "ginger", "breed": "tabby"}, None, 400, "missing_query"),
        ({"species": "fox"}, None, 400, "bad_species"),
        ({"species": 1}, None, 400, "bad_species"),
        ({"species": "cat", "colour": "purple"}, None, 400, "bad_colour"),
        ({"species": "cat", "since_days": 0}, None, 400, "bad_since_days"),
        ({"species": "cat", "since_days": 366}, None, 400, "bad_since_days"),
        ({"species": "cat", "since_days": True}, None, 400, "bad_since_days"),
        ({"species": "cat", "since_days": "30"}, None, 400, "bad_since_days"),
        ({"species": "cat", "since_days": 1.5}, None, 400, "bad_since_days"),
        ({"species": "cat", "breed": 5}, None, 400, "bad_breed"),
        ({"image_base64": 123}, None, 400, "bad_file"),
        ({"image_base64": "", "species": "cat"}, None, 400, "bad_file"),
        ({"image_base64": "not base64!!"}, None, 400, "bad_base64"),
        (
            {"image_base64": base64.b64encode(b"not a photo").decode()},
            None,
            400,
            "bad_image",
        ),
    ],
)
def test_bad_input_is_rejected_before_any_cloud_call(
    json_body, data, status, code, embed_image, config, db
):
    body, got_status, headers = call(json_body, data)
    assert (got_status, body["error"]["code"]) == (status, code)
    assert set(body["error"]) == {"code", "message"}
    assert headers["Access-Control-Allow-Origin"] == "*"
    embed_image.assert_not_called()
    config.assert_not_called()
    db.collection.assert_not_called()


def test_photo_over_20_mb_is_413(embed_image, db):
    too_big = base64.b64encode(b"\0" * (20 * MB + 1)).decode()
    body, status, _ = call({"image_base64": too_big})
    assert (status, body["error"]["code"]) == (413, "too_large")
    embed_image.assert_not_called()
    db.collection.assert_not_called()


@pytest.mark.parametrize("since_days", [1, 365, None])
def test_since_days_limits_and_default_are_accepted(since_days):
    body, status, _ = call({"species": "cat", "since_days": since_days})
    assert (status, body) == (200, {"results": []})


def test_vertex_failure_is_500(embed_image):
    embed_image.side_effect = RuntimeError("429 Too Many Requests")
    body, status, headers = call({"image_base64": PHOTO_BASE64})
    assert (status, body["error"]["code"]) == (500, "internal")
    assert headers["Access-Control-Allow-Origin"] == "*"


# ---------- search by photo ----------


def test_photo_is_shrunk_to_a_1024_px_jpeg_and_embedded_with_config(
    embed_image, config
):
    png = base64.b64encode(jpeg(2000, 1000, "PNG")).decode()
    call({"image_base64": png, "species": "cat"})
    config.assert_called_once()
    sent, sent_config = embed_image.call_args.args
    assert sent_config == CONFIG
    image = Image.open(io.BytesIO(sent))
    assert (image.format, image.size) == ("JPEG", (1024, 512))


def test_photo_search_is_one_vector_query_with_species_and_is_public(db):
    call({"image_base64": PHOTO_BASE64, "species": "cat"})
    db.collection.assert_called_once_with("sightings")  # no files to fetch
    assert filters_sent(db) == [
        ("species", "==", "cat"),
        ("is_public", "==", True),
    ]
    db.sightings.find_nearest.assert_called_once_with(
        vector_field="embedding",
        query_vector=Vector(QUERY_VECTOR),
        distance_measure=DistanceMeasure.COSINE,
        limit=50,
        distance_result_field="distance",
    )
    db.sightings.order_by.assert_not_called()


def test_photo_search_without_species_filters_on_is_public_only(db):
    call({"image_base64": PHOTO_BASE64})
    assert filters_sent(db) == [("is_public", "==", True)]
    db.sightings.find_nearest.assert_called_once()


def test_the_pages_any_species_body_with_nulls_is_a_no_species_search(db):
    # What the lost-pet page sends for "any species, any colour".
    firestore_returns(
        db,
        sightings=[sighting("a", distance=0.1, colour="black")],
        files={"a": file_record()},
    )
    body, status, _ = call(
        {
            "image_base64": PHOTO_BASE64,
            "species": None,
            "colour": None,
            "breed": None,
            "since_days": 30,
        }
    )
    assert (status, ids(body)) == (200, ["a"])
    assert filters_sent(db) == [("is_public", "==", True)]
    db.sightings.find_nearest.assert_called_once()


def test_null_species_without_a_photo_is_still_400(db):
    body, status, _ = call({"species": None, "colour": None, "breed": None})
    assert (status, body["error"]["code"]) == (400, "missing_query")
    db.collection.assert_not_called()


def test_photo_results_are_ranked_by_score_one_minus_distance(db):
    # Streamed out of order: the function ranks them itself.
    firestore_returns(
        db,
        sightings=[
            sighting("far", distance=0.4),
            sighting("near", distance=0.05),
            sighting("middle", distance=0.123),
        ],
        files={name: file_record() for name in ("far", "near", "middle")},
    )
    body, status, _ = call({"image_base64": PHOTO_BASE64, "species": "cat"})
    assert status == 200
    assert ids(body) == ["near", "middle", "far"]
    assert [r["score"] for r in body["results"]] == [0.95, 0.88, 0.6]


def test_photo_search_drops_sightings_older_than_since_days(db):
    firestore_returns(
        db,
        sightings=[
            sighting("old", distance=0.1, uploaded_at=OLD),
            sighting("recent", distance=0.2),
        ],
        files={"old": file_record(OLD), "recent": file_record()},
    )
    body, _, _ = call({"image_base64": PHOTO_BASE64})
    assert ids(body) == ["recent"]
    body, _, _ = call({"image_base64": PHOTO_BASE64, "since_days": 60})
    assert ids(body) == ["old", "recent"]


def test_photo_search_filters_colour_after_the_vector_query(db):
    firestore_returns(
        db,
        sightings=[
            sighting("black_cat", distance=0.1, colour="black"),
            sighting("ginger_cat", distance=0.2, colour="ginger"),
        ],
        files={"black_cat": file_record(), "ginger_cat": file_record()},
    )
    body, _, _ = call({"image_base64": PHOTO_BASE64, "colour": "ginger"})
    assert ids(body) == ["ginger_cat"]
    assert ("colour", "==", "ginger") not in filters_sent(db)


def test_empty_colour_and_breed_do_not_filter(db):
    firestore_returns(
        db,
        sightings=[sighting("a", distance=0.1, colour="black")],
        files={"a": file_record()},
    )
    body, status, _ = call(
        {"image_base64": PHOTO_BASE64, "colour": "", "breed": "Siamese"}
    )
    assert (status, ids(body)) == (200, ["a"])
    assert filters_sent(db) == [("is_public", "==", True)]


def test_one_result_per_file_keeping_its_best_sighting(db):
    firestore_returns(
        db,
        sightings=[
            sighting("two_cats", n=0, distance=0.3),
            sighting("two_cats", n=1, distance=0.1),
            sighting("one_cat", n=0, distance=0.2),
        ],
        files={"two_cats": file_record(), "one_cat": file_record()},
    )
    body, _, _ = call({"image_base64": PHOTO_BASE64})
    assert [
        (r["file_id"], r["sighting_id"], r["score"]) for r in body["results"]
    ] == [
        ("two_cats", "two_cats_1", 0.9),
        ("one_cat", "one_cat_0", 0.8),
    ]
    # Each file is fetched once, in one get_all.
    db.get_all.assert_called_once_with(["files/two_cats", "files/one_cat"])


def test_files_that_are_not_active_are_dropped(db):
    firestore_returns(
        db,
        sightings=[
            sighting("deleting", distance=0.1),
            sighting("no_status", distance=0.15),
            sighting("missing", distance=0.2),
            sighting("active", distance=0.3),
        ],
        files={
            "deleting": file_record(status="deleting"),
            "no_status": file_record(status=None),
            "active": file_record(),
        },
    )
    body, _, _ = call({"image_base64": PHOTO_BASE64})
    assert ids(body) == ["active"]


def test_results_are_file_summaries_with_score_and_sighting_id(db):
    uploaded = datetime(2026, 10, 27, 9, 43, tzinfo=timezone.utc)
    firestore_returns(
        db,
        sightings=[sighting("cat_file", distance=0.09)],
        files={"cat_file": file_record(uploaded)},
    )
    body, _, headers = call({"image_base64": PHOTO_BASE64})
    assert headers["Access-Control-Allow-Origin"] == "*"
    assert set(body) == {"results"}
    assert body["results"] == [
        {
            "file_id": "cat_file",
            "file_type": "image",
            "url": SIGNED,
            "thumbnail_url": SIGNED,
            "tags": {"cat": 1},
            "uploaded_at": "2026-10-27T09:43:00Z",
            "score": 0.91,
            "sighting_id": "cat_file_0",
        }
    ]


def test_no_sightings_returns_no_results_without_fetching_files(db, gcs):
    body, status, _ = call({"image_base64": PHOTO_BASE64})
    assert (status, body) == (200, {"results": []})
    db.get_all.assert_not_called()
    gcs.bucket.assert_not_called()


# ---------- search by description ----------


def test_description_search_filters_in_firestore_newest_first(
    db, embed_image, config
):
    firestore_returns(
        db,
        sightings=[sighting("newer"), sighting("older")],
        files={
            "newer": file_record(RECENT),
            "older": file_record(RECENT - timedelta(days=2)),
        },
    )
    body, status, _ = call({"species": "dog", "since_days": 7})
    assert status == 200
    assert ids(body) == ["newer", "older"]  # the query's order is kept
    assert [r["score"] for r in body["results"]] == [None, None]

    (species, public, (field, op, cutoff)) = filters_sent(db)
    assert species == ("species", "==", "dog")
    assert public == ("is_public", "==", True)
    assert (field, op) == ("uploaded_at", ">=")
    expected = datetime.now(timezone.utc) - timedelta(days=7)
    assert abs(cutoff - expected) < timedelta(seconds=5)
    db.sightings.order_by.assert_called_once_with(
        "uploaded_at", direction=main.firestore.Query.DESCENDING
    )
    db.sightings.limit.assert_called_once_with(50)
    db.sightings.find_nearest.assert_not_called()
    embed_image.assert_not_called()
    config.assert_not_called()


def test_description_search_with_colour_adds_a_colour_filter(db):
    call({"species": "cat", "colour": "tabby"})
    assert [f[:2] for f in filters_sent(db)] == [
        ("species", "=="),
        ("is_public", "=="),
        ("colour", "=="),
        ("uploaded_at", ">="),
    ]
    assert filters_sent(db)[2] == ("colour", "==", "tabby")


# ---------- the query photo is never stored (rubric 2.2.4) ----------

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
    """Each method name in a fake's calls: "sightings.where().stream" gives
    sightings, where and stream."""
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
    monkeypatch.setattr(main.detect, "model_config", REAL_MODEL_CONFIG)
    firestore_returns(
        db,
        sightings=[sighting("match", distance=0.1)],
        files={"match": file_record()},
    )

    body, status, _ = call(
        {"image_base64": PHOTO_BASE64, "species": "cat", "colour": "ginger"}
    )
    assert (status, ids(body)) == (200, ["match"])

    names = called_names(db) | called_names(gcs)
    # The search really ran: config read, vector query, files fetched, URLs signed.
    assert {
        "document",
        "find_nearest",
        "stream",
        "get_all",
        "generate_signed_url",
    } <= names
    written = {
        name
        for name in names
        if name in WRITE_CALLS or name.startswith("upload_from_")
    }
    assert written == set()


def test_the_log_has_no_photo_or_embedding(capsys):
    call({"image_base64": PHOTO_BASE64, "species": "cat", "colour": "ginger"})
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert lines == [
        {
            "severity": "INFO",
            "message": "lost pet search",
            "species": "cat",
            "colour": "ginger",
            "since_days": 30,
            "photo": True,
            "results": 0,
        }
    ]
