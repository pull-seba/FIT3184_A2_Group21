"""Tests for ecoguard_common.tag_match.

Run from the repo root: python -m pytest shared/python
"""

import pytest

from ecoguard_common.tag_match import (
    QueryError,
    known_tags,
    matches,
    parse_query,
)

KNOWN = {"fox", "rabbit", "feral pig", "cane toad", "cat", "dog"}


def test_known_tags_reads_shared_tags_json():
    assert "feral pig" in known_tags()


def doc(tags, status="active"):
    return {"tags": tags, "status": status}


def test_counts_are_minimums():
    query = parse_query({"fox": 2}, KNOWN)
    assert not matches(doc({"fox": 1}), query)
    assert matches(doc({"fox": 2}), query)
    assert matches(doc({"fox": 3}), query)


def test_tags_combine_with_and():
    query = parse_query({"feral pig": 1, "cane toad": 3}, KNOWN)
    assert matches(doc({"feral pig": 1, "cane toad": 3, "fox": 1}), query)
    assert not matches(doc({"feral pig": 2}), query)
    assert not matches(doc({"cane toad": 5}), query)
    assert not matches(doc({"feral pig": 1, "cane toad": 2}), query)


def test_list_means_at_least_one_and_names_are_normalised():
    assert parse_query(["cat"], KNOWN) == {"cat": 1}
    query = parse_query({" Feral Pig ": 2, "FOX": 1}, KNOWN)
    assert query == {"feral pig": 2, "fox": 1}
    assert parse_query({"Fox": 3, "fox": 1}, KNOWN) == {"fox": 3}


@pytest.mark.parametrize(
    "body, code",
    [
        ({"foxx": 1}, "unknown_tag"),
        ({"fox": 0}, "bad_query"),
        ({"fox": True}, "bad_query"),
        ({}, "bad_query"),
        ([None], "bad_query"),
        ("fox", "bad_query"),
    ],
)
def test_rejects_bad_queries(body, code):
    with pytest.raises(QueryError) as excinfo:
        parse_query(body, KNOWN)
    assert excinfo.value.args[0] == code


def test_skips_inactive_untagged_and_empty_queries():
    deleting = doc({"fox": 4}, status="deleting")
    tagged_before_upload_record = {"tags": {"fox": 4}}
    untagged = {"status": "active"}
    for skipped in (deleting, tagged_before_upload_record, untagged):
        assert not matches(skipped, {"fox": 1})
    assert not matches(doc({"fox": 1}), {})
