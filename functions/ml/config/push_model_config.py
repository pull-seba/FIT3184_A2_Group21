#!/usr/bin/env python3
"""
Member 3 - write functions/ml/config/model.json to Firestore `config/model`.

The tagging service re-reads `config/model` every few minutes, so changing a
threshold, the detector region or the embedding model is: edit model.json,
bump "version", run this script. No code change (rubric 2.1.3).

  python3 functions/ml/config/push_model_config.py --dry-run   # check only
  python3 functions/ml/config/push_model_config.py             # write

Needs `pip install google-cloud-firestore` and Application Default
Credentials (`gcloud auth application-default login`).
"""

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODEL_JSON = HERE / "model.json"
TAGS_JSON = HERE.parents[2] / "shared" / "tags.json"
PROJECT = "ecoguard-g21"
REQUIRED = {
    "version",
    "detector",
    "detector_region",
    "request_min_confidence",
    "thresholds",
    "default_threshold",
    "box_min_confidence",
    "borrow_boxes",
    "label_map_version",
    "chained_classifier",
    "embedding_model",
    "embedding_dimension",
    "embedding_location",
}


def validate(config, tags):
    """Returns a list of problems; empty means the config is safe to push."""
    problems = []
    missing = REQUIRED - set(config)
    if missing:
        problems.append(f"missing fields: {', '.join(sorted(missing))}")
    names = {t["name"] for t in tags["tags"]}
    unknown = set(config.get("thresholds", {})) - names
    if unknown:
        problems.append(f"thresholds for unknown tags: {sorted(unknown)}")
    for tag, value in config.get("thresholds", {}).items():
        if not 0 <= value <= 100:
            problems.append(f"threshold for {tag} must be 0-100, got {value}")
    if config.get("label_map_version") != tags.get("version"):
        problems.append(
            f"label_map_version {config.get('label_map_version')} != "
            f"shared/tags.json version {tags.get('version')}"
        )
    if not 1 <= config.get("embedding_dimension", 0) <= 2048:
        problems.append("embedding_dimension must be 1-2048 (Firestore limit)")
    return problems


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--project", default=PROJECT)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    config = json.loads(MODEL_JSON.read_text(encoding="utf-8"))
    tags = json.loads(TAGS_JSON.read_text(encoding="utf-8"))
    problems = validate(config, tags)
    if problems:
        sys.exit("Not pushed:\n- " + "\n- ".join(problems))
    print(json.dumps(config, indent=2))
    if args.dry_run:
        print("Valid. Dry run, nothing written.")
        return

    from google.cloud import firestore

    db = firestore.Client(project=args.project)
    db.document("config/model").set(
        {**config, "updated_at": firestore.SERVER_TIMESTAMP}
    )
    print(f"Wrote config/model version {config['version']} to {args.project}")


if __name__ == "__main__":
    main()
