"""French is a first-class UI/output language, not a half-wired one.

The French catalog used to fall back to English on hundreds of keys, so a user
who selected French still saw English screens. These tests pin the catalog and
the partner reply-language seam that made "Auto" hardcode English.
"""

from __future__ import annotations

import ast
import json
import pathlib
import re

import pytest

from deeptutor.book.export import _LABELS as BOOK_EXPORT_LABELS
from deeptutor.book.overview_copy import _COPY as BOOK_OVERVIEW_COPY
from deeptutor.runtime.banner import LABELS, labels_for
from deeptutor.services.config.launch_settings import (
    _normalize_language as _launch_language,
)
from deeptutor.services.config.settings_spec import _LANGUAGE_CHOICES
from deeptutor.services.i18n import _MESSAGES as BACKEND_MESSAGES
from deeptutor.services.i18n import _parse_language
from deeptutor.services.i18n import t as backend_t
from deeptutor.services.prompt.language import language_directive, language_label
from deeptutor.services.settings.interface_settings import (
    _normalize_language,
    _normalize_response_language,
)

WEB = pathlib.Path(__file__).resolve().parents[2] / "web"


@pytest.mark.parametrize("raw", ["fr", "FR", " fr ", "french", "français", "francais", "fr-FR"])
def test_normalizer_accepts_french_spellings(raw: str) -> None:
    assert _normalize_language(raw) == "fr"


@pytest.mark.parametrize("raw", ["fr-BR", "french", "français", "francais"])
def test_launch_settings_accept_french(raw: str) -> None:
    assert _launch_language(raw) == "fr"


def test_response_language_accepts_native_french_name() -> None:
    assert _normalize_response_language("français") == "fr"


def test_settings_offers_french() -> None:
    assert "fr" in {code for code, _label, _desc in _LANGUAGE_CHOICES}


def test_language_directive_names_french() -> None:
    assert language_label("fr") == "Français"
    assert "Français" in language_directive("fr")


def test_cli_banner_is_fully_translated() -> None:
    assert set(LABELS["fr"]) == set(LABELS["en"])
    assert labels_for("fr") is LABELS["fr"]
    assert labels_for("fr-FR") is LABELS["fr"]
    assert labels_for("français") is LABELS["fr"]
    assert labels_for("francais") is LABELS["fr"]


def test_backend_messages_speak_french() -> None:
    assert set(BACKEND_MESSAGES["fr"]) == set(BACKEND_MESSAGES["en"])
    assert _parse_language("fr-FR") == "fr"
    assert "Partenaire" in backend_t("api.partner_not_found", language="fr")


def test_book_overview_and_export_speak_french() -> None:
    assert set(BOOK_OVERVIEW_COPY["fr"]) == set(BOOK_OVERVIEW_COPY["en"])
    assert set(BOOK_EXPORT_LABELS["fr"]) == set(BOOK_EXPORT_LABELS["en"])


def test_quiz_judge_speaks_french() -> None:
    """The judge whitelist is derived from its prompts, so pin the prompt."""
    tree = ast.parse(
        (WEB.parent / "deeptutor/api/routers/quiz_judge.py").read_text(encoding="utf-8")
    )
    prompts = next(
        ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(getattr(target, "id", None) == "_JUDGE_SYSTEM_PROMPTS" for target in node.targets)
    )
    assert "fr" in prompts
    assert "français" in prompts["fr"]


def test_web_locale_covers_every_english_key() -> None:
    """No French screen may fall back to English for a missing key."""
    en = json.loads((WEB / "locales/en/app.json").read_text(encoding="utf-8"))
    fr = json.loads((WEB / "locales/fr/app.json").read_text(encoding="utf-8"))
    assert set(en) <= set(fr)


def test_web_common_locale_covers_every_english_key() -> None:
    en = json.loads((WEB / "locales/en/common.json").read_text(encoding="utf-8"))
    fr = json.loads((WEB / "locales/fr/common.json").read_text(encoding="utf-8"))
    assert set(en) <= set(fr)


def test_web_locale_keeps_interpolation_placeholders() -> None:
    en = json.loads((WEB / "locales/en/app.json").read_text(encoding="utf-8"))
    fr = json.loads((WEB / "locales/fr/app.json").read_text(encoding="utf-8"))
    pattern = re.compile(r"\{\{[^}]+\}\}")
    mismatches = [
        key
        for key in set(en) & set(fr)
        if set(pattern.findall(en[key])) != set(pattern.findall(fr[key]))
    ]
    assert mismatches == []


def test_partner_reply_language_picker_follows_the_account_language() -> None:
    """Auto must use the selected model output language, not hardcoded English."""
    picker = (WEB / "components/partners/PartnerReplyLanguageSelect.tsx").read_text(
        encoding="utf-8"
    )
    assert "readStoredResponseLanguage" in picker
    assert "RESPONSE_LANGUAGE_OPTIONS.map" in picker

    surfaces = [
        WEB / "app/(workspace)/partners/new/page.tsx",
        WEB / "components/partners/PartnerConfigure.tsx",
    ]
    for path in surfaces:
        source = path.read_text(encoding="utf-8")
        assert "PartnerReplyLanguageSelect" in source
        assert 't("Auto (English)")' not in source
