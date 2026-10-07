"""Tagging Lambda: S3 upload -> ML detection -> DynamoDB record (rubric 2.1.3).

The model settings and label mapping are read from S3 at runtime, so switching
model, confidence threshold or species mapping needs no code change.
"""
import hashlib
import json
import os
import time
import urllib.parse
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from botocore.exceptions import ClientError

s3 = boto3.client("s3")
rekognition = boto3.client("rekognition")
table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])

CONFIG_BUCKET = os.environ["CONFIG_BUCKET"]
CONFIG_TTL_SECONDS = 60  # config changes take effect within a minute, no redeploy
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv"}

_config_cache = {"loaded_at": 0.0, "model": None, "labels": None}


def _read_json(key):
    return json.loads(s3.get_object(Bucket=CONFIG_BUCKET, Key=key)["Body"].read())


def load_config():
    if time.time() - _config_cache["loaded_at"] > CONFIG_TTL_SECONDS:
        _config_cache["model"] = _read_json(os.environ["MODEL_CONFIG_KEY"])
        _config_cache["labels"] = _read_json(os.environ["LABEL_MAP_KEY"])
        _config_cache["loaded_at"] = time.time()
    return _config_cache["model"], _config_cache["labels"]


def detect_rekognition(bucket, key, model_cfg, label_map):
    """Returns ({tag: count}, raw_labels). Count = number of bounding boxes, min 1."""
    response = rekognition.detect_labels(
        Image={"S3Object": {"Bucket": bucket, "Name": key}},
        MaxLabels=model_cfg.get("max_labels", 50),
        MinConfidence=model_cfg.get("min_confidence", 70),
    )
    tags = {}
    raw_labels = []
    for label in response["Labels"]:
        raw_labels.append({"name": label["Name"], "confidence": Decimal(str(round(label["Confidence"], 1)))})
        tag = label_map.get(label["Name"])
        if tag:
            count = max(len(label.get("Instances", [])), 1)
            # Several labels can map to one tag (Pig, Boar -> feral pig); keep the highest count.
            tags[tag] = max(tags.get(tag, 0), count)
    return tags, raw_labels


# Add new models here (e.g. "yolo") and select them in config/model-config.json.
DETECTORS = {"rekognition": detect_rekognition}


def handler(event, context):
    for record in event["Records"]:
        bucket = record["s3"]["bucket"]["name"]
        key = urllib.parse.unquote_plus(record["s3"]["object"]["key"])
        process(bucket, key)


def process(bucket, key):
    extension = os.path.splitext(key)[1].lower()
    if extension in IMAGE_EXTENSIONS:
        file_type = "image"
    elif extension in VIDEO_EXTENSIONS:
        file_type = "video"
    else:
        print(f"Skipping unsupported file type: {key}")
        return

    obj = s3.get_object(Bucket=bucket, Key=key)
    digest = hashlib.sha256()
    for chunk in obj["Body"].iter_chunks(1024 * 1024):
        digest.update(chunk)

    item = {
        "file_id": digest.hexdigest(),
        "file_type": file_type,
        "s3_key": key,
        "file_url": f"https://{bucket}.s3.amazonaws.com/{urllib.parse.quote(key)}",
        "thumbnail_url": None,  # filled in by the thumbnail function
        "tags": {},
        "uploaded_by": obj["Metadata"].get("uploaded-by", "unknown"),
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    }

    if file_type == "image":
        model_cfg, label_map = load_config()
        detect = DETECTORS[model_cfg["provider"]]
        item["tags"], item["labels"] = detect(bucket, key, model_cfg, label_map)
        item["model"] = f'{model_cfg["provider"]}:{model_cfg.get("model_version", "latest")}'
    # Videos are tagged later from extracted frames (1 frame / 10 s, backend/gcp/video_frames).

    try:
        table.put_item(Item=item, ConditionExpression="attribute_not_exists(file_id)")
        print(f"Tagged {key}: {item['tags']}")
    except ClientError as error:
        if error.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        # Safety net only - the upload API should reject duplicates before they reach S3.
        print(f"Duplicate content, record already exists: {key}")
