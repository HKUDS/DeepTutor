"""``slugify_partner_id`` must yield ASCII/URL-safe ids.

Partner ids ride in ``/partners/<id>`` links and become on-disk directory
names, so a non-Latin id (e.g. a raw CJK name) produced an unreachable link.
These tests pin the ASCII-safe behavior and the stable per-name fallback used
for names that have no ASCII characters at all.
"""

from __future__ import annotations

import string

from deeptutor.services.partners.manager import slugify_partner_id, slugify_soul_id

_ALLOWED = set(string.ascii_lowercase + string.digits + "-")


def _is_url_safe(slug: str) -> bool:
    return bool(slug) and slug.isascii() and set(slug) <= _ALLOWED


class TestAsciiNames:
    def test_lowercases_and_hyphenates(self):
        assert slugify_partner_id("Ada Lovelace") == "ada-lovelace"

    def test_collapses_runs_and_strips_edges(self):
        assert slugify_partner_id("  Study  Buddy!!!  ") == "study-buddy"
        assert slugify_partner_id("--Hi--") == "hi"

    def test_underscore_is_not_kept(self):
        # Underscore must not survive: it would let an id collide with the
        # reserved ``_souls`` directory.
        slug = slugify_partner_id("my_bot")
        assert slug == "my-bot"
        assert "_" not in slug

    def test_result_is_url_safe(self):
        for name in ("Ada", "R2-D2", "Café au lait", "数学老师Bot"):
            assert _is_url_safe(slugify_partner_id(name))


class TestNonLatinNames:
    def test_pure_cjk_falls_back_to_ascii_handle(self):
        slug = slugify_partner_id("小助手")
        assert _is_url_safe(slug)
        assert slug.startswith("partner-")

    def test_same_name_is_stable(self):
        # Same name -> same id, so the create-time duplicate check still fires.
        assert slugify_partner_id("小助手") == slugify_partner_id("小助手")

    def test_distinct_cjk_names_get_distinct_ids(self):
        # The whole point of the fallback: two different non-Latin names must
        # not both collapse to the same "partner" id.
        assert slugify_partner_id("小助手") != slugify_partner_id("数学老师")

    def test_mixed_name_keeps_the_ascii_part(self):
        assert slugify_partner_id("小助手Bot") == "bot"


class TestSoulSlug:
    """``slugify_soul_id`` shares the partner logic but falls back to ``soul``.

    Soul ids ride in ``/souls/<id>`` URLs, so the same ASCII-safety guarantees
    must hold.
    """

    def test_ascii_name_slugged(self):
        assert slugify_soul_id("Rigorous Tutor") == "rigorous-tutor"

    def test_pure_cjk_falls_back_to_soul_handle(self):
        slug = slugify_soul_id("我的灵魂")
        assert _is_url_safe(slug)
        assert slug.startswith("soul-")

    def test_distinct_cjk_names_get_distinct_ids(self):
        assert slugify_soul_id("我的灵魂") != slugify_soul_id("严谨助教")

    def test_fallback_prefix_differs_from_partner(self):
        # Same pure-CJK name → different prefixes, so a soul id and a partner id
        # derived from the same name never collide by construction.
        name = "我的灵魂"
        assert slugify_soul_id(name).startswith("soul-")
        assert slugify_partner_id(name).startswith("partner-")

    def test_empty_becomes_soul(self):
        assert slugify_soul_id("   ") == "soul"


class TestDegenerate:
    def test_empty_and_whitespace_become_partner(self):
        assert slugify_partner_id("") == "partner"
        assert slugify_partner_id("   ") == "partner"

    def test_punctuation_only_falls_back(self):
        # No ASCII alphanumerics survive, but the name is non-empty -> stable
        # per-name handle rather than a bare "partner".
        slug = slugify_partner_id("!!!")
        assert _is_url_safe(slug)
        assert slug.startswith("partner-")
