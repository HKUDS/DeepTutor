"""Optional schema-only actions for DeepTutor Immersive Reading."""

from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import re
from typing import Any

from deeptutor.reading.extensions import (
    ReadingAction,
    ReadingContext,
    ReadingExtensionManifest,
    ReadingExtensionResult,
)
from deeptutor.services.llm.exceptions import LLMConfigError


def _sentences(text: str, limit: int = 3) -> list[str]:
    clean = re.sub(r"\s+", " ", text).strip()
    rows = [row.strip() for row in re.split(r"(?<=[.!?。！？])\s*", clean) if row.strip()]
    return rows[:limit] or ([clean[:240]] if clean else [])


class _BaseExtension:
    manifest: ReadingExtensionManifest

    @staticmethod
    def _source(context: ReadingContext) -> str:
        return context.selection or context.visible_text or context.unit_text

    def _check(self, action: str) -> None:
        if action not in {row.id for row in self.manifest.actions}:
            raise ValueError(f"Unknown action {action!r}")

    def submit(
        self, interaction: dict[str, Any], submission: dict[str, Any]
    ) -> ReadingExtensionResult:
        raise ValueError("This extension has no interactive submission.")


class ReadAloudExtension(_BaseExtension):
    manifest = ReadingExtensionManifest(
        id="read_aloud",
        version="0.1.0",
        name="Read aloud",
        actions=[ReadingAction(id="read", label="Read aloud", requires=["visible_text"])],
        result_types=["browser_speech"],
    )

    def run_action(self, action: str, context: ReadingContext) -> ReadingExtensionResult:
        self._check(action)
        return ReadingExtensionResult(
            type="browser_speech",
            title="Read aloud",
            payload={"text": self._source(context), "locale": context.locale},
        )


class GuidedLearnExtension(_BaseExtension):
    manifest = ReadingExtensionManifest(
        id="guided_learn",
        version="0.1.0",
        name="Learn",
        actions=[ReadingAction(id="explain", label="Learn", requires=["visible_text"])],
        result_types=["card"],
    )

    def run_action(self, action: str, context: ReadingContext) -> ReadingExtensionResult:
        self._check(action)
        rows = _sentences(self._source(context))
        return ReadingExtensionResult(
            type="card",
            title="Guided learning",
            payload={
                "overview": rows[0] if rows else "",
                "concepts": rows,
                "example": rows[1] if len(rows) > 1 else (rows[0] if rows else ""),
                "reflection": "What detail in this passage best supports its main idea?",
            },
        )


class VocabularyExtension(_BaseExtension):
    manifest = ReadingExtensionManifest(
        id="vocabulary",
        version="0.1.0",
        name="Vocabulary",
        actions=[ReadingAction(id="hint", label="Vocabulary", requires=["selection"])],
        result_types=["card"],
    )

    def run_action(self, action: str, context: ReadingContext) -> ReadingExtensionResult:
        self._check(action)
        word = (context.selection.strip().split() or [""])[0][:80]
        dictionary = os.environ.get("DEEPTUTOR_READING_DICTIONARY", "").strip()
        if not word:
            message = "Select one word in the page to get a contextual clue."
            definition = ""
        elif not dictionary:
            message = (
                "Configure DEEPTUTOR_READING_DICTIONARY with a local JSON dictionary path "
                "to reveal definitions."
            )
            definition = ""
        else:
            definition, message = _dictionary_lookup(Path(dictionary), word)
        return ReadingExtensionResult(
            type="card",
            title=word or "Vocabulary",
            message=message,
            payload={
                "word": word,
                "definition": definition,
                "context": (_sentences(context.unit_text, 1) or [""])[0],
            },
        )


class TranslationExtension(_BaseExtension):
    manifest = ReadingExtensionManifest(
        id="translation",
        version="0.1.0",
        name="Translate",
        actions=[ReadingAction(id="translate", label="Translate", requires=["visible_text"])],
        result_types=["card"],
    )

    async def run_action(self, action: str, context: ReadingContext) -> ReadingExtensionResult:
        self._check(action)
        model = os.environ.get("DEEPTUTOR_READING_TRANSLATION_MODEL", "").strip()
        provider = os.environ.get("DEEPTUTOR_READING_TRANSLATION_PROVIDER", "").strip()
        if not model:
            return ReadingExtensionResult(
                type="card",
                title="Translation",
                message=(
                    "Configure DEEPTUTOR_READING_TRANSLATION_MODEL with an installed model "
                    "ID to enable translation."
                ),
                payload={"source_text": self._source(context)[:2000]},
            )

        from deeptutor.services.llm import complete

        source = self._source(context)[:12_000]
        try:
            translated = await complete(
                source,
                system_prompt=(
                    "Translate the supplied reading passage into Chinese. Preserve Markdown "
                    "structure and technical terms. Return only the translation."
                ),
                model=model,
                binding=provider or None,
                max_tokens=4096,
            )
        except LLMConfigError as exc:
            detail = str(exc)[:3900]
            return ReadingExtensionResult(
                type="card",
                title="Translation",
                message=f"Translation is not configured correctly: {detail}",
                payload={"source_text": source},
            )
        return ReadingExtensionResult(
            type="card",
            title="Translation",
            payload={"source_text": source, "translation": translated},
        )


def _dictionary_lookup(path: Path, word: str) -> tuple[str, str]:
    try:
        if path.stat().st_size > 2 * 1024 * 1024:
            return "", "The configured dictionary exceeds the 2 MB safety limit."
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return "", "The configured dictionary file does not exist."
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return "", "The configured dictionary must be a readable JSON object."
    if not isinstance(payload, dict):
        return "", "The configured dictionary must contain a JSON object."
    entries = {str(key).casefold(): value for key, value in payload.items()}
    value = entries.get(word.casefold())
    if value is None:
        return "", f"No local definition was found for {word!r}."
    if isinstance(value, list):
        definition = "; ".join(str(item) for item in value)
    else:
        definition = str(value)
    return definition[:4000], "Local dictionary"


class QuizExtension(_BaseExtension):
    manifest = ReadingExtensionManifest(
        id="quiz",
        version="0.1.0",
        name="Test",
        actions=[ReadingAction(id="start", label="Test", requires=["visible_text"])],
        result_types=["quiz", "feedback"],
    )

    def run_action(self, action: str, context: ReadingContext) -> ReadingExtensionResult:
        self._check(action)
        source = self._source(context)
        choices = _sentences(source)
        while len(choices) < 3:
            choices.append("Not stated in this passage")
        questions = [
            {
                "id": f"q{index + 1}",
                "prompt": "Which statement appears in the current passage?",
                "choices": choices[index:] + choices[:index],
            }
            for index in range(3)
        ]
        interaction_id = sha256(
            f"{context.material_id}|{context.locator}|{source}".encode()
        ).hexdigest()[:24]
        return ReadingExtensionResult(
            type="quiz",
            interaction_id=interaction_id,
            title="Three-question check",
            payload={
                "questions": questions,
                "_answers": {f"q{index + 1}": 0 for index in range(3)},
            },
        )

    def submit(
        self, interaction: dict[str, Any], submission: dict[str, Any]
    ) -> ReadingExtensionResult:
        expected = interaction.get("private", {}).get("answers", {})
        answers = submission.get("answers")
        answers = answers if isinstance(answers, dict) else {}
        score = sum(1 for key, value in expected.items() if answers.get(key) == value)
        return ReadingExtensionResult(
            type="feedback",
            interaction_id=str(interaction.get("interaction_id") or ""),
            title="Quiz result",
            message=f"{score}/{len(expected)}",
            payload={"score": score, "total": len(expected), "completed": True},
        )


__all__ = [
    "GuidedLearnExtension",
    "QuizExtension",
    "ReadAloudExtension",
    "TranslationExtension",
    "VocabularyExtension",
]
