"""AND and minimum-count tag matching, shared by every search. Owner: member 4."""


class QueryError(ValueError):
    """A tag query the API rejects with 400. Its args are (code, message) for the error body."""


def parse_query(body, known_tags):
    """Turn a request body into {tag: minimum count}, or raise QueryError.

    Accepts {"fox": 2} or a list of names, where ["cat"] means {"cat": 1}. Names are trimmed and
    lowercased, then checked against known_tags (the tag names in shared/tags.json).
    """
    if isinstance(body, list):
        if not all(isinstance(name, str) for name in body):
            raise QueryError("bad_query", "Tag names must be strings")
        body = dict.fromkeys(body, 1)
    if not isinstance(body, dict) or not body:
        raise QueryError("bad_query", 'Send at least one tag, as {"fox": 2} or ["fox"]')

    query = {}
    for name, count in body.items():
        tag = name.strip().lower()
        if tag not in known_tags:
            raise QueryError("unknown_tag", f"Tag '{tag}' is not in the tag list")
        # type() rather than isinstance(): JSON true is a bool, which isinstance() counts as the int 1.
        if type(count) is not int or count < 1:
            raise QueryError("bad_query", f"Count for '{tag}' must be a whole number of at least 1")
        # "Fox" and "fox" in one query both become "fox", so keep the stricter minimum.
        query[tag] = max(count, query.get(tag, 0))
    return query


def matches(doc, query):
    """True if a `files` document has every queried tag at or above its minimum count (AND).

    Only "active" files match: not files being deleted, and not documents tagging wrote before the
    upload record existed. An empty query matches nothing, so a search-by-file photo with no
    animals in it finds no files instead of every file.
    """
    if not query or doc.get("status") != "active":
        return False
    tags = doc.get("tags") or {}
    return all(tags.get(tag, 0) >= count for tag, count in query.items())
