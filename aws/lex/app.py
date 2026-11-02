"""chat fulfilment: runs the Lex chatbot's searches through the GCP gateway.

Owner: member 4. Rubric: 2.2.5 (cross-cloud link 2). Setup: see README.md.

The chat widget sends the signed-in user's Cognito ID token as the Lex request
attribute idToken. This Lambda forwards it to API Gateway, which checks it like
any other call, so the Lambda holds no GCP credentials of its own.
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

API_BASE = os.environ.get("API_BASE", "")
MELBOURNE = ZoneInfo("Australia/Melbourne")
MAX_LINKS = 10
LOST_PET_DAYS = 30
SIGN_IN_AGAIN = (
    "Your sign-in has expired. Please sign in again, then ask me once more."
)
TRY_AGAIN = "Sorry, the search didn't work just now. Please try again soon."
WHICH_ANIMAL = (
    "Which animal? I can search one at a time: foxes, rabbits, feral pigs, "
    'cane toads, cats or dogs. Try "Show me photos of foxes".'
)
WHICH_PET = 'Is it a cat or a dog? Try "Help me find a lost ginger cat".'


class SignInNeeded(Exception):
    pass


def melbourne_today() -> date:
    return datetime.now(MELBOURNE).date()


def slot_value(intent: dict, name: str) -> dict | None:
    """What the user typed (originalValue) and what Lex made of it (interpretedValue)."""
    slot = intent["slots"].get(name)
    return slot["value"] if slot else None


def interpreted(intent: dict, name: str) -> str | None:
    """What Lex made of a slot, or None if it's empty or Lex couldn't resolve it.

    Lex fills a slot with only an originalValue when the words don't fit its
    type: "in Melbourne" as a date, "many" as a count, "purple" as a colour.
    """
    said = slot_value(intent, name)
    return said.get("interpretedValue") if said else None


def date_window(
    said: str, resolved: str | None, today: date
) -> tuple[date, date] | None:
    """The first and last Melbourne day the user means, or None if unclear.

    Lex resolves relative dates in us-east-1's time zone, up to a day behind
    Melbourne, and leaves "this month" unresolved, so the common phrases are
    worked out here from Melbourne's today.
    """
    said = said.lower()
    monday = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    if "yesterday" in said or "last night" in said:
        return today - timedelta(days=1), today - timedelta(days=1)
    if "today" in said or "tonight" in said:
        return today, today
    if "last week" in said:
        return monday - timedelta(days=7), monday - timedelta(days=1)
    if "this week" in said:
        return monday, today
    if "last month" in said:
        last_month_end = month_start - timedelta(days=1)
        return last_month_end.replace(day=1), last_month_end
    if "this month" in said:
        return month_start, today
    if not resolved:
        return None
    first = date.fromisoformat(resolved)
    if first > today:
        # Lex picks the next matching day, but sightings are in the past:
        # "Friday" means last Friday and "30 October" the last 30 October.
        if first - today < timedelta(days=7):
            first -= timedelta(days=7)
        else:
            first = first.replace(year=first.year - 1)
    return first, first


def search(path: str, token: str | None, body: dict) -> list[dict]:
    if not token:
        raise SignInNeeded
    request = urllib.request.Request(
        API_BASE + path,
        data=json.dumps(body).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.load(response)["results"]
    except urllib.error.HTTPError as error:
        if error.code == 401:
            raise SignInNeeded from error
        raise


def plural(name: str) -> str:
    return name + ("es" if name.endswith("x") else "s")


def day(when: date) -> str:
    return f"{when:%a} {when.day} {when:%b}"


def text(message: str) -> dict:
    return {"contentType": "PlainText", "content": message}


def link(result: dict) -> dict:
    """One result as a message the chat widget shows as a link.

    Lex caps a message at 1024 characters and a signed URL takes about 880, so
    each result gets its own message holding only a label and the URL.
    """
    kind = "Video" if result["file_type"] == "video" else "Photo"
    tags = ", ".join(
        f"{name} ×{count}" for name, count in result["tags"].items()
    )
    uploaded = datetime.fromisoformat(result["uploaded_at"]).astimezone(
        MELBOURNE
    )
    label = f"{kind} · {tags} · {day(uploaded.date())}"
    content = json.dumps(
        {"label": label, "url": result["url"]}, ensure_ascii=False
    )
    return {"contentType": "CustomPayload", "content": content}


def links(results: list[dict]) -> list[dict]:
    shown = [link(result) for result in results[:MAX_LINKS]]
    if len(results) > MAX_LINKS:
        shown.append(
            text(
                f"Those are the newest {MAX_LINKS}. "
                f"The Search page shows all {len(results)}."
            )
        )
    return shown


def counted(results: list[dict]) -> str:
    """Such as '2 photos and 1 video'."""
    videos = sum(result["file_type"] == "video" for result in results)
    kinds = [(len(results) - videos, "photo"), (videos, "video")]
    return " and ".join(
        f"{n} {kind}{'' if n == 1 else 's'}" for n, kind in kinds if n
    )


def find_photos(intent: dict, token: str | None) -> list[dict]:
    species = interpreted(intent, "species")
    if not species:
        return [text(WHICH_ANIMAL)]
    count = interpreted(intent, "count")
    minimum = max(1, int(float(count))) if count else 1
    if minimum == 1:
        what = f"of {plural(species)}"
    else:
        what = f"with at least {minimum} {plural(species)}"

    path, when = "/search/tags", ""
    date_said = slot_value(intent, "date")
    window = date_said and date_window(
        date_said["originalValue"],
        date_said.get("interpretedValue"),
        melbourne_today(),
    )
    if window:
        first, last = window
        path += "?" + urllib.parse.urlencode(
            {"from": first.isoformat(), "to": last.isoformat()}
        )
        if first == last:
            when = f" spotted on {day(first)}"
        else:
            when = f" spotted between {day(first)} and {day(last)}"

    results = search(path, token, {species: minimum})
    if not results:
        return [
            text(
                f"I couldn't find any photos or videos {what}{when}. "
                "Try another animal or day."
            )
        ]
    return [text(f"I found {counted(results)} {what}{when}."), *links(results)]


def find_lost_pet(intent: dict, token: str | None) -> list[dict]:
    pet = interpreted(intent, "pet")
    if not pet:
        return [text(WHICH_PET)]
    colour = interpreted(intent, "colour")
    described = f"{colour} {pet}" if colour else pet

    results = search(
        "/search/lost-pet",
        token,
        {
            "species": pet,
            "colour": colour,
            "breed": None,
            "since_days": LOST_PET_DAYS,
        },
    )
    if not results:
        return [
            text(
                f"There are no public sightings of {plural(described)} in the "
                f"last {LOST_PET_DAYS} days. The Lost pet page can also "
                "search with a photo."
            )
        ]
    return [
        text(
            f"I found {counted(results)} from the last {LOST_PET_DAYS} days "
            f"that could show your {described}:"
        ),
        *links(results),
    ]


INTENTS = {"FindPhotos": find_photos, "FindLostPet": find_lost_pet}


def handler(event, context):
    intent = event["sessionState"]["intent"]
    token = (event.get("requestAttributes") or {}).get("idToken")
    try:
        messages = INTENTS[intent["name"]](intent, token)
    except SignInNeeded:
        messages = [text(SIGN_IN_AGAIN)]
    except Exception as exc:
        # The user gets a sentence instead of a Lex error, whatever went wrong.
        message = f"{intent['name']} failed: {exc!r}"
        print(json.dumps({"level": "ERROR", "message": message}))
        messages = [text(TRY_AGAIN)]
    return {
        "sessionState": {
            "dialogAction": {"type": "Close"},
            "intent": {**intent, "state": "Fulfilled"},
        },
        "messages": messages,
    }
