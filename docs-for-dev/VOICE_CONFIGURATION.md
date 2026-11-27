# Speech configuration and adapter development

[Handbook](README.md) · [Agent setup](AGENT_SETUP.md) · [Video learning](watching-workspace.md)

TTS (speech synthesis) and STT (speech recognition) have their own provider
profiles and defaults in Speech settings, independently of the chat model.

## Configure and verify

1. Select an implemented provider and supply its endpoint, exact model/resource
   ID and credential type.
2. Discover voices through the provider when supported. Voice IDs are not a
   permanent bundled catalog; account-specific voices and model IDs remain
   editable. A listed voice does not prove account entitlement.
3. Choose language, format and other options supported by that model family.
4. Preview a short sample, then save/select the default. Preview uses the current
   form without changing the saved default.
5. Verify actual read-aloud or transcription after saving. Model-list success
   alone does not prove speech synthesis or recognition works.

Preview invokes the provider and may incur usage. Form changes invalidate the
old preview; an in-flight preview can be cancelled. Request timeout accepts
5–600 seconds, defaulting to 60. Short samples help isolate configuration errors.

## Provider boundaries

- **Volcengine Speech:** Speech credentials differ from Ark LLM keys. The
  adapter accepts Speech API Key authentication and the older App ID/access-token
  form. Match TTS resource and voice family. STT uses a recording-file API;
  audio normalization may require system FFmpeg.
- **Aliyun DashScope:** Qwen3 TTS and Qwen-Audio TTS have distinct native
  endpoints and parameters. The adapter normalizes supported official
  compatible-mode bases; a private endpoint must implement the selected
  protocol. Match key and endpoint region. Confirm voices through discovery
  and actual preview instead of assuming an old example remains available.
- **Other adapters:** a compatible chat endpoint does not establish a
  compatible speech API. Model options and live discovery determine supported
  voices and formats.

Preserve distinct authentication, region/model, permission, rate-limit, timeout
and audio-download errors without exposing credential-bearing responses.
Retain cancellation and configured timeouts rather than adding unbounded retries.

## Source map

| Responsibility | Implementation |
| --- | --- |
| Profiles and resolution | [voice/config.py](../deeptutor/services/voice/config.py) |
| Model/parameter hints | [voice/options.py](../deeptutor/services/voice/options.py) |
| Voice discovery | [voice/discovery.py](../deeptutor/services/voice/discovery.py) |
| Preview | [voice/preview.py](../deeptutor/services/voice/preview.py) |
| Provider protocols | [voice/adapters/](../deeptutor/services/voice/adapters/) |
| Audio conversion | [voice/audio.py](../deeptutor/services/voice/audio.py) |

When adding an adapter, test credential handling, endpoint normalization,
decoding, timeout/cancellation and error redaction. Report live checks separately
from mocked protocol tests. Provider catalogs, availability and billing remain
external to this repository.
