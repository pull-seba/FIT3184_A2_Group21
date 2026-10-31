"""Tests for ecoguard_common.urls.

Run from the repo root: python -m pytest shared/python
"""

import pytest

from ecoguard_common.urls import file_id_from_url

FILE_ID = "a3c94a983f10c7e72d9a800e972a8a75764798afb02f84303d76627c47addb14"
MEDIA = "ecoguard-g21-media"
DERIVED = "ecoguard-g21-derived"
# What generate_signed_url(version="v4") appends, shortened.
SIGNATURE = (
    "?X-Goog-Algorithm=GOOG4-RSA-SHA256"
    "&X-Goog-Credential=fn-tag-query%40ecoguard-g21.iam.gserviceaccount.com"
    "%2F20261030%2Fauto%2Fstorage%2Fgoog4_request"
    "&X-Goog-Date=20261030T010203Z&X-Goog-Expires=3600"
    "&X-Goog-SignedHeaders=host&X-Goog-Signature=5f2a9c0e"
)


def every_form(bucket, key):
    """The same object as each URL form the contract accepts."""
    return [
        f"https://storage.googleapis.com/{bucket}/{key}",
        f"gs://{bucket}/{key}",
    ]


@pytest.mark.parametrize("extension", ["jpg", "png", "webp", "mp4", "mov"])
def test_originals_in_every_form(extension):
    for url in every_form(MEDIA, f"{FILE_ID}.{extension}"):
        assert file_id_from_url(url) == FILE_ID


def test_thumbnails_in_every_form():
    for url in every_form(DERIVED, f"thumbs/{FILE_ID}.jpg"):
        assert file_id_from_url(url) == FILE_ID


def test_frames_give_their_files_id_not_the_frame_index():
    for url in every_form(DERIVED, f"frames/{FILE_ID}/0003.jpg"):
        assert file_id_from_url(url) == FILE_ID


def test_signed_urls():
    thumbnail = f"https://storage.googleapis.com/{DERIVED}/thumbs/{FILE_ID}.jpg"
    assert file_id_from_url(thumbnail + SIGNATURE) == FILE_ID


def test_url_encoded_keys():
    encoded = [
        f"https://storage.googleapis.com/{DERIVED}/thumbs%2F{FILE_ID}.jpg",
        f"https://storage.googleapis.com/{DERIVED}%2Fframes%2F{FILE_ID}%2F0000.jpg",
        f"gs://{DERIVED}/frames/{FILE_ID}%2F0001.jpg",
    ]
    for url in encoded:
        assert file_id_from_url(url) == FILE_ID


def test_surrounding_spaces_and_fragments_are_ignored():
    url = f"  gs://{MEDIA}/{FILE_ID}.jpg#top \n"
    assert file_id_from_url(url) == FILE_ID


@pytest.mark.parametrize(
    "url",
    [
        # Not Cloud Storage
        f"https://example.com/{MEDIA}/{FILE_ID}.jpg",
        f"http://storage.googleapis.com/{MEDIA}/{FILE_ID}.jpg",
        f"{MEDIA}/{FILE_ID}.jpg",
        "",
        # Not our buckets: someone else's, or the models bucket
        f"https://storage.googleapis.com/other-bucket/{FILE_ID}.jpg",
        f"gs://ecoguard-g21-models/{FILE_ID}.jpg",
        f"https://storage.googleapis.com/{MEDIA}",
        # Not a key our files use
        f"gs://{MEDIA}/{FILE_ID}.gif",
        f"gs://{MEDIA}/{FILE_ID}",
        f"gs://{MEDIA}/thumbs/{FILE_ID}.jpg",
        f"gs://{DERIVED}/{FILE_ID}.jpg",
        f"gs://{DERIVED}/thumbs/{FILE_ID}.png",
        f"gs://{DERIVED}/frames/{FILE_ID}/1.jpg",
        f"gs://{DERIVED}/frames/{FILE_ID}.jpg",
        f"gs://{MEDIA}/{FILE_ID.upper()}.jpg",
        f"gs://{MEDIA}/{FILE_ID[:63]}.jpg",
        f"gs://{MEDIA}/uploads/{FILE_ID}.jpg",
    ],
)
def test_anything_else_raises_value_error(url):
    with pytest.raises(ValueError):
        file_id_from_url(url)


def test_error_never_repeats_the_url():
    # Callers may log the message, and a signed URL must not reach the logs.
    url = f"https://storage.googleapis.com/other-bucket/x.jpg{SIGNATURE}"
    with pytest.raises(ValueError) as error:
        file_id_from_url(url)
    assert "X-Goog-Signature" not in str(error.value)
    assert "other-bucket" not in str(error.value)
