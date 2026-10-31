import base64
import json
from unittest import mock

import flask
import pytest
from google.cloud import firestore

with mock.patch("google.cloud.firestore.Client"):
    import main

app = flask.Flask(__name__)

JPG_ID = "a" * 64
PNG_ID = "b" * 64
MP4_ID = "c" * 64
MISSING_ID = "d" * 64
MEDIA = "https://storage.googleapis.com/ecoguard-g21-media"
JPG_URL = f"{MEDIA}/{JPG_ID}.jpg"
JPG_THUMBNAIL_URL = (
    f"https://storage.googleapis.com/ecoguard-g21-derived/thumbs/{JPG_ID}.jpg"
)
PNG_URL = f"{MEDIA}/{PNG_ID}.png"
MP4_URL = f"{MEDIA}/{MP4_ID}.mp4"
MISSING_URL = f"{MEDIA}/{MISSING_ID}.jpg"
FOREIGN_URL = "https://example.com/cat.jpg"
ACTIVE = {"status": "active"}


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
        "/tags/bulk", method="POST", json=json_body, data=data, headers=headers
    ):
        body, status, _ = main.handler(flask.request)
        return json.loads(body), status


def bulk(**overrides):
    return {"urls": [JPG_URL], "tags": ["fox"], "operation": 1, **overrides}


@pytest.fixture(autouse=True)
def db(monkeypatch):
    firestore_db = mock.Mock()
    firestore_db.collection.return_value.document.side_effect = lambda file_id: (
        mock.Mock(id=file_id)
    )
    monkeypatch.setattr(main, "db", firestore_db)
    return firestore_db


def firestore_holds(db, records):
    db.get_all.side_effect = lambda refs, field_paths: [
        mock.Mock(
            id=ref.id,
            exists=ref.id in records,
            **{"to_dict.return_value": records.get(ref.id)},
        )
        for ref in refs
    ]


def changes_by_file_id(db):
    updates = db.batch.return_value.update.call_args_list
    return {ref.id: changes for (ref, changes), _ in updates}


def test_rejects_request_without_gateway_claims():
    _, status = call(bulk(), headers={})
    assert status == 401


@pytest.mark.parametrize(
    "json_body, data, code",
    [
        (None, "not json", "bad_json"),
        (bulk(urls=[]), None, "bad_urls"),
        (bulk(urls=[7]), None, "bad_urls"),
        (bulk(operation=2), None, "bad_operation"),
        (bulk(operation=True), None, "bad_operation"),
        (bulk(tags=["foxx"]), None, "unknown_tag"),
        (bulk(tags=[]), None, "bad_query"),
    ],
)
def test_bad_input_is_400_before_firestore(db, json_body, data, code):
    body, status = call(json_body, data)
    assert (status, body["error"]["code"]) == (400, code)
    db.get_all.assert_not_called()
    db.batch.assert_not_called()


def test_add_sets_count_1_if_absent_and_records_manual_tags(db):
    firestore_holds(db, {JPG_ID: ACTIVE, PNG_ID: ACTIVE, MP4_ID: ACTIVE})
    body, status = call(
        bulk(urls=[JPG_URL, PNG_URL, MP4_URL], tags=[" Feral Pig", "fox"])
    )
    assert status == 200
    assert [result["status"] for result in body["results"]] == ["updated"] * 3
    added = {
        "tags.`feral pig`": firestore.Maximum(1),
        "tags.fox": firestore.Maximum(1),
        "manual_tags": firestore.ArrayUnion(["feral pig", "fox"]),
    }
    assert changes_by_file_id(db) == {
        JPG_ID: added,
        PNG_ID: added,
        MP4_ID: added,
    }
    db.collection.assert_called_with("files")
    db.batch.return_value.commit.assert_called_once()


def test_remove_deletes_tags_and_manual_tags(db):
    firestore_holds(db, {JPG_ID: ACTIVE, PNG_ID: ACTIVE, MP4_ID: ACTIVE})
    body, status = call(
        bulk(urls=[JPG_URL, PNG_URL, MP4_URL], tags=["fox", "cat"], operation=0)
    )
    assert status == 200
    assert [result["status"] for result in body["results"]] == ["updated"] * 3
    removed = {
        "tags.fox": firestore.DELETE_FIELD,
        "tags.cat": firestore.DELETE_FIELD,
        "manual_tags": firestore.ArrayRemove(["fox", "cat"]),
    }
    assert changes_by_file_id(db) == {
        JPG_ID: removed,
        PNG_ID: removed,
        MP4_ID: removed,
    }


def test_one_result_per_url_in_request_order(db):
    firestore_holds(db, {JPG_ID: ACTIVE, PNG_ID: {"status": "deleting"}})
    urls = [FOREIGN_URL, JPG_URL, PNG_URL, MISSING_URL, JPG_THUMBNAIL_URL]
    body, status = call(bulk(urls=urls))
    assert status == 200
    assert body["results"] == [
        {"url": FOREIGN_URL, "file_id": None, "status": "not_found"},
        {"url": JPG_URL, "file_id": JPG_ID, "status": "updated"},
        {"url": PNG_URL, "file_id": PNG_ID, "status": "not_found"},
        {"url": MISSING_URL, "file_id": MISSING_ID, "status": "not_found"},
        {"url": JPG_THUMBNAIL_URL, "file_id": JPG_ID, "status": "updated"},
    ]
    db.batch.return_value.update.assert_called_once()


def test_url_that_is_not_ours_is_not_found(db):
    body, status = call(bulk(urls=[FOREIGN_URL]))
    assert status == 200
    assert body["results"] == [
        {"url": FOREIGN_URL, "file_id": None, "status": "not_found"}
    ]
    db.get_all.assert_not_called()
    db.batch.assert_not_called()


def test_more_than_500_files_split_into_batches(db):
    file_ids = [f"{n:064x}" for n in range(501)]
    urls = [f"{MEDIA}/{file_id}.jpg" for file_id in file_ids]
    firestore_holds(db, dict.fromkeys(file_ids, ACTIVE))
    first, second = mock.Mock(), mock.Mock()
    db.batch.side_effect = [first, second]
    _, status = call(bulk(urls=urls))
    assert status == 200
    assert (first.update.call_count, second.update.call_count) == (500, 1)
    first.commit.assert_called_once()
    second.commit.assert_called_once()


def test_firestore_failure_is_500(db):
    db.get_all.side_effect = RuntimeError("unavailable")
    _, status = call(bulk())
    assert status == 500
