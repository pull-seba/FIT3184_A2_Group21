#!/usr/bin/env python3
"""
Member 3 - check Vertex AI multimodal embeddings work from this machine and
make sense for lost pet search, before building it into the tagging service.

Embeds a few test-set photos (cats, dogs, a fox) and two text descriptions,
then prints how similar each pair is (cosine similarity, higher = closer).
Cats should sit closer to cats and to "a cat" than to dogs.

  python3 tools/testset/embed_check.py
  python3 tools/testset/embed_check.py --location us-central1   # if us-east1 404s

Needs `pip install google-auth requests`, the Vertex AI API enabled on the
project, and `gcloud auth application-default login`.
"""

import argparse
import base64
import io
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
IMAGES = HERE / "data" / "images"
PROJECT = "ecoguard-g21"
MODEL = "multimodalembedding@001"
SAMPLES = [
    "cat/cat_005.jpg",
    "cat/cat_017.jpg",
    "dog/dog_005.jpg",
    "dog/dog_012.jpg",
    "fox/fox_001.jpg",
]
TEXTS = ["a photo of a cat", "a photo of a dog"]
MAX_BYTES = 4 * 1024 * 1024  # shrink anything bigger before sending


def image_b64(path):
    data = path.read_bytes()
    if len(data) > MAX_BYTES:
        from PIL import Image

        img = Image.open(path)
        img.thumbnail((1024, 1024))
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "JPEG", quality=90)
        data = buf.getvalue()
    return base64.b64encode(data).decode()


def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (
        math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    )


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--project", default=PROJECT)
    ap.add_argument("--location", default="us-east1")
    ap.add_argument("--dimension", type=int, default=1408)
    args = ap.parse_args()

    try:
        import google.auth
        import requests
        from google.auth.transport.requests import Request
    except ImportError:
        sys.exit("pip install google-auth requests")

    creds, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    creds.refresh(Request())
    url = (
        f"https://{args.location}-aiplatform.googleapis.com/v1/projects/"
        f"{args.project}/locations/{args.location}/publishers/google/"
        f"models/{MODEL}:predict"
    )
    headers = {
        "Authorization": f"Bearer {creds.token}",
        "x-goog-user-project": args.project,
    }

    def embed(instance, key):
        resp = requests.post(
            url,
            headers=headers,
            json={
                "instances": [instance],
                "parameters": {"dimension": args.dimension},
            },
            timeout=60,
        )
        if resp.status_code != 200:
            sys.exit(
                f"Vertex AI returned {resp.status_code}: {resp.text[:300]}\n"
                "403: enable the API (gcloud services enable "
                "aiplatform.googleapis.com) or ask for the Vertex AI User role. "
                "404: try --location us-central1."
            )
        return resp.json()["predictions"][0][key]

    vectors = {}
    for rel in SAMPLES:
        vectors[rel] = embed(
            {"image": {"bytesBase64Encoded": image_b64(IMAGES / rel)}},
            "imageEmbedding",
        )
        print(f"  embedded {rel}: {len(vectors[rel])} numbers")
    for text in TEXTS:
        vectors[text] = embed({"text": text}, "textEmbedding")
        print(f"  embedded '{text}': {len(vectors[text])} numbers")

    names = list(vectors)
    short = [Path(n).stem if "/" in n else n.split()[-1] for n in names]
    print("\nCosine similarity (higher = more alike):")
    print(" " * 18 + "".join(f"{s:>10}" for s in short))
    for name, label in zip(names, short):
        row = "".join(
            f"{cosine(vectors[name], vectors[o]):10.2f}" for o in names
        )
        print(f"{label:>18}{row}")
    print(
        "\nLooks right if cat-cat beats cat-dog, and each photo is closest to "
        "the matching text."
    )


if __name__ == "__main__":
    main()
