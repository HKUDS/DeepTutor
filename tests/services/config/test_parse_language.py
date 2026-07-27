import pytest

from deeptutor.services.config.loader import parse_language


@pytest.mark.parametrize(
    "input_val, expected",
    [
        ("en", "en"),
        ("English", "en"),
        ("ENGLISH", "en"),
        ("zh", "zh"),
        ("Chinese", "zh"),
        ("cn", "zh"),
        ("CN", "zh"),
        ("ja", "ja"),
        ("ko", "ko"),
        ("fr", "fr"),
        ("de", "de"),
        ("es", "es"),
        ("ru", "ru"),
        ("pt", "pt"),
        ("it", "it"),
        ("Japanese", "ja"),
        ("Korean", "ko"),
        ("French", "fr"),
        ("German", "de"),
        ("Spanish", "es"),
        ("Russian", "ru"),
        ("Portuguese", "pt"),
        ("Italian", "it"),
        (None, "en"),
        ("", "en"),
        (42, "en"),
        ({}, "en"),
        ("pt-BR", "pt-br"),
        ("zh-TW", "zh-tw"),
        ("  en  ", "en"),
        (" ja ", "ja"),
    ],
)
def test_parse_language(input_val, expected):
    assert parse_language(input_val) == expected
