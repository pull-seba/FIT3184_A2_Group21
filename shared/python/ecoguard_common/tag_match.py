"""AND and minimum-count tag matching for every search. Owner: member 4."""

import json
from pathlib import Path


class QueryError(ValueError):
    """A tag query the API rejects with 400. Its args are (code, message)."""


def load_tags() -> dict:
    package_dir = Path(__file__).parent
    deployed_copy = package_dir / "tags.json"
    repo_copy = package_dir.parent.parent / "tags.json"
    path = deployed_copy if deployed_copy.exists() else repo_copy
    return json.loads(path.read_text())


def known_tags() -> set[str]:
    return {tag["name"] for tag in load_tags()["tags"]}


def parse_query(body: object, known_tags: set[str]) -> dict[str, int]:
    if isinstance(body, list):
        if not all(isinstance(name, str) for name in body):
            raise QueryError("bad_query", "Tag names must be strings")
        body = dict.fromkeys(body, 1)
    if not isinstance(body, dict) or not body:
        raise QueryError(
            "bad_query", 'Send at least one tag, as {"fox": 2} or ["fox"]'
        )

    query = {}
    for name, count in body.items():
        tag = name.strip().lower()
        if tag not in known_tags:
            raise QueryError(
                "unknown_tag", f"Tag '{tag}' is not in the tag list"
            )
        # type() rather than isinstance(): JSON true is a bool, which
        # isinstance() counts as the int 1.
        if type(count) is not int or count < 1:
            raise QueryError(
                "bad_query",
                f"Count for '{tag}' must be a whole number of at least 1",
            )
        # "Fox" and "fox" both become "fox", so keep the stricter minimum.
        query[tag] = max(count, query.get(tag, 0))
    return query


def matches(doc: dict, query: dict[str, int]) -> bool:
    # Documents tagging wrote before the upload record have no status, and
    # all() would match every file for an empty query.
    if not query or doc.get("status") != "active":
        return False
    tags = doc.get("tags") or {}
    return all(tags.get(tag, 0) >= count for tag, count in query.items())
