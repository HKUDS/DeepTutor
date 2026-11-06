# Volcengine Ark Agent Plan

Use **Volcengine Ark Agent Plan** in Settings → Providers to configure one
dedicated Agent Plan key for language, embedding, image/video generation and
speech models. This is a separate provider from VolcEngine, Coding Plan and
Volcengine Speech (Doubao).

## Configure a connection

1. Add **Volcengine Ark Agent Plan** in Settings → Providers.
2. Enter the dedicated API key from the Agent Plan console. Leave Provider URL
   blank to use the per-service defaults below.
3. Save the provider, then add models referencing this connection from Language
   models, Embedding models, Media generation or Voice settings.
4. Test each configured model before making it active. Listing language models
   does not verify speech or media generation access.

| Service | Default address | Model example |
| --- | --- | --- |
| Language / task models, OpenAI-compatible | `https://ark.cn-beijing.volces.com/api/plan/v3` | `doubao-seed-2.1-pro` |
| Language models, Anthropic Messages | `https://ark.cn-beijing.volces.com/api/plan` | A model supported by the subscription |
| Text embeddings | `https://ark.cn-beijing.volces.com/api/plan/v3/embeddings` | `doubao-embedding-vision` |
| Image generation | `https://ark.cn-beijing.volces.com/api/plan/v3` | `doubao-seedream-5.0-flash` |
| Video generation | `https://ark.cn-beijing.volces.com/api/plan/v3` | `doubao-seedance-2.0` |
| Text-to-speech | `https://openspeech.bytedance.com/api/v3/plan` | `seed-tts-2.0` |
| Speech-to-text | `https://openspeech.bytedance.com/api/v3/plan` | `bigmodel` |

Language, embedding and generation requests use Bearer authentication. Speech
requests use `X-Api-Key`. A shared default language URL is translated to the
speech default automatically; the dedicated key remains on the backend.
Gateway deployments can override each service's address in the provider's
service settings.

Models and entitlements may change. Enter a supported model ID from your account
when it differs from these examples. The embedding adapter supports text input
through the plan's OpenAI-compatible endpoint; this integration does not add
image/video embedding input.

## Voice settings

For TTS, use the model/resource ID `seed-tts-2.0` and a speaker supported by
that version, for example `zh_female_vv_uranus_bigtts` from the official sample.
Use Preview voice to test the exact model and speaker. The HTTP response contains
JSON audio chunks; the backend collects them before returning playable audio.
WAV output is packaged from the provider's PCM output.

For ASR, the wire model name is `bigmodel`; the default resource ID is
`volc.seedasr.sauc.duration`. The adapter converts recordings to 16 kHz mono PCM,
uploads sequenced binary WebSocket frames, and returns the final transcript and
available utterance timestamps. Install FFmpeg for browser WebM/Opus recordings.
Recording remains upload-after-stop; this does not add live partial transcripts
to the browser UI.

## References

- [Agent Plan overview](https://ark.volcengine.com/region:cn-beijing/docs/agent-plan-personal-plan-overview)
- [Language model integration](https://ark.volcengine.com/region:cn-beijing/docs/agent-plan-personal-other-tools)
- [Embedding models](https://ark.volcengine.com/region:cn-beijing/docs/agent-plan-personal-vectorized-models)
- [Image and video models](https://ark.volcengine.com/region:cn-beijing/docs/agent-plan-personal-visual-models)
- [Speech models](https://ark.volcengine.com/region:cn-beijing/docs/agent-plan-personal-voice-model)
