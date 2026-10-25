"""The caller's identity, as forwarded by API Gateway. Owner: member 1 (starter from the team kit)."""
import base64
import json


def get_user(request):
    """Return the caller's Cognito claims as a dict, or None if the request didn't come through the gateway.

    API Gateway verifies the Cognito ID token, then forwards its payload base64url-encoded in the
    X-Apigateway-Api-Userinfo header. The header can be trusted only because each Cloud Run service
    is deployed with --no-allow-unauthenticated and only the gateway's service account may invoke it.
    """
    raw = request.headers.get("X-Apigateway-Api-Userinfo")
    if not raw:
        return None
    padded = raw + "=" * (-len(raw) % 4)
    try:
        claims = json.loads(base64.urlsafe_b64decode(padded))
    except ValueError:
        return None
    if not isinstance(claims, dict) or not claims.get("sub"):
        return None
    return claims
