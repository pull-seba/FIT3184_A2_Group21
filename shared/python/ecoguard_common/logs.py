"""Structured logs for Cloud Run functions. Owner: member 2."""

import json


def log(severity: str, message: str, **fields):
    """One JSON line, which Cloud Logging parses into a structured entry.
    Never log tokens, signed URLs or image bytes."""
    print(
        json.dumps({"severity": severity, "message": message, **fields}),
        flush=True,
    )
