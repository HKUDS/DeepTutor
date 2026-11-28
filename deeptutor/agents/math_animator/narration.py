"""Turn spoken Manim section markers into synchronized audio and holds."""

from __future__ import annotations

import ast
import asyncio
import hashlib
import io
from pathlib import Path
import shutil
import subprocess
from typing import Awaitable, Callable
import wave

from deeptutor.i18n import StatusI18n
from deeptutor.services.config.provider_runtime import resolve_tts_runtime_config
from deeptutor.services.voice import synthesize_speech
from deeptutor.services.voice.audio import _parse_pcm_content_type, _pcm16_to_wav
from deeptutor.services.voice.base import VoiceProviderError

NARRATION_PREFIX = "narration:"


def narration_text(node: ast.AST) -> str | None:
    """Recognize literal self.next_section('narration:...') statements."""
    if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
        return None
    call = node.value
    if (
        not isinstance(call.func, ast.Attribute)
        or not isinstance(call.func.value, ast.Name)
        or call.func.value.id != "self"
        or call.func.attr != "next_section"
        or not call.args
        or not isinstance(call.args[0], ast.Constant)
        or not isinstance(call.args[0].value, str)
    ):
        return None
    name = call.args[0].value
    return name[len(NARRATION_PREFIX) :].strip() if name.startswith(NARRATION_PREFIX) else None


_FINISH_SPEECH = """\
if getattr(self, '_dt_narration_end', 0) > self.time:
    self.wait(self._dt_narration_end - self.time)
"""


class _NarrationTransformer(ast.NodeTransformer):
    """Insert audio starts and holds without executing the generated script."""

    def __init__(self, clips: dict[str, tuple[Path, float]]) -> None:
        self.clips = clips

    def visit_Expr(self, node: ast.Expr) -> ast.AST | list[ast.stmt]:
        text = narration_text(node)
        if text is None or text not in self.clips:
            return self.generic_visit(node)
        path, duration = self.clips[text]
        return ast.parse(
            _FINISH_SPEECH
            + f"self.add_sound({str(path)!r})\n"
            + f"self._dt_narration_end = self.time + {duration!r}\n"
        ).body

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.FunctionDef:
        self.generic_visit(node)
        if node.name != "construct":
            return node
        # A finally block also protects early returns from clipping the last phrase.
        node.body = [
            ast.Try(
                body=node.body, handlers=[], orelse=[], finalbody=ast.parse(_FINISH_SPEECH).body
            )
        ]
        return node


class NarrationService:
    """Synthesize and cache speech for a single Manim render/retry loop."""

    def __init__(self, audio_dir: Path, language: str = "zh") -> None:
        self.audio_dir = audio_dir
        self._clips: dict[str, tuple[Path, float]] = {}
        self.i18n = StatusI18n("math_animator", language, module="math_animator")

    async def prepare(
        self, code: str, progress: Callable[[str], Awaitable[None]] | None = None
    ) -> str:
        """Use the active TTS model; unconfigured installations retain silent video."""
        try:
            config = resolve_tts_runtime_config()
        except ValueError as exc:
            if str(exc).startswith("No active TTS model is configured."):
                return code
            raise
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            from .renderer import ManimRenderError

            raise ManimRenderError(
                f"Generated Manim code has invalid Python syntax: {exc}"
            ) from exc
        texts = list(
            dict.fromkeys(
                text for node in ast.walk(tree) if (text := narration_text(node)) is not None
            )
        )
        if not texts or any(not text for text in texts):
            # A code error can be repaired; provider errors must not trigger code retries.
            from .renderer import ManimRenderError

            raise ManimRenderError(
                "Video narration is required with the configured TTS model. Add literal "
                "self.next_section('narration:spoken explanation') calls at the start of "
                "each teaching beat inside construct(). Use short spoken sentences."
            )
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        clips: dict[str, tuple[Path, float]] = {}
        for index, text in enumerate(texts, 1):
            if len(text) > config.max_input_chars:
                from .renderer import ManimRenderError

                raise ManimRenderError(
                    "Narration segment is too long; split it into shorter beats."
                )
            cache_key = hashlib.sha256(
                repr(
                    (
                        text,
                        config.model,
                        config.voice,
                        config.base_url,
                        config.instructions,
                        config.speed,
                        config.response_format,
                    )
                ).encode()
            ).hexdigest()
            if cache_key not in self._clips:
                if progress:
                    await progress(
                        self.i18n.t(
                            "narration_synthesizing",
                            "Synthesizing narration {index}/{total} ({model}).",
                            index=index,
                            total=len(texts),
                            model=config.model,
                        )
                    )
                audio, content_type = await synthesize_speech(text)
                path = self.audio_dir / f"{cache_key}.wav"
                duration = await asyncio.to_thread(_save_wav, audio, content_type, path)
                self._clips[cache_key] = path, duration
            # The transform maps spoken text to this invocation's selected voice.
            clips[text] = self._clips[cache_key]
        transformed = _NarrationTransformer(clips).visit(tree)
        return ast.unparse(ast.fix_missing_locations(transformed)) + "\n"


def _save_wav(audio: bytes, content_type: str, path: Path) -> float:
    pcm = _parse_pcm_content_type(content_type)
    if pcm:
        audio = _pcm16_to_wav(audio, sample_rate=pcm[0], channels=pcm[1])
    try:
        with wave.open(io.BytesIO(audio), "rb") as wav:
            duration = wav.getnframes() / wav.getframerate()
        path.write_bytes(audio)
    except (wave.Error, EOFError):
        source = path.with_suffix(".input")
        source.write_bytes(audio)
        try:
            ffmpeg = shutil.which("ffmpeg")
            if ffmpeg is None:
                raise VoiceProviderError("FFmpeg is required to decode narration audio.")
            subprocess.run(
                [
                    ffmpeg,
                    "-y",
                    "-v",
                    "error",
                    "-i",
                    str(source),
                    "-vn",
                    "-ac",
                    "1",
                    "-ar",
                    "24000",
                    "-c:a",
                    "pcm_s16le",
                    str(path),
                ],
                check=True,
                capture_output=True,
                timeout=60,
            )
            with wave.open(str(path), "rb") as wav:
                duration = wav.getnframes() / wav.getframerate()
        except (OSError, subprocess.SubprocessError, wave.Error, EOFError) as exc:
            raise VoiceProviderError(
                "Could not decode narration audio; check FFmpeg and TTS output."
            ) from exc
        finally:
            source.unlink(missing_ok=True)
    if duration <= 0:
        raise VoiceProviderError("TTS returned narration with no audio frames.")
    return duration
