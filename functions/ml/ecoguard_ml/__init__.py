"""ML code shared by member 3's functions (tagging, search_by_file, lost_pet).

detect.py: image bytes -> {tag: count}, the counting rule from the bake-off.
rekognition.py: Amazon Rekognition DetectLabels from GCP without AWS keys.
embed.py: Vertex AI multimodal embeddings of photos and text.
sightings.py: cat and dog crops with their embedding and colour.

Copied into each function folder before deploy, like ecoguard_common.
Owner: member 3.
"""


class BadImage(ValueError):
    """The bytes can't be tagged: not a readable image, or one the detector
    rejects. Retrying won't help, unlike a network or throttling error."""
