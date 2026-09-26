"""Supported reply languages used by core turn-request validation."""

SUPPORTED_RESPONSE_LANGUAGES: tuple[str, ...] = (
    "en",
    "zh",
    "zh-tw",
    "ja",
    "ko",
    "es",
    "fr",
    "de",
    "ru",
    "pt",
    "it",
    "ar",
    "pl",
    "uk",
)


def validate_reply_language_override(value: str | None) -> str | None:
    """Validate an explicit session choice; ``None`` follows the account default."""
    if value is None:
        return None
    if value not in SUPPORTED_RESPONSE_LANGUAGES:
        raise ValueError("Unsupported reply language")
    return value
