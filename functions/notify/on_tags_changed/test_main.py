"""Tests mock every cloud client; nothing here touches the shared project."""

import json
from datetime import UTC, datetime
from unittest import mock

from cloudevents.http import CloudEvent
from google.events.cloud import firestore as firestoredata

with mock.patch("google.cloud.pubsub_v1.PublisherClient"):
    import main

FILE_ID = "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
NAME = f"projects/ecoguard-g21/databases/(default)/documents/files/{FILE_ID}"


def document(tags=None, **fields):
    """A Firestore document as it appears inside the event."""
    doc = firestoredata.Document(name=NAME)
    if tags is not None:
        doc.fields["tags"] = firestoredata.Value(
            map_value=firestoredata.MapValue(
                fields={
                    name: firestoredata.Value(integer_value=count)
                    for name, count in tags.items()
                }
            )
        )
    for name, value in fields.items():
        if isinstance(value, datetime):
            doc.fields[name] = firestoredata.Value(timestamp_value=value)
        else:
            doc.fields[name] = firestoredata.Value(string_value=value)
    return doc


def fire(before=None, after=None):
    """Runs the handler on one event and returns the published message, or None."""
    data = firestoredata.DocumentEventData(
        old_value=before or firestoredata.Document(),
        value=after or firestoredata.Document(),
    )
    event = CloudEvent(
        {
            "type": "google.cloud.firestore.document.v1.updated",
            "source": "test",
        },
        firestoredata.DocumentEventData.serialize(data),
    )
    main.publisher.reset_mock()
    main.handler(event)
    if not main.publisher.publish.called:
        return None
    _, payload = main.publisher.publish.call_args.args
    return json.loads(payload)


def test_new_tag_publishes_the_contract_message():
    uploaded = datetime(2026, 10, 26, 9, 43, tzinfo=UTC)
    message = fire(
        before=document(file_type="image", uploaded_at=uploaded),
        after=document({"fox": 2}, file_type="image", uploaded_at=uploaded),
    )
    assert message == {
        "file_id": FILE_ID,
        "file_type": "image",
        "tags": {"fox": 2},
        "added": ["fox"],
        "uploaded_at": "2026-10-26T09:43:00Z",
    }


def test_new_document_counts_as_no_tags_before():
    message = fire(after=document({"cat": 1}))
    assert message["added"] == ["cat"]


def test_higher_count_is_added():
    message = fire(
        before=document({"fox": 1, "cat": 1}),
        after=document({"fox": 3, "cat": 1}),
    )
    assert message["added"] == ["fox"]
    assert message["tags"] == {"fox": 3, "cat": 1}


def test_same_tags_publish_nothing():
    assert (
        fire(
            before=document({"fox": 2}),
            after=document({"fox": 2}, status="active"),
        )
        is None
    )


def test_removed_or_lower_tags_publish_nothing():
    assert (
        fire(before=document({"fox": 2, "cat": 1}), after=document({"fox": 1}))
        is None
    )


def test_tag_names_with_spaces():
    message = fire(after=document({"feral pig": 1, "cane toad": 3}))
    assert message["added"] == ["cane toad", "feral pig"]


def test_delete_publishes_nothing():
    assert fire(before=document({"fox": 2})) is None


def test_file_being_deleted_publishes_nothing():
    assert fire(after=document({"fox": 2}, status="deleting")) is None


def test_same_event_twice_gives_the_same_message():
    # Eventarc can deliver twice; the handler reads only the event, so both runs agree.
    first = fire(after=document({"fox": 2}))
    second = fire(after=document({"fox": 2}))
    assert first == second
