"""Tests mock SNS and the token exchange; nothing here touches AWS or GCP."""

import base64
import json
from unittest import mock

import flask
import pytest
from botocore.exceptions import ClientError

import main

app = flask.Flask(__name__)

EMAIL = "test@example.com"
ARN = "arn:aws:sns:us-east-1:111:ecoguard-tag-alerts:abc"


def gateway_headers(email=EMAIL):
    """What API Gateway adds after it verifies a Cognito ID token."""
    claims = {"sub": "test-user"}
    if email:
        claims["email"] = email
    raw = json.dumps(claims).encode()
    return {
        "X-Apigateway-Api-Userinfo": base64.urlsafe_b64encode(raw)
        .decode()
        .rstrip("=")
    }


def subscription(endpoint=EMAIL, arn=ARN, protocol="email"):
    return {
        "Protocol": protocol,
        "Endpoint": endpoint,
        "SubscriptionArn": arn,
    }


@pytest.fixture
def sns():
    """An SNS client whose topic has no subscribers yet."""
    client = mock.Mock()
    client.get_paginator.return_value.paginate.return_value = [
        {"Subscriptions": []}
    ]
    with mock.patch.object(main, "sns_client", return_value=client):
        yield client


def subscribers(client, *subscriptions):
    client.get_paginator.return_value.paginate.return_value = [
        {"Subscriptions": list(subscriptions)}
    ]


def call(method="GET", body=None, headers=None):
    with app.test_request_context(
        "/",
        method=method,
        json=body,
        headers=gateway_headers() if headers is None else headers,
    ):
        response = main.handler(flask.request)
    payload, status, _ = response
    return status, json.loads(payload) if payload else None


def test_preflight_needs_no_token():
    with app.test_request_context("/", method="OPTIONS"):
        _, status, headers = main.handler(flask.request)
    assert status == 204
    assert "PUT" in headers["Access-Control-Allow-Methods"]


def test_call_not_through_the_gateway_is_rejected(sns):
    assert call(headers={})[0] == 401
    sns.subscribe.assert_not_called()


def test_account_with_no_email_is_rejected(sns):
    status, body = call(headers=gateway_headers(email=None))
    assert status == 400
    assert body["error"]["code"] == "no_email"


def test_other_methods_are_rejected(sns):
    assert call(method="POST", body={"tags": []})[0] == 405


def test_get_with_no_subscription_returns_no_tags(sns):
    assert call() == (200, {"tags": []})


def test_get_returns_the_filter_policy_tags(sns):
    subscribers(sns, subscription())
    sns.get_subscription_attributes.return_value = {
        "Attributes": {"FilterPolicy": '{"tags": ["fox", "cane toad"]}'}
    }
    assert call() == (200, {"tags": ["cane toad", "fox"]})


def test_get_never_reads_someone_elses_subscription(sns):
    subscribers(sns, subscription(endpoint="other@example.com"))
    assert call() == (200, {"tags": []})
    sns.get_subscription_attributes.assert_not_called()


def test_get_ignores_non_email_subscribers_with_the_same_address(sns):
    subscribers(sns, subscription(protocol="email-json"))
    assert call() == (200, {"tags": []})


def test_email_matches_whatever_its_case(sns):
    subscribers(sns, subscription(endpoint="Test@Example.com"))
    sns.get_subscription_attributes.return_value = {
        "Attributes": {"FilterPolicy": '{"tags": ["fox"]}'}
    }
    assert call() == (200, {"tags": ["fox"]})


def test_get_while_unconfirmed_returns_no_tags(sns):
    subscribers(sns, subscription(arn=main.PENDING))
    assert call() == (200, {"tags": []})
    sns.get_subscription_attributes.assert_not_called()


def test_first_put_subscribes_with_the_filter_in_place(sns):
    status, body = call("PUT", {"tags": ["fox", "cane toad", "fox"]})
    assert (status, body) == (200, {"tags": ["cane toad", "fox"]})
    sns.subscribe.assert_called_once_with(
        TopicArn=main.TOPIC_ARN,
        Protocol="email",
        Endpoint=EMAIL,
        Attributes={"FilterPolicy": '{"tags": ["cane toad", "fox"]}'},
    )


def test_put_when_confirmed_replaces_the_filter(sns):
    subscribers(sns, subscription())
    assert call("PUT", {"tags": ["cat"]}) == (200, {"tags": ["cat"]})
    sns.set_subscription_attributes.assert_called_once_with(
        SubscriptionArn=ARN,
        AttributeName="FilterPolicy",
        AttributeValue='{"tags": ["cat"]}',
    )
    sns.subscribe.assert_not_called()


def test_put_with_no_tags_unsubscribes(sns):
    subscribers(sns, subscription())
    assert call("PUT", {"tags": []}) == (200, {"tags": []})
    sns.unsubscribe.assert_called_once_with(SubscriptionArn=ARN)


def test_put_with_no_tags_and_no_subscription_does_nothing(sns):
    assert call("PUT", {"tags": []}) == (200, {"tags": []})
    sns.unsubscribe.assert_not_called()
    sns.subscribe.assert_not_called()


def test_new_tags_while_unconfirmed_asks_to_confirm_first(sns):
    subscribers(sns, subscription(arn=main.PENDING))
    sns.subscribe.side_effect = ClientError(
        {"Error": {"Code": "InvalidParameter", "Message": "different"}},
        "Subscribe",
    )
    status, body = call("PUT", {"tags": ["cat"]})
    assert status == 409
    assert body["error"]["code"] == "confirm_first"


def test_unknown_tag_changes_nothing(sns):
    status, body = call("PUT", {"tags": ["fox", "foxx"]})
    assert status == 400
    assert body["error"]["code"] == "unknown_tag"
    sns.subscribe.assert_not_called()


@pytest.mark.parametrize(
    "body", [{}, {"tags": "fox"}, {"tags": [1]}, ["fox"], None]
)
def test_malformed_body_is_rejected(sns, body):
    status, reply = call("PUT", body)
    assert status == 400
    assert reply["error"]["code"] == "bad_tags"


def test_other_sns_errors_are_a_500_without_details(sns):
    sns.subscribe.side_effect = ClientError(
        {"Error": {"Code": "AuthorizationError", "Message": "secret detail"}},
        "Subscribe",
    )
    status, body = call("PUT", {"tags": ["fox"]})
    assert status == 500
    assert "secret detail" not in json.dumps(body)


def test_failed_token_exchange_is_a_500(sns):
    with mock.patch.object(
        main, "sns_client", side_effect=RuntimeError("no metadata server")
    ):
        assert call()[0] == 500
