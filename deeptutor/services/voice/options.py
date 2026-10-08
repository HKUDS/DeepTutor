"""Speech parameter hints, shared by settings and runtime defaults.

Voice IDs are never bundled here. They are discovered live by voice.discovery.
These model/parameter hints are not an exhaustive entitlement/model inventory.
Unknown models and private voices remain editable.
Sources checked 2026-09-17 are included in each provider's public metadata.
"""

from __future__ import annotations

from copy import deepcopy


def choices(values: list[str]) -> list[dict]:
    return [{"id": value, "label": value} for value in values]


def is_qwen_audio_tts(model: str) -> bool:
    """Qwen-Audio TTS uses SpeechSynthesizer, unlike Qwen3's multimodal API."""
    return model.startswith("qwen-audio-") and "-tts-" in model


ISO_LANGUAGES = choices("zh en ja ko de fr es pt it ru ar id".split())
VOLC_LANGUAGES = choices(
    "zh-CN en-US ja-JP id-ID es-MX pt-BR de-DE fr-FR ko-KR fil-PH ms-MY th-TH ar-SA it-IT bn-BD el-GR nl-NL ru-RU tr-TR vi-VN pl-PL ro-RO ne-NP uk-UA yue-CN".split()
)
OPENAI_FORMATS = ["mp3", "wav", "opus", "aac", "flac", "pcm"]


def preset(model: str, *, languages=None, formats=None, **kwargs) -> dict:
    return {
        "id": model,
        "label": model,
        "voices": [],
        "languages": languages or [],
        "formats": formats or [],
        **kwargs,
    }


def _tts_models(provider: str) -> tuple[list[dict], str]:
    if provider == "xiaomi_mimo":
        return [
            preset(
                "mimo-v2.5-tts",
                formats=["wav", "pcm16"],
                instructions=True,
            )
        ], "https://mimo.mi.com/docs/zh-CN/quick-start/usage-guide/audio/speech-synthesis-v2.5"
    if provider == "minimax":
        return [
            preset(
                model,
                languages=choices(["auto", "Chinese", "English"]),
                formats=["mp3", "wav", "flac", "pcm"],
                sample_rates=[8000, 16000, 22050, 24000, 32000, 44100],
                speed={"min": 0.5, "max": 2, "step": 0.05},
            )
            for model in [
                "speech-2.8-hd",
                "speech-2.8-turbo",
                "speech-2.6-hd",
                "speech-2.6-turbo",
                "speech-02-hd",
                "speech-02-turbo",
                "speech-01-hd",
                "speech-01-turbo",
            ]
        ], "https://platform.minimax.io/docs/api-reference/speech-t2a-http"
    openai = [
        preset(
            "gpt-4o-mini-tts",
            formats=OPENAI_FORMATS,
            speed={"min": 0.25, "max": 4, "step": 0.05},
            instructions=True,
        ),
        *[
            preset(
                m,
                formats=OPENAI_FORMATS,
                speed={"min": 0.25, "max": 4, "step": 0.05},
            )
            for m in ["tts-1", "tts-1-hd"]
        ],
    ]
    if provider in {"openai", "azure_openai"}:
        return openai, "https://developers.openai.com/api/docs/guides/text-to-speech"
    if provider == "openrouter":
        for model in openai:
            model["id"] = model["label"] = "openai/" + model["id"]
        # Additional gateway model IDs can still be entered manually.
        return openai + [
            preset(m, formats=["wav", "mp3", "pcm"])
            for m in [
                "google/gemini-2.5-flash-preview-tts",
                "google/gemini-2.5-pro-preview-tts",
                "google/gemini-3.1-flash-tts-preview",
            ]
        ], "https://openrouter.ai/docs/guides/overview/multimodal/audio"
    if provider == "volcengine_speech":
        return [
            preset(
                m,
                languages=choices(["zh-cn", "en", "ja", "id", "es-mx"]),
                formats=["mp3", "wav", "ogg_opus", "pcm"],
                sample_rates=[8000, 16000, 22050, 24000, 32000, 44100, 48000],
                speed={"min": 0.5, "max": 2, "step": 0.05},
                instructions=m == "seed-tts-2.0",
            )
            for m in ["seed-tts-2.0", "seed-tts-1.0", "seed-tts-1.0-concurr"]
        ], "https://www.volcengine.com/docs/6561/1257544"
    if provider == "dashscope":
        qwen_models = [
            preset(
                m,
                languages=choices(
                    "Auto Chinese English German Italian Portuguese Spanish Japanese Korean French Russian".split()
                ),
                formats=["wav"],
                instructions="instruct" in m,
                configuration_note="Qwen3 TTS outputs WAV audio. Match the API key region to the provider URL.",
            )
            for m in ["qwen3-tts-flash", "qwen3-tts-instruct-flash", "qwen3-tts-flash-2025-09-18"]
        ]
        audio_models = ["qwen-audio-3.0-tts-plus", "qwen-audio-3.0-tts-flash"]
        return qwen_models + [
            preset(
                m,
                languages=choices(["zh", "en"]),
                formats=["mp3", "wav", "opus", "pcm"],
                sample_rates=[8000, 12000, 16000, 24000, 48000],
                speed={"min": 0.5, "max": 2, "step": 0.05},
                instructions=True,
                configuration_note="Qwen-Audio TTS requires a Beijing API key. You can set a Beijing workspace URL in the provider connection; the speech endpoint is selected automatically.",
                docs_url="https://help.aliyun.com/zh/model-studio/qwen-audio-tts-voice-list",
            )
            for m in audio_models
        ], "https://help.aliyun.com/zh/model-studio/qwen-tts-voice-list"
    if provider == "groq":
        return [
            preset(
                "canopylabs/orpheus-v1-english",
                max_input_chars=200,
                formats=["wav"],
                language_note="English; vocal directions go in the spoken text.",
            ),
            preset(
                "canopylabs/orpheus-arabic-saudi",
                max_input_chars=200,
                formats=["wav"],
                language_note="Saudi Arabic; enter a voice ID from the provider documentation.",
            ),
        ], "https://console.groq.com/docs/text-to-speech"
    if provider == "siliconflow":
        siliconflow_model = "FunAudioLLM/CosyVoice2-0.5B"
        return [
            preset(
                siliconflow_model,
                formats=["mp3", "wav", "opus", "pcm"],
                language_note="Language follows the text and selected voice. Custom speech: voice IDs are accepted.",
            )
        ], "https://docs.siliconflow.cn/cn/userguide/capabilities/text-to-speech"
    return [], ""


def voice_options(provider: str, service: str) -> dict:
    if service == "tts":
        models, docs = _tts_models(provider)
        fallback = preset(
            "",
            formats=OPENAI_FORMATS,
            language_note="Language follows the text and selected voice.",
        )
        if provider == "minimax":
            fallback = {**deepcopy(models[0]), "id": "", "voices": []}
        elif provider == "volcengine_speech":
            fallback = {**deepcopy(models[0]), "id": "", "voices": [], "instructions": False}
        elif provider == "dashscope":
            fallback = {**deepcopy(models[0]), "id": "", "voices": [], "instructions": False}
            fallback.pop("configuration_note", None)
        elif provider == "groq":
            fallback = preset("", formats=["wav"])
        elif provider == "xiaomi_mimo":
            fallback = preset("", formats=["wav", "pcm16"], instructions=True)
    else:
        ids = {
            "openai": ["gpt-4o-mini-transcribe", "gpt-4o-transcribe", "whisper-1"],
            "azure_openai": ["whisper-1", "gpt-4o-mini-transcribe"],
            "openrouter": ["openai/whisper-large-v3"],
            "groq": ["whisper-large-v3-turbo", "whisper-large-v3"],
            "siliconflow": ["FunAudioLLM/SenseVoiceSmall"],
            "dashscope": ["paraformer-realtime-v2"],
            "volcengine_speech": ["bigmodel"],
        }.get(provider, [])
        languages = VOLC_LANGUAGES if provider == "volcengine_speech" else ISO_LANGUAGES
        if provider == "siliconflow":
            languages = choices(["zh", "en", "ja", "ko", "yue"])
        if provider == "dashscope":
            languages = choices(["zh", "en"])
        models = [preset(m, languages=languages) for m in ids]
        fallback = preset("", languages=languages)
        docs = (
            "https://www.volcengine.com/docs/6561/2608628"
            if provider == "volcengine_speech"
            else ""
        )
    return {"models": models, "fallback": fallback, "docs_url": docs}


def voice_model_options(provider: str, service: str, model: str) -> dict:
    options = voice_options(provider, service)
    # Longest match keeps tts-1-hd distinct from tts-1 and supports dated releases.
    return next(
        (
            item
            for item in sorted(options["models"], key=lambda x: -len(x["id"]))
            if model == item["id"] or model.startswith(item["id"] + "-")
        ),
        options["fallback"],
    )
