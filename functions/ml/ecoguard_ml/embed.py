"""Vertex AI multimodal embeddings for lost pet search. Owner: member 3.

Photos and text share one embedding space, so a pet's crop can be compared
with another crop (search by photo) or with "a photo of a ginger cat"
(colour, search by description). Model, dimension and region come from
config/model (rubric 2.1.3). Vertex AI stores nothing it embeds.

On Cloud Run the token is the function's own service account's, so there are
no keys. On a laptop it's `gcloud auth application-default login`. The
request is the one tools/testset/embed_check.py tried out.
"""

import base64

import google.auth
from google.auth.transport.requests import AuthorizedSession

PROJECT = "ecoguard-g21"
_session = None


def session() -> AuthorizedSession:
    """One authorised HTTP session per instance; it refreshes its own token."""
    global _session
    if _session is None:
        credentials, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        _session = AuthorizedSession(credentials)
    return _session


def _predict(instance: dict, config: dict) -> dict:
    location = config["embedding_location"]
    url = (
        f"https://{location}-aiplatform.googleapis.com/v1/projects/{PROJECT}"
        f"/locations/{location}/publishers/google/models/"
        f"{config['embedding_model']}:predict"
    )
    response = session().post(
        url,
        json={
            "instances": [instance],
            "parameters": {"dimension": config["embedding_dimension"]},
        },
        timeout=60,
    )
    # 403, 404, 429 and 5xx raise, so Eventarc or Pub/Sub retries the event.
    response.raise_for_status()
    return response.json()["predictions"][0]


def embed_image(jpeg_bytes: bytes, config: dict) -> list[float]:
    image = {"bytesBase64Encoded": base64.b64encode(jpeg_bytes).decode()}
    return _predict({"image": image}, config)["imageEmbedding"]


def embed_text(text: str, config: dict) -> list[float]:
    return _predict({"text": text}, config)["textEmbedding"]
