"""Tests for bilingual source pairing logic."""

import pytest

from deeptutor.services.web_source.pairing import (
    compute_pair_status,
    group_sources_by_origin,
    infer_language,
    language_prefix,
    normalize_origin,
    pair_file_paths,
    pair_key_for,
    strip_lang_prefix_from_path,
)


class TestLanguageInference:
    def test_en_url(self):
        assert infer_language("https://docs.example.com/guide/") == "en"

    def test_zh_cn_url(self):
        assert infer_language("https://docs.example.com/zh-cn/guide/") == "zh"

    def test_zh_hans_url(self):
        assert infer_language("https://docs.example.com/zh-hans/guide/") == "zh"

    def test_zh_hant_url(self):
        assert infer_language("https://docs.example.com/zh-hant/guide/") == "zh"

    def test_zh_only_url(self):
        assert infer_language("https://docs.example.com/zh/") == "zh"

    def test_root_url(self):
        assert infer_language("https://docs.example.com/") == "en"

    def test_en_prefix(self):
        assert infer_language("https://docs.example.com/en/guide/") == "en"

    def test_locale_query(self):
        assert infer_language("https://example.com/docs?locale=zh_CN") == "zh"

    def test_language_subdomain(self):
        assert infer_language("https://cn.example.com/docs/") == "zh"


class TestLanguagePrefix:
    def test_zh_cn(self):
        assert language_prefix("https://docs.example.com/zh-cn/guide/") == "zh-cn"

    def test_en(self):
        assert language_prefix("https://docs.example.com/guide/") == ""


class TestNormalizeOrigin:
    def test_en_and_zh_share_origin(self):
        en = normalize_origin("https://docs.example.com/")
        zh = normalize_origin("https://docs.example.com/zh-cn/")
        assert en == zh

    def test_strips_zh_prefix_from_path(self):
        en = normalize_origin("https://docs.example.com/guide/intro")
        zh = normalize_origin("https://docs.example.com/zh-cn/guide/intro")
        assert en == zh

    def test_different_hosts_dont_pair(self):
        en = normalize_origin("https://docs.a.com/")
        zh = normalize_origin("https://docs.b.com/zh-cn/")
        assert en != zh


class TestStripLangPrefix:
    def test_nested_path(self):
        assert strip_lang_prefix_from_path("zh-cn/explore/book.md", "zh-cn") == "explore/book.md"

    def test_homepage_flat(self):
        assert strip_lang_prefix_from_path("zh-cn.md", "zh-cn") == "index.md"

    def test_no_prefix(self):
        assert strip_lang_prefix_from_path("explore/book.md", "") == "explore/book.md"

    def test_unrelated_prefix(self):
        assert (
            strip_lang_prefix_from_path("other/explore/book.md", "zh-cn") == "other/explore/book.md"
        )


class TestPairFilePaths:
    def test_all_paired(self):
        en = ["index.md", "guide/intro.md", "guide/setup.md"]
        zh = ["zh-cn/index.md", "zh-cn/guide/intro.md", "zh-cn/guide/setup.md"]
        result = pair_file_paths(en, zh, "zh-cn")
        assert all(zh_fp is not None for _, zh_fp in result)
        assert result[0] == ("index.md", "zh-cn/index.md")

    def test_homepage_special_case(self):
        en = ["index.md"]
        zh = ["zh-cn.md"]
        result = pair_file_paths(en, zh, "zh-cn")
        assert result[0] == ("index.md", "zh-cn.md")

    def test_en_only(self):
        en = ["index.md", "extra.md"]
        zh = ["zh-cn/index.md"]
        result = pair_file_paths(en, zh, "zh-cn")
        assert result[0][1] is not None  # index.md paired
        assert result[1][1] is None  # extra.md unpaired

    def test_manual_path_pair_overrides_different_leaf_names(self):
        result = pair_file_paths(
            ["en.html.md"],
            ["zh.html.md"],
            "",
            {"en.html.md": "zh.html.md"},
        )

        assert result == [("en.html.md", "zh.html.md")]


class TestGroupSourcesByOrigin:
    def test_deepTutor_pairing(self):
        sources = [
            {"id": "a", "url": "https://docs.deeptutor.info/"},
            {"id": "b", "url": "https://docs.deeptutor.info/zh-cn/"},
        ]
        pairs = group_sources_by_origin(sources)
        assert len(pairs) == 1
        assert pairs[0].is_pair
        assert pairs[0].en_source["id"] == "a"
        assert pairs[0].zh_source["id"] == "b"
        assert pairs[0].zh_lang_prefix == "zh-cn"

    def test_en_only_source(self):
        sources = [{"id": "a", "url": "https://docs.example.com/"}]
        pairs = group_sources_by_origin(sources)
        assert len(pairs) == 1
        assert not pairs[0].is_pair
        assert pairs[0].en_source is not None
        assert pairs[0].zh_source is None

    def test_different_origins_not_paired(self):
        sources = [
            {"id": "a", "url": "https://docs.a.com/"},
            {"id": "b", "url": "https://docs.b.com/zh-cn/"},
        ]
        pairs = group_sources_by_origin(sources)
        assert len(pairs) == 2
        assert not pairs[0].is_pair

    def test_explicit_language_overrides_url_inference(self):
        sources = [
            {"id": "a", "url": "https://example.com/guide/", "language": "zh"},
            {"id": "b", "url": "https://example.com/en/guide/", "language": "en"},
        ]
        pairs = group_sources_by_origin(sources)
        assert len(pairs) == 1
        assert pairs[0].is_pair

    def test_manual_pairing_key_groups_separate_domains(self):
        key = "manual-pair"
        sources = [
            {"id": "a", "url": "https://docs.example.com/", "pairing_key": key, "language": "en"},
            {"id": "b", "url": "https://example.cn/docs/", "pairing_key": key, "language": "zh"},
        ]
        pairs = group_sources_by_origin(sources)
        assert len(pairs) == 1
        assert pairs[0].is_pair

    def test_manual_pairing_url_adds_entry_file_mapping(self):
        key = "manual-pair"
        sources = [
            {
                "id": "a",
                "url": "https://docs.example.com/en.html",
                "pairing_key": key,
                "language": "en",
                "paired_url": "https://example.cn/zh.html",
            },
            {
                "id": "b",
                "url": "https://example.cn/zh.html",
                "pairing_key": key,
                "language": "zh",
                "paired_url": "https://docs.example.com/en.html",
            },
        ]

        pairs = group_sources_by_origin(sources)

        assert pairs[0].manual_path_pairs == {"en.html.md": "zh.html.md"}


class TestPairKey:
    def test_stable(self):
        assert pair_key_for("docs.deeptutor.info/") == pair_key_for("docs.deeptutor.info/")

    def test_no_slash_colisions(self):
        assert "/" not in pair_key_for("docs.example.com/path/")
        assert " " not in pair_key_for("docs example com/")


class TestPairStatus:
    def test_bilingual_status(self):
        from deeptutor.services.web_source.pairing import LanguagePair

        pair = LanguagePair(
            origin="docs.example.com/",
            en_source={"id": "a", "url": "https://docs.example.com/"},
            zh_source={"id": "b", "url": "https://docs.example.com/zh-cn/"},
            zh_lang_prefix="zh-cn",
        )
        status = compute_pair_status(pair)
        assert status.status == "bilingual"
        assert status.en_source_id == "a"
        assert status.zh_source_id == "b"
