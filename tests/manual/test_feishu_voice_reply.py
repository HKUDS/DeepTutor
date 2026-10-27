"""End-to-end voice-reply test: TTS → opus → Feishu upload → audio message.

Uses the real partner config (app credentials) and sends one audio message
to the most recently active Feishu p2p chat.
"""
import asyncio
import sys

sys.path.insert(0, "/Users/olive/DeepTutor")

import yaml

from deeptutor.partners.bus.queue import MessageBus
from deeptutor.partners.channels.feishu import FEISHU_AVAILABLE, FeishuChannel, FeishuConfig

CONFIG_PATH = "/Users/olive/DeepTutor/data/partners/partner-f3b7f3f4/config.yaml"
TARGET_OPEN_ID = "ou_8bd32fa2601af4bb67e6d7c192788fc6"

TEST_TEXT = (
    "**语音回复测试**：你好！这是 DeepTutor 的语音回复功能测试，"
    "由本地 TTS 服务合成。`代码`和[链接](http://example.com)已在合成前剥离。"
)


def main() -> None:
    assert FEISHU_AVAILABLE, "lark_oapi not installed"
    with open(CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)["channels"]["feishu"]
    config = FeishuConfig.model_validate(cfg)
    print("voice_reply enabled:", config.voice_reply)

    import lark_oapi as lark
    from lark_oapi.core.const import FEISHU_DOMAIN

    from deeptutor.partners.channels.lark_http import install_keep_alive

    install_keep_alive()
    channel = FeishuChannel(config, MessageBus())
    channel._client = (
        lark.Client.builder()
        .app_id(config.app_id)
        .app_secret(config.app_secret)
        .domain(FEISHU_DOMAIN)
        .log_level(lark.LogLevel.INFO)
        .build()
    )

    plain = channel._strip_markdown_for_tts(TEST_TEXT)
    print("stripped text:", plain)

    wav = channel._synthesize_tts_sync(plain)
    print("tts wav bytes:", len(wav) if wav else None)
    assert wav

    converted = channel._wav_to_opus_sync(wav)
    assert converted, "opus conversion failed"
    opus, duration_ms = converted
    print("opus bytes:", len(opus), "duration_ms:", duration_ms)

    file_key = channel._upload_voice_sync(opus, duration_ms)
    print("file_key:", file_key)
    assert file_key

    import json

    sent = channel._send_message_sync(
        "open_id", TARGET_OPEN_ID, "audio", json.dumps({"file_key": file_key})
    )
    print("audio message sent:", sent)
    assert sent, "audio message delivery failed"
    print("OK: full voice pipeline succeeded, audio delivered to", TARGET_OPEN_ID)


if __name__ == "__main__":
    main()
