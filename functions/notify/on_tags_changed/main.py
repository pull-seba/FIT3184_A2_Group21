"""on_tags_changed: publishes to tag-changes when a file gains a tag or a higher count.

Owner: member 1. Rubric: 2.3.3. Trigger: see README.md.
"""

import json
import os

import functions_framework
from google.cloud import pubsub_v1
from google.events.cloud import firestore as firestoredata

# Created once per instance and reused across events.
publisher = pubsub_v1.PublisherClient()

TOPIC = os.environ.get("TOPIC", "projects/ecoguard-g21/topics/tag-changes")


def tag_counts(document) -> dict[str, int]:
    """The `tags` map of a Firestore document from the event, as {name: count}."""
    if "tags" not in document.fields:
        return {}
    fields = document.fields["tags"].map_value.fields
    return {name: value.integer_value for name, value in fields.items()}


def added_tags(before: dict[str, int], after: dict[str, int]) -> list[str]:
    """Tags that are new or whose count went up. Removed or lower counts never alert."""
    return sorted(
        name for name, count in after.items() if count > before.get(name, 0)
    )


def string_field(document, name: str) -> str | None:
    return (
        document.fields[name].string_value if name in document.fields else None
    )


def time_field(document, name: str) -> str | None:
    if name not in document.fields:
        return None
    # The protobuf Timestamp converts to a datetime in UTC.
    return document.fields[name].timestamp_value.strftime("%Y-%m-%dT%H:%M:%SZ")


@functions_framework.cloud_event
def handler(cloud_event):
    # Firestore events arrive as protobuf, not JSON.
    event = firestoredata.DocumentEventData.deserialize(cloud_event.data)
    after = event.value

    # A delete has no new document: nothing to alert on.
    if not after.name:
        return
    if string_field(after, "status") == "deleting":
        return

    # A newly created document has no old value, which counts as "no tags before".
    added = added_tags(tag_counts(event.old_value), tag_counts(after))
    # Writes that don't add a tag (thumbnails, pipeline status, tag removals) end here.
    if not added:
        return

    file_id = after.name.rsplit("/", 1)[-1]
    message = {
        "file_id": file_id,
        "file_type": string_field(after, "file_type"),
        "tags": tag_counts(after),
        "added": added,
        "uploaded_at": time_field(after, "uploaded_at"),
    }
    publisher.publish(TOPIC, json.dumps(message).encode()).result()
    print(
        json.dumps(
            {
                "severity": "INFO",
                "message": "published tag-changes",
                "file_id": file_id,
                "added": added,
            }
        )
    )
