"""Tests mock Google's token check and SNS; nothing here touches either cloud."""

import base64
import json
from unittest import mock

with mock.patch("boto3.client"):
    import app

DOMAIN = "abc123.lambda-url.ap-southeast-2.on.aws"
GOOD_CLAIMS = {
    "iss": "https://accounts.google.com",
    "aud": f"https://{DOMAIN}/",
    "email": app.PUSH_ACCOUNT,
    "email_verified": "true",
}
MESSAGE = {
    "file_id": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
    "file_type": "image",
    "tags": {"fox": 2, "cat": 1},
    "added": ["fox"],
    "uploaded_at": "2026-10-26T09:43:00Z",
}


def push(message=MESSAGE, token="google-token"):
    """A Pub/Sub push as the Lambda function URL delivers it."""
    data = base64.b64encode(json.dumps(message).encode()).decode()
    body = json.dumps(
        {"message": {"data": data, "messageId": "1"}, "subscription": "s"}
    )
    headers = {"authorization": f"Bearer {token}"} if token else {}
    return {
        "headers": headers,
        "body": body,
        "requestContext": {"domainName": DOMAIN},
    }


def run(event, claims=GOOD_CLAIMS):
    app.sns.reset_mock()
    with mock.patch.object(app, "google_claims", return_value=claims):
        return app.handler(event, None)


def test_valid_push_publishes_with_tag_attribute():
    assert run(push()) == {"statusCode": 204}
    kwargs = app.sns.publish.call_args.kwargs
    assert kwargs["MessageAttributes"]["tags"] == {
        "DataType": "String.Array",
        "StringValue": '["fox"]',
    }
    assert "fox (2)" in kwargs["Message"]
    assert "https://storage" not in kwargs["Message"]


def test_missing_token_is_rejected():
    assert run(push(token=None)) == {"statusCode": 401}
    app.sns.publish.assert_not_called()


def test_token_google_rejects_is_rejected():
    assert run(push(), claims=None) == {"statusCode": 401}
    app.sns.publish.assert_not_called()


def test_token_for_another_account_is_rejected():
    claims = {
        **GOOD_CLAIMS,
        "email": "someone-else@example.iam.gserviceaccount.com",
    }
    assert run(push(), claims=claims) == {"statusCode": 401}


def test_token_for_another_audience_is_rejected():
    claims = {**GOOD_CLAIMS, "aud": "https://evil.example.com/"}
    assert run(push(), claims=claims) == {"statusCode": 401}


def test_malformed_message_is_dropped_not_retried():
    event = push()
    event["body"] = json.dumps(
        {"message": {"data": base64.b64encode(b"nope").decode()}}
    )
    assert run(event) == {"statusCode": 204}
    app.sns.publish.assert_not_called()


def test_subject_names_every_added_tag():
    subject, _ = app.email(
        {
            **MESSAGE,
            "tags": {"feral pig": 1, "cane toad": 3},
            "added": ["cane toad", "feral pig"],
        }
    )
    assert subject == "EcoGuard alert: cane toad, feral pig"
