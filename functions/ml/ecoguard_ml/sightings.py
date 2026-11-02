"""Cat and dog crops for lost pet search. Owner: member 3. Rubric 2.2.4.

Each cat or dog Rekognition boxes becomes one sighting: its crop's Vertex AI
embedding, its colour, its breed and its box. tagging writes them to
sightings/{file_id}_{n} (docs/contracts/firestore-schema.md).
"""

import io
import math

from PIL import Image, ImageOps

from ecoguard_common.tag_match import load_tags
from ecoguard_ml import BadImage, embed
from ecoguard_ml.detect import LABEL_MAP

TAGS = load_tags()
PET_SPECIES = set(TAGS["lost_pet_species"])
COLOURS = TAGS.get("lost_pet_colours", [])
PAD = 0.10  # 10% of the box on each side, so ears and tails stay in
CROP_SIDE = 512  # Vertex AI embeds at about this size: smaller requests
WHOLE_IMAGE = [0.0, 0.0, 1.0, 1.0]
# Rekognition files breeds under Dog or Cat in its label tree, next to these,
# which aren't breeds (tools/testset/data/rekognition_raw.jsonl).
NOT_BREEDS = {"puppy", "kitten", "hound", "white dog", "black cat"}

_colour_vectors = {}  # (embedding model, species) -> {colour: vector}


def pet_boxes(labels: list[dict], config: dict) -> list[tuple[str, list]]:
    """(species, box) for each cat or dog. The label test is count_tags':
    it maps to the tag and reaches that tag's threshold. Boxes aren't
    borrowed from other labels: a sighting must be the pet's own box."""
    found = []
    for label in labels:
        species = LABEL_MAP.get(label["name"].lower())
        if species not in PET_SPECIES:
            continue
        threshold = config["thresholds"].get(
            species, config["default_threshold"]
        )
        if label["confidence"] < threshold:
            continue
        boxes = [
            box
            for box, confidence in zip(label["boxes"], label["instances"])
            if confidence >= config["box_min_confidence"]
        ]
        found += [(species, box) for box in boxes or [WHOLE_IMAGE]]
    return found


def crop(image: Image.Image, box: list[float]) -> bytes:
    """The box padded by PAD and clamped to the photo, as a JPEG of at most
    512 px. Boxes are fractions, so they fit the original at any size."""
    x, y, w, h = box
    width, height = image.size
    left = int(max(0.0, x - PAD * w) * width)
    top = int(max(0.0, y - PAD * h) * height)
    # round(), not ceil(): 0.55 * 400 is 220.00000000000003 in floating point
    right = max(left + 1, round(min(1.0, x + w + PAD * w) * width))
    bottom = max(top + 1, round(min(1.0, y + h + PAD * h) * height))
    piece = image.crop((left, top, right, bottom))
    piece.thumbnail((CROP_SIDE, CROP_SIDE))
    out = io.BytesIO()
    piece.convert("RGB").save(out, "JPEG", quality=90)
    return out.getvalue()


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (math.hypot(*a) * math.hypot(*b))


def colour_of(vector: list[float], species: str, config: dict) -> str | None:
    """Zero-shot colour: the colour word whose text embedding is closest to
    the crop's. The same model as the crop, so there's no second model."""
    if not COLOURS:
        return None
    key = (config["embedding_model"], species)
    if key not in _colour_vectors:  # once per instance per species
        _colour_vectors[key] = {
            colour: embed.embed_text(f"a photo of a {colour} {species}", config)
            for colour in COLOURS
        }
    texts = _colour_vectors[key]
    return max(texts, key=lambda colour: cosine(vector, texts[colour]))


def breed_of(labels: list[dict], species: str) -> str | None:
    """The most confident breed label under this species, or None. Breeds
    often score only 50-60, so request_min_confidence is their only threshold.
    ponytail: the label describes the photo, not a box, so two dogs in a photo
    share one breed; a breed per box would need a breed model."""
    breeds = [
        label
        for label in labels
        if species in [parent.lower() for parent in label["parents"]]
        and label["name"].lower() not in NOT_BREEDS
    ]
    if not breeds:
        return None
    return max(breeds, key=lambda label: label["confidence"])["name"]


def pets(image_bytes: bytes, labels: list[dict], config: dict) -> list[dict]:
    """One entry per cat or dog in the photo, with its embedding. A photo
    with no pets costs no Pillow decode and no Vertex AI call."""
    found = pet_boxes(labels, config)
    if not found:
        return []
    try:
        # Rekognition's boxes are for the photo after EXIF rotation, and
        # originals under 5 MB reach it with their EXIF intact.
        image = ImageOps.exif_transpose(Image.open(io.BytesIO(image_bytes)))
    except (OSError, Image.DecompressionBombError) as error:
        raise BadImage(str(error)) from error
    result = []
    for species, box in found:
        vector = embed.embed_image(crop(image, box), config)
        result.append(
            {
                "species": species,
                "colour": colour_of(vector, species, config),
                "breed": breed_of(labels, species),
                "embedding": vector,
                "bbox": box,  # Rekognition's box, unpadded
            }
        )
    return result
