"""Tests for ecoguard_ml.detect. No cloud calls: Rekognition responses come
from the bake-off cache or are written out by hand."""

import io
import os
import json
import sys
from pathlib import Path
from unittest import mock

import pytest
from PIL import Image

from ecoguard_ml import BadImage, detect

REPO = Path(__file__).resolve().parents[3]
MODEL_JSON = REPO / "functions" / "ml" / "config" / "model.json"
RAW = REPO / "tools" / "testset" / "data" / "rekognition_raw.jsonl"
CONFIG = json.loads(MODEL_JSON.read_text())


def label(name, confidence, instances=(), parents=("Animal",)):
    return {
        "name": name,
        "confidence": confidence,
        "instances": list(instances),
        "parents": list(parents),
    }


# ---------- the sample set (Gate 2) ----------


def test_same_tags_as_the_bake_off_on_every_test_photo():
    """Production counting = the rule the bake-off scored, with the numbers
    from config/model, on the 140 cached Rekognition responses."""
    sys.path.insert(0, str(REPO / "tools" / "testset"))
    import bakeoff

    assert CONFIG["box_min_confidence"] == bakeoff.BOX_MIN
    records = [json.loads(line) for line in RAW.read_text().splitlines()]
    assert len(records) >= 130
    for record in records:
        expected = bakeoff.predict(
            record,
            detect.LABEL_MAP,
            CONFIG["thresholds"],
            CONFIG["default_threshold"],
            borrow=CONFIG["borrow_boxes"],
        )
        actual = detect.count_tags(record["labels"], CONFIG)
        assert actual == expected, record["filename"]


# ---------- counting rule ----------


def test_counts_boxes_on_the_tags_own_label():
    labels = [label("Pig", 97, instances=[96, 88, 40])]
    # the 40% box is under box_min_confidence (50)
    assert detect.count_tags(labels, CONFIG) == {"feral pig": 2}


def test_label_with_no_boxes_counts_one():
    config = {**CONFIG, "borrow_boxes": False}
    assert detect.count_tags([label("Fox", 95)], config) == {"fox": 1}


def test_label_under_its_tag_threshold_is_dropped():
    # cane toad threshold 70, fox 90
    labels = [label("Toad", 69.9), label("Fox", 89)]
    assert detect.count_tags(labels, CONFIG) == {}


def test_unmapped_labels_are_dropped():
    labels = [label("Kangaroo", 99, instances=[99]), label("Frog", 99)]
    assert detect.count_tags(labels, CONFIG) == {}


def test_labels_match_case_insensitively():
    assert detect.count_tags([label("RED FOX", 95)], CONFIG) == {"fox": 1}


def test_tag_without_boxes_borrows_another_animals_boxes():
    labels = [
        label("Toad", 93),
        label("Lizard", 99, instances=[99, 97, 60]),
    ]
    assert detect.count_tags(labels, CONFIG) == {"cane toad": 3}


def test_no_borrowing_when_config_turns_it_off():
    labels = [label("Toad", 93), label("Lizard", 99, instances=[99, 97])]
    config = {**CONFIG, "borrow_boxes": False}
    assert detect.count_tags(labels, config) == {"cane toad": 1}


def test_never_borrows_boxes_another_tag_is_using():
    labels = [
        label("Toad", 93),
        label("Pig", 97, instances=[96, 95]),
    ]
    assert detect.count_tags(labels, CONFIG) == {"cane toad": 1, "feral pig": 2}


def test_threshold_comes_from_config():
    labels = [label("Toad", 75)]
    assert detect.count_tags(labels, CONFIG) == {"cane toad": 1}
    stricter = {
        **CONFIG,
        "thresholds": {**CONFIG["thresholds"], "cane toad": 80},
    }
    assert detect.count_tags(labels, stricter) == {}


# ---------- image preparation ----------


def image_bytes(fmt, size=(64, 48)):
    out = io.BytesIO()
    Image.new("RGB", size, (200, 120, 40)).save(out, fmt)
    return out.getvalue()


@pytest.mark.parametrize("fmt", ["JPEG", "PNG"])
def test_jpeg_and_png_under_5_mb_are_sent_unchanged(fmt):
    """As in the bake-off: re-encoding can change Rekognition's labels."""
    original = image_bytes(fmt)
    assert detect.prepare_image(original) is original


def test_webp_becomes_jpeg():
    prepared = detect.prepare_image(image_bytes("WEBP"))
    assert Image.open(io.BytesIO(prepared)).format == "JPEG"


def test_animal_labels_lists_what_counts_came_from():
    labels = [
        label("Dog", 84.78, instances=[84.78, 76.01]),
        label("Wheel", 83.9, instances=[83.9], parents=["Machine"]),
        label("Toad", 93.2, parents=[]),
    ]
    assert detect.animal_labels(labels) == [
        "Dog 84.8 (2 boxes)",
        "Toad 93.2 (0 boxes)",
    ]


def test_images_over_5_mb_shrink_to_a_jpeg_under_5_mb():
    # random pixels don't compress, so this PNG is about 18 MB
    noisy = Image.frombytes("RGB", (3000, 2000), os.urandom(3000 * 2000 * 3))
    out = io.BytesIO()
    noisy.save(out, "PNG")
    assert out.tell() > detect.MAX_BYTES

    prepared = detect.prepare_image(out.getvalue())
    image = Image.open(io.BytesIO(prepared))
    assert image.format == "JPEG"
    assert image.size == (2048, 1365)
    assert len(prepared) <= detect.MAX_BYTES


def test_bytes_that_are_not_an_image_raise_bad_image():
    with pytest.raises(BadImage):
        detect.prepare_image(b"not an image")


# ---------- analyse ----------


def test_analyse_runs_the_detector_named_in_config(monkeypatch):
    fake = mock.Mock(return_value=[label("Cat", 98, instances=[97, 92])])
    monkeypatch.setitem(detect.DETECTORS, "rekognition", fake)
    tags, labels = detect.analyse(image_bytes("JPEG"), CONFIG)
    assert tags == {"cat": 2}
    assert labels == fake.return_value
    sent_bytes, sent_config = fake.call_args.args
    assert Image.open(io.BytesIO(sent_bytes)).format == "JPEG"
    assert sent_config is CONFIG


def test_analyse_rejects_an_unknown_detector():
    with pytest.raises(ValueError, match="unknown detector"):
        detect.analyse(image_bytes("JPEG"), {**CONFIG, "detector": "yolo"})


# ---------- config/model ----------


def fake_db(config):
    db = mock.Mock()
    db.document.return_value.get.return_value = mock.Mock(
        exists=config is not None, to_dict=lambda: config
    )
    return db


def test_config_is_read_once_then_again_after_five_minutes():
    db = fake_db(CONFIG)
    now = [1000.0]
    model_config = detect.ModelConfig(db, clock=lambda: now[0])

    assert model_config.get() == CONFIG
    now[0] += 299
    model_config.get()
    assert db.document.return_value.get.call_count == 1
    now[0] += 1
    model_config.get()
    assert db.document.return_value.get.call_count == 2
    db.document.assert_called_with("config/model")


def test_missing_config_says_how_to_push_it():
    with pytest.raises(RuntimeError, match="push_model_config"):
        detect.ModelConfig(fake_db(None)).get()
