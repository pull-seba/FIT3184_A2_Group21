"""subscriptions: reads and replaces the caller's alert tags.

Owner: member 1. Rubric: 2.3.3. Routes: GET and PUT
/notifications/subscriptions.

A person's alert tags are the filter policy on their SNS email subscription,
so SNS stays the one place they live (docs/decisions.md, 30 Oct). The email
comes only from the verified ID token, so nobody can change someone else's.

The function has no AWS keys. It asks the metadata server for a Google ID token
for its own service account, and AWS STS swaps that for one-hour credentials on
a role limited to this topic's subscriptions (aws/iam/subscriptions.json).
"""

import json
import os
import time

import boto3
import functions_framework
import google.auth.transport.requests
import google.oauth2.id_token
from botocore import UNSIGNED
from botocore.config import Config
from botocore.exceptions import ClientError

from ecoguard_common.auth import get_user
from ecoguard_common.logs import log
from ecoguard_common.tag_match import known_tags

ROLE_ARN = os.environ.get("SUBSCRIPTIONS_ROLE_ARN", "")
TOPIC_ARN = os.environ.get("TOPIC_ARN", "")
REGION = "us-east-1"
REFRESH_EARLY_S = 300
KNOWN_TAGS = known_tags()

# SNS lists an unconfirmed subscription with this instead of its ARN.
PENDING = "PendingConfirmation"

# The browser calls from the app's origin, so it sends a preflight first
# (infra/gateway/README.md). "*" is safe: every real call still needs a token.
CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, PUT, OPTIONS",
    "Access-Control-Allow-Headers": "Authorization, Content-Type",
}
JSON_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
}

_client = None
_expires = 0.0


def respond(body: dict, status: int = 200):
    return json.dumps(body), status, JSON_HEADERS


def error(status: int, code: str, message: str):
    """Error shape from docs/contracts/api-routes.md."""
    return respond({"error": {"code": code, "message": message}}, status)


def sns_client():
    """An SNS client on the federated role, reused until its credentials are
    about to expire. Same exchange as functions/ml/ecoguard_ml/rekognition.py."""
    global _client, _expires
    if _client and time.time() < _expires - REFRESH_EARLY_S:
        return _client
    token = google.oauth2.id_token.fetch_id_token(
        google.auth.transport.requests.Request(), audience=ROLE_ARN
    )
    # The Google token is the proof of identity, so the request isn't signed.
    sts = boto3.client(
        "sts", region_name=REGION, config=Config(signature_version=UNSIGNED)
    )
    credentials = sts.assume_role_with_web_identity(
        RoleArn=ROLE_ARN,
        RoleSessionName="subscriptions",
        WebIdentityToken=token,
    )["Credentials"]
    _client = boto3.client(
        "sns",
        region_name=REGION,
        aws_access_key_id=credentials["AccessKeyId"],
        aws_secret_access_key=credentials["SecretAccessKey"],
        aws_session_token=credentials["SessionToken"],
    )
    _expires = credentials["Expiration"].timestamp()
    return _client


def find_subscription(sns, email: str) -> dict | None:
    """The caller's email subscription on the topic, if there is one."""
    pages = sns.get_paginator("list_subscriptions_by_topic").paginate(
        TopicArn=TOPIC_ARN
    )
    for page in pages:
        for subscription in page["Subscriptions"]:
            if (
                subscription["Protocol"] == "email"
                and subscription["Endpoint"].lower() == email.lower()
            ):
                return subscription
    return None


def read_tags(sns, email: str) -> list[str]:
    """The caller's tags. An unconfirmed subscription has no ARN to read them
    with, so it counts as none until its owner confirms it."""
    subscription = find_subscription(sns, email)
    if not subscription or subscription["SubscriptionArn"] == PENDING:
        return []
    attributes = sns.get_subscription_attributes(
        SubscriptionArn=subscription["SubscriptionArn"]
    )["Attributes"]
    policy = json.loads(attributes.get("FilterPolicy") or "{}")
    return sorted(policy.get("tags", []))


def replace_tags(sns, email: str, tags: list[str]) -> None:
    """Make the caller's subscription match tags. Saving the same tags twice
    changes nothing, so a retried request is safe."""
    subscription = find_subscription(sns, email)
    confirmed = subscription and subscription["SubscriptionArn"] != PENDING
    policy = json.dumps({"tags": tags})

    if not tags:
        if confirmed:
            sns.unsubscribe(SubscriptionArn=subscription["SubscriptionArn"])
    elif confirmed:
        sns.set_subscription_attributes(
            SubscriptionArn=subscription["SubscriptionArn"],
            AttributeName="FilterPolicy",
            AttributeValue=policy,
        )
    else:
        # Sends the confirmation email. The filter is in place from the start,
        # so a new subscriber never gets an alert for a tag they didn't choose.
        sns.subscribe(
            TopicArn=TOPIC_ARN,
            Protocol="email",
            Endpoint=email,
            Attributes={"FilterPolicy": policy},
        )


def parse_tags(body) -> list[str] | None:
    """The tags from a PUT body, sorted and without repeats, or None if the
    body isn't {"tags": [...strings...]}."""
    tags = body.get("tags") if isinstance(body, dict) else None
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        return None
    return sorted(set(tags))


@functions_framework.http
def handler(request):
    if request.method == "OPTIONS":
        return "", 204, CORS

    user = get_user(request)
    if user is None:
        # Cloud Run only accepts the gateway, so this means a misconfigured deploy.
        return error(
            401,
            "unauthenticated",
            "Request did not come through the API gateway",
        )
    email = user.get("email")
    if not email:
        return error(400, "no_email", "Your account has no email address")

    if request.method not in ("GET", "PUT"):
        return error(405, "method_not_allowed", "Use GET or PUT")

    tags = None
    if request.method == "PUT":
        tags = parse_tags(request.get_json(silent=True))
        if tags is None:
            return error(400, "bad_tags", 'Send {"tags": ["fox", ...]}')
        for tag in tags:
            if tag not in KNOWN_TAGS:
                return error(
                    400, "unknown_tag", f"Tag '{tag}' is not in the tag list"
                )

    try:
        sns = sns_client()
        if tags is None:
            return respond({"tags": read_tags(sns, email)})
        replace_tags(sns, email, tags)
        return respond({"tags": tags})
    except ClientError as exc:
        # SNS refuses new tags while the first confirmation email is unanswered.
        if exc.response["Error"]["Code"] == "InvalidParameter":
            return error(
                409,
                "confirm_first",
                "Confirm the email AWS sent you, then save your alerts again",
            )
        log("ERROR", f"subscriptions failed: {exc}", sub=user["sub"])
        return error(500, "internal", "Could not update your alerts")
    except Exception as exc:  # anything unexpected is logged (api-routes.md)
        log(
            "ERROR",
            f"subscriptions failed: {type(exc).__name__}: {exc}",
            sub=user["sub"],
        )
        return error(500, "internal", "Could not update your alerts")
