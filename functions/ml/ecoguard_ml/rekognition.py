"""Amazon Rekognition DetectLabels from GCP, with no AWS keys anywhere.
Owner: member 3. Cross-cloud link 4 in docs/architecture.md.

On Cloud Run, REKOGNITION_ROLE_ARN is set. The function asks the metadata
server for a Google ID token for its own service account, and AWS STS swaps
it (AssumeRoleWithWebIdentity) for one-hour credentials on a role that may
only call rekognition:DetectLabels. The role trusts only our functions'
service accounts: aws/iam/rekognition-detect-trust.json.

Without REKOGNITION_ROLE_ARN (on a laptop), boto3's usual credential chain is
used, for example AWS_PROFILE=ecoguard, so local runs need no federation.

Image bytes are sent for analysis only; Rekognition stores nothing.
"""

import os
import time

import boto3
import google.auth.transport.requests
import google.oauth2.id_token
from botocore import UNSIGNED
from botocore.config import Config
from botocore.exceptions import ClientError

from ecoguard_ml import BadImage

# Rekognition errors meaning this image can't be tagged: retrying won't help.
BAD_IMAGE_ERRORS = {
    "InvalidImageFormatException",
    "ImageTooLargeException",
    "InvalidParameterException",
}
ROLE_ARN = os.environ.get("REKOGNITION_ROLE_ARN")
REFRESH_EARLY_S = 300  # swap credentials five minutes before they expire

_clients = {}  # region -> (Rekognition client, credentials expiry)


def _federated_client(region: str):
    token = google.oauth2.id_token.fetch_id_token(
        google.auth.transport.requests.Request(), audience=ROLE_ARN
    )
    # AssumeRoleWithWebIdentity is called without AWS credentials (the
    # Google token is the proof of identity), so the request isn't signed.
    sts = boto3.client(
        "sts", region_name=region, config=Config(signature_version=UNSIGNED)
    )
    credentials = sts.assume_role_with_web_identity(
        RoleArn=ROLE_ARN,
        # Shows in AWS CloudTrail which function called. K_SERVICE is set by
        # Cloud Run to the service name.
        RoleSessionName=os.environ.get("K_SERVICE", "ecoguard-ml"),
        WebIdentityToken=token,
    )["Credentials"]
    client = boto3.client(
        "rekognition",
        region_name=region,
        aws_access_key_id=credentials["AccessKeyId"],
        aws_secret_access_key=credentials["SecretAccessKey"],
        aws_session_token=credentials["SessionToken"],
    )
    return client, credentials["Expiration"].timestamp()


def client(region: str):
    """A Rekognition client for the region, reused until its credentials
    are about to expire."""
    cached = _clients.get(region)
    if cached and time.time() < cached[1] - REFRESH_EARLY_S:
        return cached[0]
    if ROLE_ARN:
        _clients[region] = _federated_client(region)
    else:
        _clients[region] = (
            boto3.client("rekognition", region_name=region),
            float("inf"),
        )
    return _clients[region][0]


def normalise(label: dict) -> dict:
    """One Rekognition label in the shape the bake-off cached
    (tools/testset/data/rekognition_raw.jsonl)."""
    return {
        "name": label["Name"],
        "confidence": label["Confidence"],
        "instances": [i["Confidence"] for i in label.get("Instances", [])],
        "parents": [p["Name"] for p in label.get("Parents", [])],
    }


def detect_labels(image: bytes, config: dict) -> list[dict]:
    """Rekognition's labels for JPEG bytes, region and minimum confidence
    from config/model. Per-tag thresholds are applied later, in detect."""
    try:
        response = client(config["detector_region"]).detect_labels(
            Image={"Bytes": image},
            MaxLabels=100,
            MinConfidence=config["request_min_confidence"],
        )
    except ClientError as error:
        if error.response["Error"]["Code"] in BAD_IMAGE_ERRORS:
            raise BadImage(str(error)) from error
        raise  # throttling, access denied and so on: the caller retries
    return [normalise(label) for label in response["Labels"]]
