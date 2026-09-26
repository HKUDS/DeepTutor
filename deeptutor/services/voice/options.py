"""Speech configuration hints, shared by settings and runtime defaults.

These are curated suggestions, not an exhaustive entitlement/model inventory.
Unknown models and private voices remain editable. Match the model family before
suggesting voices: a gateway's vendor name alone does not identify its TTS API.
Sources checked 2026-09-17 are included in each provider's public metadata.
"""

from __future__ import annotations

from copy import deepcopy


def choices(values: list[str]) -> list[dict]:
    return [{"id": value, "label": value} for value in values]


OPENAI_VOICES = choices(
    "alloy ash ballad coral echo fable nova onyx sage shimmer verse marin cedar".split()
)
LEGACY_OPENAI_VOICES = choices("alloy ash coral echo fable onyx nova sage shimmer".split())
GEMINI_VOICES = choices(
    "Kore Puck Charon Fenrir Aoede Leda Orus Zephyr Achernar Achird Algenib Algieba Alnilam Autonoe Callirrhoe Despina Enceladus Erinome Gacrux Iapetus Laomedeia Pulcherrima Rasalgethi Sadachbia Sadaltager Schedar Sulafat Umbriel Vindemiatrix Zubenelgenubi".split()
)
ISO_LANGUAGES = choices("zh en ja ko de fr es pt it ru ar id".split())
VOLC_LANGUAGES = choices(
    "zh-CN en-US ja-JP id-ID es-MX pt-BR de-DE fr-FR ko-KR fil-PH ms-MY th-TH ar-SA it-IT bn-BD el-GR nl-NL ru-RU tr-TR vi-VN pl-PL ro-RO ne-NP uk-UA yue-CN".split()
)
OPENAI_FORMATS = ["mp3", "wav", "opus", "aac", "flac", "pcm"]


def preset(model: str, *, voices=None, languages=None, formats=None, **kwargs) -> dict:
    return {
        "id": model,
        "label": model,
        "voices": voices or [],
        "languages": languages or [],
        "formats": formats or [],
        **kwargs,
    }


def _tts_models(provider: str) -> tuple[list[dict], str]:
    openai = [
        preset(
            "gpt-4o-mini-tts",
            voices=OPENAI_VOICES,
            formats=OPENAI_FORMATS,
            speed={"min": 0.25, "max": 4, "step": 0.05},
            instructions=True,
        ),
        *[
            preset(
                m,
                voices=LEGACY_OPENAI_VOICES,
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
            preset(m, voices=GEMINI_VOICES, formats=["wav", "mp3", "pcm"])
            for m in [
                "google/gemini-2.5-flash-preview-tts",
                "google/gemini-2.5-pro-preview-tts",
                "google/gemini-3.1-flash-tts-preview",
            ]
        ], "https://openrouter.ai/docs/guides/overview/multimodal/audio"
    if provider == "volcengine_speech":
        v2 = [
            {
                "id": "zh_female_vv_uranus_bigtts",
                "label": "Vivi 2.0",
                "languages": ["zh-cn", "en", "ja", "id", "es-mx"],
            },
            {
                "id": "zh_female_xiaohe_uranus_bigtts",
                "label": "小何 2.0",
                "languages": ["zh-cn", "en"],
            },
            {"id": "zh_male_m191_uranus_bigtts", "label": "云舟 2.0", "languages": ["zh-cn", "en"]},
            {
                "id": "zh_male_taocheng_uranus_bigtts",
                "label": "小天 2.0",
                "languages": ["zh-cn", "en"],
            },
            {
                "id": "zh_female_yingyujiaoxue_uranus_bigtts",
                "label": "Tina老师 2.0",
                "languages": ["zh-cn", "en"],
            },
            {"id": "en_male_tim_uranus_bigtts", "label": "Tim", "languages": ["en"]},
            {"id": "en_female_dacey_uranus_bigtts", "label": "Dacey", "languages": ["en"]},
        ]
        v1 = [
            {
                "id": "zh_female_shuangkuaisisi_moon_bigtts",
                "label": "爽快思思",
                "languages": ["zh-cn", "en"],
            },
            {
                "id": "zh_male_wennuanahu_moon_bigtts",
                "label": "温暖阿虎",
                "languages": ["zh-cn", "en"],
            },
        ]
        return [
            preset(
                m,
                voices=v2 if m == "seed-tts-2.0" else v1,
                languages=choices(["zh-cn", "en", "ja", "id", "es-mx"]),
                formats=["mp3", "wav", "ogg_opus", "pcm"],
                sample_rates=[8000, 16000, 22050, 24000, 32000, 44100, 48000],
                speed={"min": 0.5, "max": 2, "step": 0.05},
                instructions=m == "seed-tts-2.0",
            )
            for m in ["seed-tts-2.0", "seed-tts-1.0", "seed-tts-1.0-concurr"]
        ], "https://www.volcengine.com/docs/6561/1257544"
    if provider == "dashscope":
        # The September 2025 snapshot has fewer voices than current Flash.
        qwen_voices = [
            {"id": "Cherry", "label": "芊悦 · Cherry"},
            {"id": "Serena", "label": "苏瑶 · Serena"},
            {"id": "Ethan", "label": "晨煦 · Ethan"},
            {"id": "Chelsie", "label": "千雪 · Chelsie"},
            {"id": "Momo", "label": "茉兔 · Momo"},
            {"id": "Kai", "label": "凯 · Kai"},
        ]
        return [
            preset(
                m,
                voices=[v for v in qwen_voices if v["id"] in {"Cherry", "Ethan"}]
                if m.endswith("2025-09-18")
                else qwen_voices,
                languages=choices(
                    "Auto Chinese English German Italian Portuguese Spanish Japanese Korean French Russian".split()
                ),
                formats=["wav"],
                instructions="instruct" in m,
            )
            for m in ["qwen3-tts-flash", "qwen3-tts-instruct-flash", "qwen3-tts-flash-2025-09-18"]
        ], "https://help.aliyun.com/zh/model-studio/qwen-tts-voice-list"
    if provider == "groq":
        return [
            preset(
                "canopylabs/orpheus-v1-english",
                voices=choices(["autumn", "diana", "hannah", "austin", "daniel", "troy"]),
                max_input_chars=200,
                formats=["wav"],
                language_note="English; vocal directions go in the spoken text.",
            ),
            preset(
                "canopylabs/orpheus-arabic-saudi",
                voices=choices(["abdullah", "fahad", "sultan", "lulwa", "noura", "aisha"]),
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
                voices=[
                    {"id": f"{siliconflow_model}:{v}", "label": v}
                    for v in "alex benjamin charles david anna bella claire diana".split()
                ],
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
        if provider == "volcengine_speech":
            fallback = {**deepcopy(models[0]), "id": "", "voices": [], "instructions": False}
        elif provider == "dashscope":
            fallback = {**deepcopy(models[0]), "id": "", "voices": [], "instructions": False}
        elif provider == "groq":
            fallback = preset("", formats=["wav"])
    else:
        ids = {
            "openai": ["gpt-4o-mini-transcribe", "gpt-4o-transcribe", "whisper-1"],
            "azure_openai": ["whisper-1", "gpt-4o-mini-transcribe"],
            "openrouter": ["openai/whisper-large-v3"],
            "groq": ["whisper-large-v3-turbo", "whisper-large-v3"],
            "siliconflow": ["FunAudioLLM/SenseVoiceSmall"],
            "dashscope": ["paraformer-v2"],
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
