"""Tests for ecoguard_ml.rekognition with every AWS and Google call faked."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import pytest
from botocore.exceptions import ClientError

from ecoguard_ml import BadImage, rekognition

CONFIG = json.loads(
    (Path(__file__).resolve().parents[1] / "config" / "model.json").read_text()
)
ROLE = "arn:aws:iam::123456789012:role/ecoguard-rekognition-detect"

RESPONSE = {
    "Labels": [
        {
            "Name": "Fox",
            "Confidence": 96.5,
            "Instances": [{"Confidence": 95.1}],
            "Parents": [{"Name": "Animal"}, {"Name": "Mammal"}],
        },
        {"Name": "Grass", "Confidence": 80.0, "Instances": [], "Parents": []},
    ]
}


@pytest.fixture(autouse=True)
def no_cached_clients(monkeypatch):
    monkeypatch.setattr(rekognition, "_clients", {})


def test_labels_keep_the_bake_off_shape(monkeypatch):
    client = mock.Mock()
    client.detect_labels.return_value = RESPONSE
    monkeypatch.setattr(rekognition, "client", lambda region: client)

    labels = rekognition.detect_labels(b"jpeg", CONFIG)

    assert labels[0] == {
        "name": "Fox",
        "confidence": 96.5,
        "instances": [95.1],
        "parents": ["Animal", "Mammal"],
    }
    assert labels[1]["instances"] == []
    client.detect_labels.assert_called_once_with(
        Image={"Bytes": b"jpeg"},
        MaxLabels=100,
        MinConfidence=CONFIG["request_min_confidence"],
    )


def client_error(code):
    return ClientError(
        {"Error": {"Code": code, "Message": "x"}}, "DetectLabels"
    )


def test_an_image_rekognition_cant_read_is_a_bad_image(monkeypatch):
    client = mock.Mock()
    client.detect_labels.side_effect = client_error(
        "InvalidImageFormatException"
    )
    monkeypatch.setattr(rekognition, "client", lambda region: client)
    with pytest.raises(BadImage):
        rekognition.detect_labels(b"jpeg", CONFIG)


def test_other_aws_errors_are_raised_for_a_retry(monkeypatch):
    client = mock.Mock()
    client.detect_labels.side_effect = client_error("ThrottlingException")
    monkeypatch.setattr(rekognition, "client", lambda region: client)
    with pytest.raises(ClientError):
        rekognition.detect_labels(b"jpeg", CONFIG)


def test_without_a_role_uses_the_local_aws_credentials(monkeypatch):
    monkeypatch.setattr(rekognition, "ROLE_ARN", None)
    with mock.patch.object(rekognition.boto3, "client") as boto_client:
        rekognition.client("us-east-1")
        rekognition.client("us-east-1")
    boto_client.assert_called_once_with("rekognition", region_name="us-east-1")


def federation_fakes(expires_in):
    sts = mock.Mock()
    sts.assume_role_with_web_identity.return_value = {
        "Credentials": {
            "AccessKeyId": "ASIA-temp",
            "SecretAccessKey": "temp-secret",
            "SessionToken": "temp-session",
            "Expiration": datetime.now(timezone.utc) + expires_in,
        }
    }

    def boto_client(service, **kwargs):
        return (
            sts if service == "sts" else mock.Mock(name=service, kwargs=kwargs)
        )

    return sts, boto_client


def test_on_cloud_run_swaps_a_google_token_for_temporary_aws_credentials(
    monkeypatch,
):
    monkeypatch.setattr(rekognition, "ROLE_ARN", ROLE)
    monkeypatch.setenv("K_SERVICE", "tagging")
    sts, boto_client = federation_fakes(timedelta(hours=1))
    with (
        mock.patch.object(
            rekognition.google.oauth2.id_token,
            "fetch_id_token",
            return_value="google-id-token",
        ) as fetch,
        mock.patch.object(rekognition.boto3, "client", side_effect=boto_client),
    ):
        client = rekognition.client("us-east-1")
        assert rekognition.client("us-east-1") is client  # reused

    assert fetch.call_args.kwargs == {"audience": ROLE}
    sts.assume_role_with_web_identity.assert_called_once_with(
        RoleArn=ROLE,
        RoleSessionName="tagging",
        WebIdentityToken="google-id-token",
    )
    assert client.kwargs["aws_session_token"] == "temp-session"


def test_credentials_are_renewed_before_they_expire(monkeypatch):
    monkeypatch.setattr(rekognition, "ROLE_ARN", ROLE)
    sts, boto_client = federation_fakes(timedelta(minutes=4))
    with (
        mock.patch.object(
            rekognition.google.oauth2.id_token,
            "fetch_id_token",
            return_value="t",
        ),
        mock.patch.object(rekognition.boto3, "client", side_effect=boto_client),
    ):
        rekognition.client("us-east-1")
        rekognition.client("us-east-1")
    # four minutes left is inside the five-minute margin, so it swaps again
    assert sts.assume_role_with_web_identity.call_count == 2
