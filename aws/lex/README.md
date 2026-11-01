# chat (Lex bot and fulfilment Lambda)

Owner: member 4 · Rubric: 2.2.5 · Cross-cloud link 2

## What it does
`template.yaml` is the whole bot: the Lex V2 bot `ecoguard-chat` (locale `en_AU`) and the Lambda `ecoguard-chat-fulfilment` (`app.py`) that answers it.

| Intent | Say | The Lambda calls |
| --- | --- | --- |
| `FindPhotos` | "Show me all photos of foxes spotted yesterday", "Show me photos with at least 2 feral pigs" | `POST /search/tags` with `{species: count}`, plus `from` and `to` days when a date is given |
| `FindLostPet` | "Help me find a lost ginger cat" | `POST /search/lost-pet` with `species`, `colour` and `since_days: 30` |
| `Help`, `FallbackIntent` | "Hi", or anything else | Nothing; Lex answers with example questions |

Slot type `Species` holds the tag names from `shared/tags.json` and `PetSpecies` its `lost_pet_species`, with synonyms such as "foxes" and "boar"; `test_app.py` fails if they drift apart. Dates come from `AMAZON.Date`, but Lex resolves "yesterday" in us-east-1's time zone, up to a day behind Melbourne, so the Lambda works out today, yesterday, this week and last week from Melbourne's date itself.

## How the Lambda reaches GCP
```
chat widget ──(identity pool credentials)──▶ Lex RecognizeText, requestAttributes.idToken = Cognito ID token
Lex ──▶ this Lambda ──(Authorization: Bearer <ID token>)──▶ GCP API Gateway ──▶ tag_query or lost_pet
```
The Lambda has no GCP credentials. It forwards the signed-in user's own ID token, and the gateway checks it as it checks every request; no token, or an expired one, gets "please sign in again". Request attributes travel with one request only, so Lex never keeps the token in its session. Decided 1 Nov in `docs/decisions.md`: conversation logs stay off and the Lambda never logs the event, because either would record the token.

## Replies
The first message is a sentence (`PlainText`). Each result follows as its own `CustomPayload` message, `{"label": "Photo · fox ×2 · Sat 31 Oct", "url": "<signed URL>"}`, because Lex caps a message at 1024 characters and a signed URL takes about 880. At most 10 links, newest first; the chat widget shows each as a link.

## Permissions
- Role `ecoguard-chat-fulfilment` writes only its own log group (`aws/iam/chat-fulfilment.json`).
- Role `ecoguard-chat-bot` has no policies, because a text-only bot uses neither Polly nor Comprehend.
- Only this bot's test alias may invoke the Lambda (`FulfilmentPermission`).
- The chat widget's identity pool role may only call `lex:RecognizeText` on that alias (member 1's `aws/iam/chat-widget.json`, stack `ecoguard-auth`).

## Test
```bash
pip install pytest pyyaml
python -m pytest
```

## Deploy (a person runs this)
SAM CLI zips this folder, uploads it to its own bucket and deploys the stack `ecoguard-chat` in `us-east-1` (settings in `samconfig.toml`):
```bash
sam deploy
```
Give the `BotAliasArn` output to member 1, who passes it to the `ecoguard-auth` stack as `LexBotAliasArn`.

## Try it without the app
```bash
aws lexv2-runtime recognize-text --region us-east-1 --bot-id <BotId> --bot-alias-id TSTALIASID \
  --locale-id en_AU --session-id test --text "Show me all photos of foxes spotted yesterday" \
  --request-attributes idToken=<Cognito ID token>
```
