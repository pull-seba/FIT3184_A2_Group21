"""Tests for ecoguard_ml.embed. The HTTP session is mocked: no Vertex AI."""

import base64
from unittest import mock

import pytest
import requests

from ecoguard_ml import embed

CONFIG = {
    "embedding_model": "multimodalembedding@001",
    "embedding_dimension": 1408,
    "embedding_location": "us-east1",
}
PREDICTION = {"imageEmbedding": [0.5] * 1408, "textEmbedding": [0.25] * 1408}


@pytest.fixture
def post(monkeypatch):
    session = mock.Mock()
    session.post.return_value.json.return_value = {"predictions": [PREDICTION]}
    monkeypatch.setattr(embed, "session", lambda: session)
    return session.post


def test_image_request_and_response(post):
    assert embed.embed_image(b"jpeg", CONFIG) == [0.5] * 1408
    post.assert_called_once_with(
        "https://us-east1-aiplatform.googleapis.com/v1/projects/ecoguard-g21"
        "/locations/us-east1/publishers/google/models/"
        "multimodalembedding@001:predict",
        json={
            "instances": [
                {
                    "image": {
                        "bytesBase64Encoded": base64.b64encode(b"jpeg").decode()
                    }
                }
            ],
            "parameters": {"dimension": 1408},
        },
        timeout=60,
    )


def test_text_request_and_response(post):
    assert embed.embed_text("a photo of a cat", CONFIG) == [0.25] * 1408
    assert post.call_args.kwargs["json"]["instances"] == [
        {"text": "a photo of a cat"}
    ]


def test_region_model_and_size_come_from_config(post):
    """Rubric 2.1.3: a config change, no code change."""
    config = CONFIG | {
        "embedding_location": "us-central1",
        "embedding_dimension": 512,
    }
    embed.embed_text("a photo of a dog", config)
    url = post.call_args.args[0]
    assert url.startswith("https://us-central1-aiplatform.googleapis.com/")
    assert "/locations/us-central1/" in url
    assert post.call_args.kwargs["json"]["parameters"] == {"dimension": 512}


def test_http_error_is_raised_so_the_event_is_retried(post):
    post.return_value.raise_for_status.side_effect = requests.HTTPError("404")
    with pytest.raises(requests.HTTPError):
        embed.embed_image(b"jpeg", CONFIG)
