"""Tests mock every cloud client; nothing here touches the shared project."""

import base64
import json
from unittest import mock

import flask

with mock.patch("google.cloud.firestore.Client"):
    import main

app = flask.Flask(__name__)


def gateway_headers(sub="test-user", email="test@example.com"):
    """What API Gateway adds after it verifies a Cognito ID token."""
    raw = json.dumps({"sub": sub, "email": email}).encode()
    return {
        "X-Apigateway-Api-Userinfo": base64.urlsafe_b64encode(raw)
        .decode()
        .rstrip("=")
    }


def call(json_body=None, headers=None, data=None):
    with app.test_request_context(
        method="POST", json=json_body, data=data, headers=headers or {}
    ):
        return main.handler(flask.request)


def test_rejects_request_without_gateway_claims():
    _, status, _ = call({"anything": 1})
    assert status == 401


def test_rejects_body_that_is_not_json():
    _, status, _ = call(data="not json", headers=gateway_headers())
    assert status == 400


def test_accepts_gateway_request():
    body, status, _ = call({}, headers=gateway_headers())
    assert status == 200
    assert json.loads(body) == {}
