"""FUNCTION_NAME: one line on what this function does.

Owner: member N. Rubric: X.Y.Z. Route or trigger: see README.md.
"""

import json

import functions_framework
from google.cloud import firestore

from ecoguard_common.auth import get_user

db = firestore.Client()  # created once per instance, reused across requests

JSON_HEADERS = {"Content-Type": "application/json"}


def respond(body: dict, status: int = 200):
    return json.dumps(body), status, JSON_HEADERS


def error(status: int, code: str, message: str):
    """Error shape from docs/contracts/api-routes.md."""
    return respond({"error": {"code": code, "message": message}}, status)


@functions_framework.http
def handler(request):
    user = get_user(request)
    if user is None:
        # Cloud Run only accepts the gateway, so this means a misconfigured deploy.
        return error(
            401,
            "unauthenticated",
            "Request did not come through the API gateway",
        )

    body = request.get_json(silent=True)
    if body is None:
        return error(400, "bad_json", "Body must be JSON")

    # Validate every field against docs/contracts/api-routes.md before touching Firestore or Storage.
    # Write only the fields this function owns, with merge=True (docs/contracts/firestore-schema.md).

    return respond({})
