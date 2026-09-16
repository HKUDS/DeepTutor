# Volcengine (Doubao Seed-TTS) text-to-speech

DeepTutor can speak through Volcengine's Doubao speech-synthesis models using the native `volcengine_tts` adapter. The adapter talks to the service directly over Volcengine's own V3 one-way streaming HTTP interface — there is no OpenAI-compatible relay, no third-party gateway and no intermediary service in the path — and returns audio through the same `(audio_bytes, content_type)` contract as every other provider.

## Why a dedicated adapter

Volcengine's speech service is not OpenAI-compatible:

- it authenticates on its own headers rather than `Authorization: Bearer`
- it selects the service version with an `X-Api-Resource-Id` header instead of a request-body `model`
- it answers with a stream of JSON documents whose `data` fields carry base64 audio

Pointing the shared OpenAI-compatible adapter at it produces 400s with no usable error text. Volcengine therefore gets its own adapter alongside the DashScope one.

Only the **V3** interfaces serve the 2.0 voices (`*_uranus_bigtts`); the older `/api/v1/tts` endpoint rejects them. The adapter targets the V3 one-way streaming endpoint, `POST https://openspeech.bytedance.com/api/v3/tts/unidirectional` — one-shot text in, streamed audio out — and concatenates the stream internally, so the rest of DeepTutor still receives a single `(audio_bytes, content_type)` pair.

## Registering the provider

Nothing beyond the usual two table entries:

- `TTS_PROVIDERS["volcengine"]` in `deeptutor/services/config/provider_runtime.py`, pointing at the `volcengine_tts` adapter
- `TTS_ADAPTERS["volcengine_tts"]` in `deeptutor/services/voice/adapters/__init__.py`

The Settings UI, the connection targets and the model-catalog plumbing all read those tables, so the provider appears in the voice provider list with no frontend change.

## Configure it

Open **Settings → Models → Text-to-Speech**, add a profile, and pick **Volcengine (Doubao Seed-TTS)**. The form prefills everything below; only the API key is actually required.

| Field | Value | Notes |
| --- | --- | --- |
| Base URL | `https://openspeech.bytedance.com/api/v3/tts/unidirectional` | A bare origin also works; the path is appended. Point it at `.../unidirectional/sse` to use the SSE interface instead — the adapter parses both framings. |
| API Key | your Doubao speech API key | Sent as `X-Api-Key`. |
| Model | `seed-tts-2.0` | Selects the service version. See *Resource ID*. |
| Voice | `zh_female_yingyujiaoxue_uranus_bigtts` | The provider default; see *Voices*. |
| Output format | `mp3` | `mp3`, `opus`, `pcm` and `wav` are supported. |

**Configuration lives in the model catalog, not in environment variables.** There are no `VOLCENGINE_*` variables to set and no credential is baked into any default: the key and the selections are stored in `model_catalog.json` through the settings API, exactly like every other provider, and are redacted from settings responses. Never commit a key, put one in a `.env` that ships, or write one into a default profile.

### Credentials

A key issued by the current Volcengine console goes in the **API Key** field and is sent as `X-Api-Key`. It must be a **speech** key from the Doubao voice console — Ark (方舟) inference keys are a different product and are rejected here.

The older console's two-part credential is supported through **Extra Headers** instead: set `X-Api-App-Id` and `X-Api-Access-Key` there and leave the API Key field empty. Do not mix the two; sending a current-console key as `X-Api-App-Id` fails with `load grant: requested grant not found`.

The voice also has to be activated for the account in the Volcengine console. An unactivated voice answers `45000000 speaker permission denied`.

### Resource ID

`X-Api-Resource-Id` decides which service version serves the request and how it is billed. `seed-tts-2.0` covers the 2.0 voices, `seed-tts-1.0` / `seed-tts-1.0-concurr` the 1.0 voices, and `seed-icl-2.0` / `seed-icl-1.0` cloned voices. A resource id that does not match the voice family is rejected with `55000000`, so the two have to move together.

The value is resolved in this order, highest priority first:

1. `X-Api-Resource-Id` in the profile's **Extra Headers** — always wins, and the escape hatch for anything the other rules do not cover
2. the profile's `resource_id` field, settable through the catalog API or `model_catalog.json` (there is no Settings input for it, because the Model field covers the normal case)
3. the **Model** field, when it names a documented resource id (`seed-tts-*` / `seed-icl-*`), so switching the model in Settings is enough to move between voice families
4. the adapter's pinned default, `seed-tts-2.0`

Rule 3 is what keeps the Model field meaningful: for this provider the "model" *is* the resource id, which is why the provider spec's `default_model` and the resource id agree out of the box. A free-text model label is deliberately **not** forwarded as a resource id — an unrecognised string falls through to rule 4 rather than being sent to the service.

> Do not set the Model field to `seed-tts-2.0-standard`. That value is the voice-cloning 2.0 `req_params.model`, not a resource id, but it starts with `seed-tts-` and would be picked up by rule 3.

### Voices

The default voice is `zh_female_yingyujiaoxue_uranus_bigtts` (Teacher Tina 2.0, Chinese and British English). Any id from Volcengine's published 2.0 list works; the id goes in the **Voice** field and is sent as `req_params.speaker`. The voice must come from the same family as the resource id. Voice cloning (`S_`-prefixed ids) is a separate service with its own resource ids and is not part of this adapter.

### Speed

The model's **Speed** setting maps onto the service's native `speech_rate`: `(speed - 1) × 100`, so `0.5` becomes `-50` and `2.0` becomes `100`. Requests outside the `[-50, 100]` range are clamped rather than rejected, and the default `1.0` is omitted from the request so the voice speaks at its natural pace.

### Output formats

`mp3` and `opus` come back as-is. `pcm` is returned as raw 16-bit mono audio at 24 kHz, tagged `audio/pcm;rate=24000;channels=1`, which the voice endpoint wraps into a WAV container before the browser sees it. `wav` is requested as PCM for the same reason: the streaming interface repeats the RIFF header on every chunk, so a concatenated WAV body would be malformed. `aac` and `flac` are rejected before any request is made.

## Verifying a configuration

Use the Test button on the voice profile. It synthesizes a short sample and reports the byte count and content type — a clean response confirms the key, the resource id and the voice all agree. Failures carry the service's own status code, and the adapter annotates the common ones (`45000000`, `55000000`, `40402003`) with the likely cause. HTTP failures include Volcengine's `X-Tt-Logid` so they can be quoted to support.

## Running the tests

The adapter's tests are self-contained and never reach the network — every HTTP response is mocked, and no test needs a real API key:

```bash
pytest tests/services/test_voice_volcengine.py
```

The voice suite as a whole, which also covers the shared adapters and the catalog plumbing:

```bash
pytest tests/services/test_voice.py tests/api/test_voice_routes.py tests/services/test_voice_volcengine.py
```

They cover the request shape and headers, NDJSON reassembly across chunk boundaries, the SSE framing variant, resource-id precedence, speed and format mapping, and every failure mode (HTTP errors, in-body status codes, empty audio, timeouts, connection errors, malformed base64, missing configuration).
