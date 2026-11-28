"""Speech timing, provider failures, and an actual Manim audio export."""

import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
import wave

from deeptutor.agents.math_animator.narration import NarrationService, _save_wav
from deeptutor.agents.math_animator.renderer import ManimRenderError, ManimRenderService
from deeptutor.services.voice.base import VoiceProviderError
from deeptutor.services.voice.config import TTSConfig


def wav_audio(seconds: float = 1.0) -> bytes:
    """Build deterministic PCM WAV speech for offline timing checks."""
    out = io.BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(b"\x01\x00" * int(24000 * seconds))
    return out.getvalue()


CODE = """
class Demo(Scene):
    def construct(self):
        self.next_section("narration:first")
        self.wait(0.1)
        self.next_section("narration:second")
        self.wait(0.1)
"""


class FakeScene:
    """Track speech starts and elapsed scene time without rendering visuals."""

    def __init__(self) -> None:
        self.time = 0
        self.starts = []

    def wait(self, seconds: float) -> None:
        self.time += seconds

    def add_sound(self, path: str) -> None:
        self.starts.append(self.time)


class NarrationTests(unittest.IsolatedAsyncioTestCase):
    """Verify timing, retry caching, error reporting, and exported audio."""

    async def test_waits_for_each_phrase_and_reuses_speech_on_retry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = NarrationService(Path(directory))
            with (
                patch(
                    "deeptutor.agents.math_animator.narration.resolve_tts_runtime_config",
                    return_value=TTSConfig(model="test"),
                ),
                patch(
                    "deeptutor.agents.math_animator.narration.synthesize_speech",
                    new=AsyncMock(return_value=(wav_audio(), "audio/wav")),
                ) as speech,
            ):
                transformed = await service.prepare(CODE)
                await service.prepare(CODE)
            self.assertEqual(speech.await_count, 2)
            namespace = {"Scene": FakeScene}
            exec(transformed, namespace)
            scene = namespace["Demo"]()
            scene.construct()
            self.assertEqual(scene.starts, [0, 1])
            self.assertAlmostEqual(scene.time, 2)

    async def test_last_phrase_survives_early_return(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch(
                "deeptutor.agents.math_animator.narration.resolve_tts_runtime_config",
                return_value=TTSConfig(model="test"),
            ),
            patch(
                "deeptutor.agents.math_animator.narration.synthesize_speech",
                new=AsyncMock(return_value=(wav_audio(), "audio/wav")),
            ),
        ):
            code = await NarrationService(Path(directory)).prepare(
                CODE.replace("self.wait(0.1)", "return", 1)
            )
            namespace = {"Scene": FakeScene}
            exec(code, namespace)
            scene = namespace["Demo"]()
            scene.construct()
            self.assertAlmostEqual(scene.time, 1)

    async def test_unconfigured_tts_leaves_code_unchanged(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch(
                "deeptutor.agents.math_animator.narration.resolve_tts_runtime_config",
                side_effect=ValueError(
                    "No active TTS model is configured. Set it in Settings > Voice."
                ),
            ),
            patch("deeptutor.agents.math_animator.narration.synthesize_speech") as speech,
        ):
            self.assertEqual(await NarrationService(Path(directory)).prepare(CODE), CODE)
            speech.assert_not_called()

    async def test_missing_markers_can_be_repaired_but_provider_errors_propagate(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch(
                "deeptutor.agents.math_animator.narration.resolve_tts_runtime_config",
                return_value=TTSConfig(model="test"),
            ),
        ):
            service = NarrationService(Path(directory))
            with self.assertRaises(ManimRenderError):
                await service.prepare("class Demo(Scene):\n    def construct(self): pass\n")
            with patch(
                "deeptutor.agents.math_animator.narration.synthesize_speech",
                new=AsyncMock(side_effect=VoiceProviderError("provider unavailable")),
            ):
                with self.assertRaises(VoiceProviderError):
                    await service.prepare(CODE)

    async def test_pcm_audio_is_wrapped_with_its_declared_sample_rate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "speech.wav"
            duration = _save_wav(b"\x01\x00" * 16000, "audio/pcm;rate=16000;channels=1", path)
            self.assertEqual(duration, 1)
            with wave.open(str(path)) as wav:
                self.assertEqual(wav.getframerate(), 16000)

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg required")
    async def test_compressed_speech_is_decoded_before_scheduling(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.wav"
            source.write_bytes(wav_audio())
            compressed = root / "speech.mp3"
            subprocess.run(
                [shutil.which("ffmpeg"), "-v", "error", "-i", str(source), str(compressed)],
                check=True,
                capture_output=True,
                timeout=30,
            )
            target = root / "decoded.wav"
            duration = _save_wav(compressed.read_bytes(), "audio/mpeg", target)
            self.assertAlmostEqual(duration, 1, places=1)
            with wave.open(str(target)) as wav:
                self.assertEqual(wav.getnchannels(), 1)

    @unittest.skipUnless(shutil.which("ffprobe"), "FFprobe required")
    async def test_real_export_has_audio_and_does_not_clip_narration(self) -> None:
        try:
            import manim
        except ImportError:
            self.skipTest("Manim required")
        with (
            tempfile.TemporaryDirectory() as directory,
            patch(
                "deeptutor.agents.math_animator.narration.resolve_tts_runtime_config",
                return_value=TTSConfig(model="test"),
            ),
            patch(
                "deeptutor.agents.math_animator.narration.synthesize_speech",
                new=AsyncMock(return_value=(wav_audio(), "audio/wav")),
            ),
        ):
            root = Path(directory)
            renderer = ManimRenderService("test", output_dir=root / "out", workspace_root=root)
            result = await renderer.render(
                code="from manim import *\n" + CODE, output_mode="video", quality="low"
            )
            info = json.loads(
                subprocess.check_output(
                    [
                        "ffprobe",
                        "-v",
                        "error",
                        "-show_entries",
                        "stream=codec_type,duration",
                        "-of",
                        "json",
                        str(root / result.artifacts[0].relative_path),
                    ]
                )
            )
            streams = {stream["codec_type"]: stream for stream in info["streams"]}
            self.assertIn("audio", streams)
            self.assertGreaterEqual(float(streams["video"]["duration"]), 2)
            self.assertGreaterEqual(float(streams["audio"]["duration"]), 2)


if __name__ == "__main__":
    unittest.main()
