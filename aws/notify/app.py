"""notify: receives tag-changes pushes from GCP Pub/Sub and emails subscribers through SNS.

Owner: member 1. Rubric: 2.3.3 (cross-cloud link 3). Setup: see README.md.

Pub/Sub can't sign AWS requests, so the function URL is open and every request must carry a
Google-signed ID token for the push service account. Anything else gets 401.
"""

import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request

import boto3

sns = boto3.client("sns")

TOPIC_ARN = os.environ.get("TOPIC_ARN", "")
PUSH_ACCOUNT = os.environ.get(
    "PUSH_ACCOUNT", "ecoguard-pubsub-push@ecoguard-g21.iam.gserviceaccount.com"
)
APP_URL = os.environ.get("APP_URL", "http://localhost:5173")
GOOGLE_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}


def google_claims(token: str) -> dict | None:
    """Asks Google to check the token's signature and expiry; returns its claims, or None."""
    url = "https://oauth2.googleapis.com/tokeninfo?" + urllib.parse.urlencode(
        {"id_token": token}
    )
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return json.load(response)
    except urllib.error.HTTPError:
        return None  # Google answers 400 for a bad or expired token


def from_pubsub(event) -> bool:
    """True only for a Google ID token issued to our push account, for this URL."""
    auth = event.get("headers", {}).get("authorization", "")
    if not auth.startswith("Bearer "):
        return False
    claims = google_claims(auth.removeprefix("Bearer "))
    if not claims:
        return False
    # Pub/Sub sets the audience to the push endpoint, which is this function's URL.
    domain = event["requestContext"]["domainName"]
    return (
        claims.get("iss") in GOOGLE_ISSUERS
        and claims.get("aud") in {f"https://{domain}", f"https://{domain}/"}
        and claims.get("email") == PUSH_ACCOUNT
        and claims.get("email_verified") == "true"
    )


def read_message(event) -> dict:
    """The tag-changes message inside a Pub/Sub push body."""
    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        body = base64.b64decode(body).decode()
    data = json.loads(body)["message"]["data"]
    return json.loads(base64.b64decode(data))


def email(message: dict) -> tuple[str, str]:
    """Subject and body. Names the species and counts and links to the app, never a signed URL."""
    added = message["added"]
    counts = ", ".join(f"{name} ({message['tags'][name]})" for name in added)
    subject = f"EcoGuard alert: {', '.join(added)}"[:100]  # SNS subject limit
    body = (
        f"A {message.get('file_type') or 'file'} in Aussie EcoGuard now shows: {counts}.\n\n"
        f"All tags on it: {json.dumps(message['tags'])}\n"
        f"Uploaded: {message.get('uploaded_at') or 'just now'}\n\n"
        f"Open the app to see it: {APP_URL}\n"
    )
    return subject, body


def handler(event, context):
    if not from_pubsub(event):
        return {"statusCode": 401}

    try:
        message = read_message(event)
        added = message["added"]
    except (KeyError, ValueError):
        # A malformed message would fail the same way on every retry, so accept and drop it.
        print(
            json.dumps(
                {"level": "ERROR", "message": "malformed tag-changes push"}
            )
        )
        return {"statusCode": 204}

    subject, body = email(message)
    sns.publish(
        TopicArn=TOPIC_ARN,
        Subject=subject,
        Message=body,
        # Each email subscription's filter policy matches against this list.
        MessageAttributes={
            "tags": {
                "DataType": "String.Array",
                "StringValue": json.dumps(added),
            }
        },
    )
    print(
        json.dumps(
            {
                "message": "sent alert",
                "file_id": message.get("file_id"),
                "added": added,
            }
        )
    )
    return {"statusCode": 204}
