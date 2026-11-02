"""Tests for ecoguard_ml.sightings. No cloud calls: Vertex AI is mocked."""

import io
from types import SimpleNamespace
from unittest import mock

import pytest
from PIL import Image

from ecoguard_ml import BadImage, sightings

CONFIG = {
    "thresholds": {"cat": 90, "dog": 95, "fox": 90},
    "default_threshold": 95,
    "box_min_confidence": 50,
    "embedding_model": "multimodalembedding@001",
}


def label(name, confidence, boxes=(), instances=None):
    """A label in rekognition.normalise's shape."""
    boxes = [list(b) for b in boxes]
    if instances is None:
        instances = [99.0] * len(boxes)
    return {
        "name": name,
        "confidence": confidence,
        "instances": instances,
        "boxes": boxes,
        "parents": ["Animal"],
    }


def jpeg(size=(400, 300), exif=None):
    out = io.BytesIO()
    image = Image.new("RGB", size, "orange")
    image.save(out, "JPEG", **({"exif": exif} if exif else {}))
    return out.getvalue()


def size_of(jpeg_bytes):
    return Image.open(io.BytesIO(jpeg_bytes)).size


@pytest.fixture(autouse=True)
def embed(monkeypatch):
    """Every crop embeds to [1, 0, 0]; "ginger" text is the closest."""
    monkeypatch.setattr(sightings, "_colour_vectors", {})

    def text(words, config):
        return [1.0, 0.1, 0.0] if " ginger " in words else [0.0, 1.0, 0.0]

    fake = SimpleNamespace(
        image=mock.Mock(return_value=[1.0, 0.0, 0.0]),
        text=mock.Mock(side_effect=text),
    )
    monkeypatch.setattr(sightings.embed, "embed_image", fake.image)
    monkeypatch.setattr(sightings.embed, "embed_text", fake.text)
    return fake


# ---------- which labels become sightings ----------


def test_two_cat_boxes_give_two_pets(embed):
    boxes = [(0.1, 0.1, 0.3, 0.3), (0.6, 0.5, 0.2, 0.3)]
    found = sightings.pets(jpeg(), [label("Cat", 97.0, boxes)], CONFIG)
    assert [p["species"] for p in found] == ["cat", "cat"]
    assert [p["bbox"] for p in found] == [list(b) for b in boxes]
    assert all(p["breed"] is None for p in found)
    assert found[0]["embedding"] == [1.0, 0.0, 0.0]
    assert embed.image.call_count == 2


def test_a_box_under_box_min_confidence_is_skipped():
    boxes = [(0.1, 0.1, 0.3, 0.3), (0.6, 0.5, 0.2, 0.3)]
    labels = [label("Cat", 97.0, boxes, instances=[99.0, 30.0])]
    found = sightings.pets(jpeg(), labels, CONFIG)
    assert [p["bbox"] for p in found] == [[0.1, 0.1, 0.3, 0.3]]


def test_cat_under_its_threshold_gives_none(embed):
    labels = [label("Cat", 85.0, [(0.1, 0.1, 0.3, 0.3)])]
    assert sightings.pets(jpeg(), labels, CONFIG) == []
    embed.image.assert_not_called()


def test_dog_uses_the_dog_threshold():
    labels = [label("Dog", 96.0, [(0.2, 0.2, 0.5, 0.5)])]
    assert [p["species"] for p in sightings.pets(jpeg(), labels, CONFIG)] == [
        "dog"
    ]
    labels = [label("Dog", 94.0, [(0.2, 0.2, 0.5, 0.5)])]
    assert sightings.pets(jpeg(), labels, CONFIG) == []


def test_pet_label_with_no_boxes_gives_one_whole_image_sighting():
    found = sightings.pets(jpeg(), [label("Cat", 97.0)], CONFIG)
    assert [p["bbox"] for p in found] == [[0.0, 0.0, 1.0, 1.0]]


def test_photo_with_no_pets_is_never_decoded_or_embedded(embed):
    labels = [label("Fox", 98.0, [(0.1, 0.1, 0.5, 0.5)])]
    # not an image at all: a fox photo must not even be opened
    assert sightings.pets(b"not an image", labels, CONFIG) == []
    embed.image.assert_not_called()


def test_unreadable_photo_with_a_cat_is_a_bad_image():
    with pytest.raises(BadImage):
        sightings.pets(b"not an image", [label("Cat", 97.0)], CONFIG)


# ---------- crops ----------


def test_crop_is_padded_by_ten_percent():
    image = Image.new("RGB", (400, 400))
    # 0.25-0.75 padded by 0.05 each side is 0.20-0.80: 240 px
    assert size_of(sightings.crop(image, [0.25, 0.25, 0.5, 0.5])) == (240, 240)


def test_crop_at_the_edge_is_clamped_to_the_photo():
    image = Image.new("RGB", (400, 300))
    width, height = size_of(sightings.crop(image, [0.95, 0.95, 0.1, 0.1]))
    assert 0 < width <= 400 and 0 < height <= 300


def test_big_crop_is_shrunk_to_512_px():
    image = Image.new("RGB", (2000, 1000))
    assert size_of(sightings.crop(image, [0.0, 0.0, 1.0, 1.0])) == (512, 256)


def test_crop_follows_exif_rotation(embed):
    """A 400 x 200 photo marked "rotate 90" is 200 x 400 upright, which is
    the photo Rekognition's boxes describe."""
    exif = Image.Exif()
    exif[0x0112] = 6  # Orientation: rotate 90 clockwise
    photo = jpeg((400, 200), exif=exif)
    sightings.pets(photo, [label("Cat", 97.0, [(0.0, 0.0, 1.0, 0.5)])], CONFIG)
    # top half of the upright photo, padded to 0.55 of its height
    assert size_of(embed.image.call_args.args[0]) == (200, 220)


# ---------- colour ----------


def test_colour_is_the_closest_colour_word(embed):
    found = sightings.pets(jpeg(), [label("Cat", 97.0)], CONFIG)
    assert found[0]["colour"] == "ginger"
    assert embed.text.call_args_list[0].args[0] == "a photo of a ginger cat"


def test_colour_words_are_embedded_once_per_species(embed):
    two = [label("Cat", 97.0, [(0.1, 0.1, 0.3, 0.3), (0.5, 0.5, 0.3, 0.3)])]
    sightings.pets(jpeg(), two, CONFIG)
    sightings.pets(jpeg(), two, CONFIG)
    assert embed.text.call_count == len(sightings.COLOURS)


def test_no_colour_list_gives_null_colour(monkeypatch, embed):
    monkeypatch.setattr(sightings, "COLOURS", [])
    found = sightings.pets(jpeg(), [label("Cat", 97.0)], CONFIG)
    assert found[0]["colour"] is None
    embed.text.assert_not_called()
