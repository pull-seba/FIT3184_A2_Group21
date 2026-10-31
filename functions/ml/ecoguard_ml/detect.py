"""Image bytes -> EcoGuard tags with counts. Owner: member 3. Rubric 2.1.3.

The counting rule is the one the bake-off chose (tools/testset/bakeoff.py,
decision of 29 Oct), and every number in it comes from config/model, so
thresholds or the detector change without a code change. tests/test_detect.py
checks this file gives the same tags as the bake-off on all 140 test photos.
"""

import io
import json
from pathlib import Path

from PIL import Image, ImageOps

from ecoguard_ml import BadImage, rekognition

# Rekognition reads only JPEG or PNG up to 5 MB, and uploads can be WebP or up
# to 20 MB. Those are converted to a 2048 px JPEG at quality 90, which is well
# under 5 MB, the same as the bake-off did for its oversized photos.
REKOGNITION_FORMATS = {"JPEG", "PNG"}
MAX_BYTES = 5 * 1024 * 1024
MAX_SIDE = 2048

# config/model's "detector" names one of these. A new model is a new entry
# here plus a config change; thresholds alone need no code change.
DETECTORS = {"rekognition": rekognition.detect_labels}


def _load_label_map() -> dict[str, str]:
    """model_label_map from shared/tags.json, keys lowercased: labels are
    matched case-insensitively (decision of 28 Oct)."""
    here = Path(__file__).parent
    path = here / "tags.json"  # the copy made at deploy
    if not path.exists():
        # In the repo. Only looked up here: deployed, the package sits at
        # /workspace/ecoguard_ml, which has no folder two levels up.
        path = here.parents[2] / "shared" / "tags.json"
    label_map = json.loads(path.read_text())["model_label_map"]
    return {label.lower(): tag for label, tag in label_map.items()}


LABEL_MAP = _load_label_map()


def prepare_image(data: bytes) -> bytes:
    """Bytes Rekognition accepts for any accepted upload (JPEG, PNG, WebP,
    up to 20 MB). Raises BadImage if Pillow can't read it.

    A JPEG or PNG under 5 MB is sent unchanged, as in the bake-off: weak
    labels whose boxes a count borrows (Dog 85% on two foxes) can vanish
    when a photo is re-encoded, so thresholds only hold for original bytes.
    """
    try:
        image = Image.open(io.BytesIO(data))  # reads the header only
        if image.format in REKOGNITION_FORMATS and len(data) <= MAX_BYTES:
            return data
        image = ImageOps.exif_transpose(image)  # phone photos store rotation
        image.thumbnail((MAX_SIDE, MAX_SIDE))
        out = io.BytesIO()
        image.convert("RGB").save(out, "JPEG", quality=90)
    except (OSError, Image.DecompressionBombError) as error:
        # The bytes are already in memory, so an OSError here is Pillow
        # failing to decode (UnidentifiedImageError, truncated file).
        raise BadImage(str(error)) from error
    return out.getvalue()


def animal_labels(labels: list[dict]) -> list[str]:
    """The labels a count can come from, for the log: "Dog 84.8 (2 boxes)".
    Shows why a photo got its count without logging the image."""
    return [
        f"{label['name']} {label['confidence']:.1f} "
        f"({len(label['instances'])} boxes)"
        for label in labels
        if "Animal" in label["parents"] or label["name"].lower() in LABEL_MAP
    ]


def count_tags(
    labels: list[dict], config: dict, label_map: dict[str, str] = LABEL_MAP
) -> dict[str, int]:
    """{tag: count} for one image from its detector labels.

    A label counts when it maps to a tag and its confidence reaches that
    tag's threshold. The count is the number of boxes on the label with box
    confidence of at least box_min_confidence, else 1. With borrow_boxes, a
    tag with no boxes of its own takes the largest box count on another
    animal label that no tag is using: Rekognition often boxes the right
    animal under the wrong name ("Lizard" on toads, "Dog" on a fox).
    """
    thresholds = config["thresholds"]
    box_min = config["box_min_confidence"]

    def boxes(label):
        return sum(1 for c in label["instances"] if c >= box_min)

    tags = {}
    own_boxes = {}
    for label in labels:
        tag = label_map.get(label["name"].lower())
        if not tag:
            continue  # unmapped labels are dropped
        if label["confidence"] < thresholds.get(
            tag, config["default_threshold"]
        ):
            continue
        tags[tag] = max(tags.get(tag, 0), boxes(label) or 1)
        own_boxes[tag] = max(own_boxes.get(tag, 0), boxes(label))

    if config["borrow_boxes"]:
        spare = max(
            (
                boxes(label)
                for label in labels
                if "Animal" in label["parents"]
                and label_map.get(label["name"].lower()) not in tags
            ),
            default=0,
        )
        for tag in tags:
            if not own_boxes[tag] and spare:
                tags[tag] = spare
    return tags


def analyse(data: bytes, config: dict) -> tuple[dict[str, int], list[dict]]:
    """Tags for one image's bytes, plus the detector's labels. Nothing is
    stored: search_by_file uses this on query photos too."""
    detector = DETECTORS.get(config["detector"])
    if detector is None:
        raise ValueError(
            f"config/model names unknown detector {config['detector']!r}"
        )
    labels = detector(prepare_image(data), config)
    return count_tags(labels, config), labels


def model_config(db) -> dict:
    snapshot = db.document("config/model").get()
    if not snapshot.exists:
        raise RuntimeError(
            "config/model is missing: run "
            "functions/ml/config/push_model_config.py"
        )
    return snapshot.to_dict()
