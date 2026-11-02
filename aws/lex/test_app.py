"""Tests fake the gateway; nothing here calls AWS or GCP."""

import io
import json
import urllib.error
from datetime import date
from pathlib import Path
from unittest import mock

import pytest
import yaml

import app

app.API_BASE = "https://gateway.example"

TODAY = date(2026, 11, 4)  # a Wednesday
HERE = Path(__file__).parent


def result(file_type="image", tags=None, url="https://storage.example/signed"):
    return {
        "file_id": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
        "file_type": file_type,
        "url": url,
        "thumbnail_url": url,
        "tags": tags or {"fox": 2},
        "uploaded_at": "2026-11-02T22:30:00Z",  # Tue 3 Nov in Melbourne
    }


def lex_event(intent, slots, token="id-token"):
    """A fulfilment event as Lex V2 sends it, cut to the fields the Lambda reads."""
    return {
        "requestAttributes": {"idToken": token} if token else None,
        "sessionState": {
            "intent": {
                "name": intent,
                "slots": {
                    # Lex leaves interpretedValue out when it can't resolve the words.
                    name: {
                        "value": {
                            "originalValue": said,
                            **({"interpretedValue": value} if value else {}),
                        }
                    }
                    if said
                    else None
                    for name, (said, value) in slots.items()
                },
                "state": "ReadyForFulfillment",
            }
        },
    }


FOXES_YESTERDAY = {
    "species": ("foxes", "fox"),
    "count": (None, None),
    "date": ("yesterday", "2026-11-02"),
}


def run(event, results=()):
    with (
        mock.patch.object(app, "search", return_value=list(results)) as search,
        mock.patch.object(app, "melbourne_today", return_value=TODAY),
    ):
        return app.handler(event, None), search


@pytest.mark.parametrize(
    "said, lex_date, expected",
    [
        # Lex works in New York time, a day behind on Melbourne mornings.
        ("yesterday", "2026-11-02", (date(2026, 11, 3), date(2026, 11, 3))),
        ("today", "2026-11-03", (TODAY, TODAY)),
        ("last week", "2026-10-19", (date(2026, 10, 26), date(2026, 11, 1))),
        ("this week", "2026-10-26", (date(2026, 11, 2), TODAY)),
        # Lex leaves these two unresolved.
        ("this month", None, (date(2026, 11, 1), TODAY)),
        ("last month", None, (date(2026, 10, 1), date(2026, 10, 31))),
        ("Friday", "2026-11-06", (date(2026, 10, 30), date(2026, 10, 30))),
        ("30 October", "2027-10-30", (date(2026, 10, 30), date(2026, 10, 30))),
        ("2 November", "2026-11-02", (date(2026, 11, 2), date(2026, 11, 2))),
        ("one day", None, None),
    ],
)
def test_dates_are_melbourne_days_in_the_past(said, lex_date, expected):
    assert app.date_window(said, lex_date, TODAY) == expected


def test_photo_search_sends_species_count_and_days():
    slots = {**FOXES_YESTERDAY, "count": ("2", "2")}
    response, search = run(
        lex_event("FindPhotos", slots), [result(), result("video")]
    )
    search.assert_called_once_with(
        "/search/tags?from=2026-11-03&to=2026-11-03", "id-token", {"fox": 2}
    )
    first, *rest = response["messages"]
    assert first == app.text(
        "I found 1 photo and 1 video with at least 2 foxes spotted on Tue 3 Nov."
    )
    assert json.loads(rest[0]["content"]) == {
        "label": "Photo · fox ×2 · Tue 3 Nov",
        "url": "https://storage.example/signed",
    }
    assert [message["contentType"] for message in rest] == ["CustomPayload"] * 2
    assert response["sessionState"]["dialogAction"] == {"type": "Close"}


def test_species_alone_means_at_least_one_on_any_day():
    slots = {
        "species": ("cane toads", "cane toad"),
        "count": (None, None),
        "date": (None, None),
    }
    response, search = run(
        lex_event("FindPhotos", slots), [result(tags={"cane toad": 1})]
    )
    search.assert_called_once_with("/search/tags", "id-token", {"cane toad": 1})
    assert response["messages"][0] == app.text("I found 1 photo of cane toads.")


def test_no_matches_get_a_friendly_answer():
    response, _ = run(lex_event("FindPhotos", FOXES_YESTERDAY))
    assert response["messages"] == [
        app.text(
            "I couldn't find any photos or videos of foxes spotted on Tue 3 Nov. "
            "Try another animal or day."
        )
    ]


def test_long_answers_link_the_newest_ten():
    response, _ = run(lex_event("FindPhotos", FOXES_YESTERDAY), [result()] * 12)
    messages = response["messages"]
    assert len(messages) == 1 + app.MAX_LINKS + 1
    assert messages[-1] == app.text(
        "Those are the newest 10. The Search page shows all 12."
    )


def test_a_link_fits_in_one_lex_message():
    # Longer than the real 880-character signed URLs, with three tags.
    url = "https://storage.googleapis.com/ecoguard-media/" + "x" * 870
    tags = {"feral pig": 3, "cane toad": 2, "fox": 1}
    assert len(app.link(result("video", tags, url))["content"]) <= 1024


def test_lost_pet_search_sends_species_and_colour():
    slots = {"pet": ("cat", "cat"), "colour": ("orange", "ginger")}
    response, search = run(
        lex_event("FindLostPet", slots), [result(tags={"cat": 1})]
    )
    search.assert_called_once_with(
        "/search/lost-pet",
        "id-token",
        {"species": "cat", "colour": "ginger", "breed": None, "since_days": 30},
    )
    assert response["messages"][0] == app.text(
        "I found 1 photo from the last 30 days that could show your ginger cat:"
    )


def test_missing_token_asks_to_sign_in_without_calling_the_gateway():
    with mock.patch.object(app.urllib.request, "urlopen") as urlopen:
        response = app.handler(
            lex_event("FindPhotos", FOXES_YESTERDAY, token=None), None
        )
    urlopen.assert_not_called()
    assert response["messages"] == [app.text(app.SIGN_IN_AGAIN)]


@pytest.mark.parametrize(
    "intent, slot, question",
    [
        ("FindPhotos", "species", app.WHICH_ANIMAL),
        ("FindLostPet", "pet", app.WHICH_PET),
    ],
)
@pytest.mark.parametrize(
    "said",
    [
        (None, None),  # "Show me photos"
        ("kangaroos", None),  # not a tag, so Lex can't resolve it
        ("foxes and cats", None),
    ],
)
def test_no_animal_gets_the_question_and_lex_keeps_no_state(
    intent, slot, question, said
):
    response, search = run(lex_event(intent, {slot: said}))
    search.assert_not_called()
    assert response["messages"] == [app.text(question)]
    assert response["sessionState"]["dialogAction"] == {"type": "Close"}


def test_unresolved_count_and_date_search_without_them():
    # "Show me photos with at least many foxes in Melbourne" used to crash.
    slots = {
        "species": ("foxes", "fox"),
        "count": ("many", None),
        "date": ("in Melbourne", None),
    }
    response, search = run(lex_event("FindPhotos", slots), [result()])
    search.assert_called_once_with("/search/tags", "id-token", {"fox": 1})
    assert response["messages"][0] == app.text("I found 1 photo of foxes.")


def test_unresolved_colour_searches_without_it():
    slots = {"pet": ("cat", "cat"), "colour": ("purple", None)}
    response, search = run(lex_event("FindLostPet", slots), [result()])
    search.assert_called_once_with(
        "/search/lost-pet",
        "id-token",
        {"species": "cat", "colour": None, "breed": None, "since_days": 30},
    )
    assert response["messages"][0] == app.text(
        "I found 1 photo from the last 30 days that could show your cat:"
    )


@pytest.mark.parametrize(
    "failure, answer",
    [
        (
            urllib.error.HTTPError("", 401, "Unauthorized", None, None),
            app.SIGN_IN_AGAIN,
        ),
        (
            urllib.error.HTTPError("", 502, "Bad Gateway", None, None),
            app.TRY_AGAIN,
        ),
        (urllib.error.URLError("timed out"), app.TRY_AGAIN),
    ],
)
def test_gateway_failures_still_get_an_answer(failure, answer):
    with mock.patch.object(app.urllib.request, "urlopen", side_effect=failure):
        response = app.handler(lex_event("FindPhotos", FOXES_YESTERDAY), None)
    assert response["messages"] == [app.text(answer)]


def test_search_posts_json_with_the_users_token():
    reply = mock.MagicMock()
    reply.__enter__.return_value = io.BytesIO(b'{"results": []}')
    with mock.patch.object(
        app.urllib.request, "urlopen", return_value=reply
    ) as urlopen:
        assert app.search("/search/tags", "id-token", {"fox": 1}) == []
    request = urlopen.call_args.args[0]
    assert request.get_method() == "POST"
    assert request.get_header("Authorization") == "Bearer id-token"
    assert json.loads(request.data) == {"fox": 1}


def bot_locale():
    class TemplateLoader(yaml.SafeLoader):
        pass

    # CloudFormation tags such as !Ref don't matter for the bot's own settings.
    TemplateLoader.add_multi_constructor("!", lambda loader, suffix, node: None)
    template = yaml.load((HERE / "template.yaml").read_text(), TemplateLoader)
    return template["Resources"]["ChatBot"]["Properties"]["BotLocales"][0]


def test_no_slot_is_required_so_lex_never_waits_on_a_prompt():
    for intent in bot_locale()["Intents"]:
        for slot in intent.get("Slots", []):
            setting = slot["ValueElicitationSetting"]
            assert setting["SlotConstraint"] == "Optional", slot["Name"]


def test_slot_values_are_the_tag_list():
    values = {
        slot_type["Name"]: [
            value["SampleValue"]["Value"]
            for value in slot_type["SlotTypeValues"]
        ]
        for slot_type in bot_locale()["SlotTypes"]
    }
    tags = json.loads((HERE / "../../shared/tags.json").read_text())
    assert values["Species"] == [tag["name"] for tag in tags["tags"]]
    assert values["PetSpecies"] == tags["lost_pet_species"]
    assert values["Colour"] == tags["lost_pet_colours"]
