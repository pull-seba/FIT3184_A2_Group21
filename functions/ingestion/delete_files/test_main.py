"""Tests mock every cloud client; nothing here touches the shared project.

Firestore and Storage are small in-memory fakes, so each test can check what
is left afterwards, as the demo does ("show storage and Firestore clean").
"""

import base64
import hashlib
import json
from types import SimpleNamespace
from unittest import mock

import flask
import pytest
from google.api_core import exceptions

with (
    mock.patch("google.cloud.firestore.Client"),
    mock.patch("google.cloud.storage.Client"),
):
    import main

app = flask.Flask(__name__)

MEDIA = "ecoguard-g21-media"
DERIVED = "ecoguard-g21-derived"
USER = "uploader-sub"
SIGNATURE = "X-Goog-Algorithm=GOOG4-RSA-SHA256&X-Goog-Signature=0a1b2c3d"


class FakeDoc:
    def __init__(self, cloud, collection, doc_id):
        self.cloud, self.key = cloud, (collection, doc_id)

    def get(self):
        data = self.cloud.docs.get(self.key)
        return SimpleNamespace(to_dict=lambda: dict(data) if data else None)

    def set(self, data, merge=False):
        assert merge, "every write merges (firestore-schema.md)"
        self.cloud.ops.append(("set", *self.key, dict(data)))
        self.cloud.docs[self.key] = {
            **self.cloud.docs.get(self.key, {}),
            **data,
        }

    def delete(self):
        self.cloud.ops.append(("delete", *self.key))
        self.cloud.docs.pop(self.key, None)


class FakeFirestore:
    def __init__(self, cloud):
        self.cloud = cloud

    def collection(self, name):
        cloud = self.cloud

        class Collection:
            def document(self, doc_id):
                return FakeDoc(cloud, name, doc_id)

            def where(self, filter):
                assert filter.op_string == "=="
                matches = [
                    doc_id
                    for (collection, doc_id), data in list(cloud.docs.items())
                    if collection == name
                    and data.get(filter.field_path) == filter.value
                ]
                return SimpleNamespace(
                    stream=lambda: [
                        SimpleNamespace(reference=FakeDoc(cloud, name, doc_id))
                        for doc_id in matches
                    ]
                )

        return Collection()


class FakeStorage:
    def __init__(self, cloud):
        self.cloud = cloud

    def list_blobs(self, bucket, prefix):
        cloud = self.cloud
        listed = [
            key
            for b, key in sorted(cloud.objects)
            if b == bucket and key.startswith(prefix)
        ]
        # An object another call deletes between this listing and our delete.
        cloud.objects -= {
            (bucket, key) for key in listed if key in cloud.vanishing
        }
        return [self.blob(bucket, key) for key in listed]

    def blob(self, bucket, key):
        cloud = self.cloud

        def delete():
            if key in cloud.broken:
                raise exceptions.ServiceUnavailable("storage is down")
            if (bucket, key) not in cloud.objects:
                raise exceptions.NotFound("no such object")
            cloud.objects.discard((bucket, key))
            cloud.ops.append(("delete object", bucket, key))

        return SimpleNamespace(delete=delete)


@pytest.fixture
def cloud(monkeypatch):
    state = SimpleNamespace(
        docs={}, objects=set(), ops=[], broken=set(), vanishing=set()
    )
    monkeypatch.setattr(main, "db", FakeFirestore(state))
    monkeypatch.setattr(main, "gcs", FakeStorage(state))
    return state


def add_file(
    cloud, name, ext="jpg", frames=0, sightings=0, uploaded_by=USER, **fields
):
    """A processed file as the pipeline leaves it. Returns its ID."""
    file_id = hashlib.sha256(name.encode()).hexdigest()
    cloud.objects |= {
        (MEDIA, f"{file_id}.{ext}"),
        (DERIVED, f"thumbs/{file_id}.jpg"),
    }
    cloud.objects |= {
        (DERIVED, f"frames/{file_id}/{i:04d}.jpg") for i in range(frames)
    }
    cloud.docs[("files", file_id)] = {
        "file_id": file_id,
        "media_key": f"{file_id}.{ext}",
        "uploaded_by": uploaded_by,
        "status": "active",
        **fields,
    }
    for n in range(sightings):
        cloud.docs[("sightings", f"{file_id}_{n}")] = {
            "file_id": file_id,
            "species": "cat",
        }
    return file_id


def leftovers(cloud, file_id):
    """Everything still stored for a file."""
    objects = sorted(key for _, key in cloud.objects if file_id in key)
    docs = sorted(
        f"{collection}/{doc_id}"
        for (collection, doc_id), data in cloud.docs.items()
        if file_id in doc_id or data.get("file_id") == file_id
    )
    return objects + docs


def original_url(file_id, ext="jpg"):
    return f"https://storage.googleapis.com/{MEDIA}/{file_id}.{ext}"


def gateway_headers(sub=USER, email="test@example.com"):
    """What API Gateway adds after it verifies a Cognito ID token."""
    raw = json.dumps({"sub": sub, "email": email}).encode()
    return {
        "X-Apigateway-Api-Userinfo": base64.urlsafe_b64encode(raw)
        .decode()
        .rstrip("=")
    }


def call(json_body=None, headers=None, data=None, method="POST"):
    with app.test_request_context(
        method=method, json=json_body, data=data, headers=headers or {}
    ):
        return main.handler(flask.request)


def delete(*urls, sub=USER):
    body, status, _ = call({"urls": list(urls)}, headers=gateway_headers(sub))
    assert status == 200
    return json.loads(body)["results"]


# ---- Request checks ----


def test_rejects_request_without_gateway_claims(cloud):
    _, status, _ = call({"urls": ["x"]})
    assert status == 401


def test_answers_cors_preflight_without_a_token():
    body, status, headers = call(method="OPTIONS")
    assert (body, status) == ("", 204)
    assert headers["Access-Control-Allow-Origin"] == "*"
    assert "POST" in headers["Access-Control-Allow-Methods"]
    assert "Authorization" in headers["Access-Control-Allow-Headers"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"json_body": {"urls": ["x"]}},  # 401
        {"data": "not json", "headers": gateway_headers()},  # 400
        {"json_body": {"urls": ["x"]}, "headers": gateway_headers()},  # 200
    ],
)
def test_every_response_allows_the_app_origin(cloud, kwargs):
    _, _, headers = call(**kwargs)
    assert headers["Access-Control-Allow-Origin"] == "*"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"data": "not json"},
        {"json_body": ["a list"]},
        {"json_body": {}},
        {"json_body": {"urls": "one url"}},
        {"json_body": {"urls": []}},
        {"json_body": {"urls": [42]}},
        {"json_body": {"urls": ["u"] * 101}},
    ],
)
def test_rejects_invalid_requests_before_touching_anything(cloud, kwargs):
    add_file(cloud, "fox")
    before = (set(cloud.objects), dict(cloud.docs))
    body, status, _ = call(headers=gateway_headers(), **kwargs)
    assert status == 400
    assert json.loads(body)["error"]["code"] in {"bad_json", "bad_urls"}
    assert (cloud.objects, cloud.docs) == before


def test_accepts_100_urls(cloud):
    results = delete(*[f"https://example.com/{n}.jpg" for n in range(100)])
    assert len(results) == 100


# ---- Deleting ----


def test_deletes_an_image_with_its_thumbnail_and_record(cloud):
    file_id = add_file(cloud, "fox")
    results = delete(original_url(file_id))
    assert results == [
        {"url": original_url(file_id), "file_id": file_id, "status": "deleted"}
    ]
    assert leftovers(cloud, file_id) == []


def test_deletes_a_video_with_its_frames_and_sightings(cloud):
    file_id = add_file(cloud, "cat video", ext="mp4", frames=6, sightings=2)
    assert len(leftovers(cloud, file_id)) == 1 + 1 + 6 + 1 + 2
    assert delete(original_url(file_id, "mp4"))[0]["status"] == "deleted"
    assert leftovers(cloud, file_id) == []


def test_leaves_other_files_alone(cloud):
    target = add_file(cloud, "cat video", ext="mp4", frames=6, sightings=1)
    other = add_file(cloud, "other cat", ext="mp4", frames=3, sightings=1)
    before = leftovers(cloud, other)
    delete(original_url(target, "mp4"))
    assert leftovers(cloud, other) == before


@pytest.mark.parametrize(
    "url",
    [
        "https://storage.googleapis.com/{bucket}/{id}.mp4",
        "gs://{bucket}/{id}.mp4",
        "https://storage.googleapis.com/{bucket}/{id}.mp4?" + SIGNATURE,
        "https://storage.googleapis.com/{derived}/thumbs/{id}.jpg?" + SIGNATURE,
    ],
)
def test_any_url_of_a_file_deletes_all_of_it(cloud, url):
    file_id = add_file(cloud, "fox video", ext="mp4", frames=6, sightings=1)
    url = url.format(bucket=MEDIA, derived=DERIVED, id=file_id)
    assert delete(url) == [
        {"url": url, "file_id": file_id, "status": "deleted"}
    ]
    assert leftovers(cloud, file_id) == []


def test_marks_deleting_first_and_deletes_the_record_last(cloud):
    file_id = add_file(cloud, "cat video", ext="mp4", frames=2, sightings=1)
    delete(original_url(file_id, "mp4"))
    assert cloud.ops[0] == ("set", "files", file_id, {"status": "deleting"})
    assert cloud.ops[-1] == ("delete", "files", file_id)
    assert (
        len(cloud.ops) == 1 + 4 + 1 + 1
    )  # mark, 4 objects, 1 sighting, record


# ---- Results ----


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/fox.jpg",
        "not a url",
        "",
        "gs://someone-elses-bucket/{id}.jpg",
        "https://storage.googleapis.com/{bucket}/fox.jpg",
        "https://storage.googleapis.com/{derived}/{id}.jpg",
    ],
)
def test_url_that_isnt_one_of_ours_is_not_found(cloud, url):
    file_id = add_file(cloud, "fox")
    url = url.format(bucket=MEDIA, derived=DERIVED, id=file_id)
    before = set(cloud.objects)
    assert delete(url) == [{"url": url, "file_id": None, "status": "not_found"}]
    assert cloud.objects == before


def test_file_with_no_record_is_not_found(cloud):
    file_id = hashlib.sha256(b"never uploaded").hexdigest()
    assert delete(original_url(file_id)) == [
        {
            "url": original_url(file_id),
            "file_id": file_id,
            "status": "not_found",
        }
    ]
    assert cloud.ops == []


def test_deleting_twice_reports_not_found_the_second_time(cloud):
    file_id = add_file(cloud, "fox")
    assert delete(original_url(file_id))[0]["status"] == "deleted"
    assert delete(original_url(file_id))[0]["status"] == "not_found"


def test_same_file_twice_in_one_request_is_deleted_once(cloud):
    file_id = add_file(cloud, "fox")
    thumbnail = f"https://storage.googleapis.com/{DERIVED}/thumbs/{file_id}.jpg"
    results = delete(original_url(file_id), thumbnail)
    assert [r["status"] for r in results] == ["deleted", "deleted"]
    assert cloud.ops.count(("delete", "files", file_id)) == 1


def test_one_result_per_url_in_request_order(cloud):
    mine = add_file(cloud, "fox")
    theirs = add_file(cloud, "toad", uploaded_by="someone-else")
    missing = hashlib.sha256(b"missing").hexdigest()
    urls = [
        "https://example.com/x.jpg",
        original_url(theirs),
        original_url(mine),
        original_url(missing),
    ]
    results = delete(*urls)
    assert [r["url"] for r in results] == urls
    assert [r["file_id"] for r in results] == [None, theirs, mine, missing]
    assert [r["status"] for r in results] == [
        "not_found",
        "error",
        "deleted",
        "not_found",
    ]


# ---- Who can delete ----


def test_only_the_uploader_can_delete(cloud):
    file_id = add_file(cloud, "fox", uploaded_by="someone-else")
    before = leftovers(cloud, file_id)
    assert delete(original_url(file_id)) == [
        {
            "url": original_url(file_id),
            "file_id": file_id,
            "status": "error",
            "detail": "You can only delete files you uploaded",
        }
    ]
    assert leftovers(cloud, file_id) == before
    assert cloud.docs[("files", file_id)]["status"] == "active"


def test_seeded_files_cant_be_deleted_from_the_app(cloud):
    file_id = add_file(cloud, "seed", uploaded_by="seed-data", seed=True)
    assert delete(original_url(file_id))[0]["status"] == "error"


def test_record_tagging_wrote_before_the_upload_finished_isnt_deletable(cloud):
    # Tagging can merge its fields first; that document has no uploaded_by yet.
    file_id = hashlib.sha256(b"in flight").hexdigest()
    cloud.docs[("files", file_id)] = {"tags": {"fox": 1}}
    assert delete(original_url(file_id))[0]["status"] == "error"


# ---- Retries and failures ----


def test_finishes_a_delete_that_stopped_halfway(cloud):
    file_id = add_file(
        cloud, "cat video", ext="mp4", frames=6, sightings=2, status="deleting"
    )
    cloud.objects.discard((DERIVED, f"thumbs/{file_id}.jpg"))
    cloud.objects -= {
        (DERIVED, f"frames/{file_id}/000{i}.jpg") for i in range(3)
    }
    assert delete(original_url(file_id, "mp4"))[0]["status"] == "deleted"
    assert leftovers(cloud, file_id) == []


def test_object_deleted_by_another_call_meanwhile_counts_as_deleted(cloud):
    file_id = add_file(cloud, "cat video", ext="mp4", frames=3)
    cloud.vanishing = {f"frames/{file_id}/0001.jpg", f"thumbs/{file_id}.jpg"}
    assert delete(original_url(file_id, "mp4"))[0]["status"] == "deleted"
    assert leftovers(cloud, file_id) == []


def test_failure_keeps_the_file_hidden_and_a_retry_finishes_it(cloud):
    broken = add_file(cloud, "cat video", ext="mp4", frames=3)
    fine = add_file(cloud, "fox")
    cloud.broken = {f"frames/{broken}/0001.jpg"}

    results = delete(original_url(broken, "mp4"), original_url(fine))
    assert results[0] == {
        "url": original_url(broken, "mp4"),
        "file_id": broken,
        "status": "error",
        "detail": "Could not delete it. Try again.",
    }
    assert results[1]["status"] == "deleted"  # the rest of the list carries on
    assert (
        cloud.docs[("files", broken)]["status"] == "deleting"
    )  # out of results

    cloud.broken = set()
    assert delete(original_url(broken, "mp4"))[0]["status"] == "deleted"
    assert leftovers(cloud, broken) == []


def test_logs_name_the_file_but_never_the_url(cloud, capsys):
    deleted = add_file(cloud, "fox")
    failed = add_file(cloud, "toad")
    cloud.broken = {f"{failed}.jpg"}
    urls = [
        original_url(deleted) + "?" + SIGNATURE,
        original_url(failed) + "?" + SIGNATURE,
    ]
    delete(*urls)

    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    by_file = {line["file_id"]: line for line in lines}
    assert by_file[deleted]["message"] == "file deleted"
    assert by_file[deleted]["objects"] == 2
    assert by_file[failed]["severity"] == "ERROR"
    assert all(url not in json.dumps(lines) for url in urls)
    assert "X-Goog-Signature" not in json.dumps(lines)
