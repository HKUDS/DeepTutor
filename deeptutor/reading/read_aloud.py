"""Built-in browser speech extension for Immersive Reading."""

from __future__ import annotations

from deeptutor.reading.extensions import (
    ReadingAction,
    ReadingContext,
    ReadingExtensionManifest,
    ReadingExtensionResult,
)


class ReadAloudExtension:
    """Return server-verified unit text for the browser's speech API."""

    manifest = ReadingExtensionManifest(
        id="read_aloud",
        version="1.0.0",
        name="Read aloud",
        actions=[ReadingAction(id="read", label="Read aloud")],
        result_types=["browser_speech"],
    )

    def run_action(self, action: str, context: ReadingContext) -> ReadingExtensionResult:
        if action != "read":
            raise ValueError(f"Unsupported read-aloud action: {action}")
        return ReadingExtensionResult(
            type="browser_speech",
            payload={"text": context.visible_text, "locale": context.locale},
        )


__all__ = ["ReadAloudExtension"]
