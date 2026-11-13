"""Reader-facing copy for the engine-injected Overview chapter.

This one page is built **deterministically** — no LLM call — so its wording
cannot come from the model the way every other block's does. It used to live as
``"中文" if book.language == "zh" else "English"`` conditionals scattered through
``engine.py``, which meant the language picker could offer eleven languages
while the book's own front page only ever spoke two.

Collecting it here does not by itself translate the page, but it turns "add a
language" from an edit across two functions into one entry in this table, and
it makes the gap visible instead of implicit: anything not listed falls back to
English, and :func:`missing_languages` reports what is still owed.
"""

from __future__ import annotations

from typing import Any

# Keys every entry must define. Kept explicit so a partial translation fails
# loudly in tests rather than rendering a stray English string mid-page.
REQUIRED_KEYS = frozenset(
    {
        "chapter_title",
        "chapter_summary",
        "objectives",
        "intro_title",
        "intro_body",
        "untitled_book",
        "concept_map_title",
        "chapter_index_title",
        "chapter_index_heading",
    }
)

_COPY: dict[str, dict[str, Any]] = {
    "pt": {
        "chapter_title": "Como ler este livro",
        "chapter_summary": "Visão geral gerada automaticamente do grafo de conceitos e do índice de capítulos do livro.",
        "objectives": [
            "Ter uma visão rápida do mapa completo de capítulos",
            "Entender como os conceitos dependem uns dos outros",
            "Escolher o caminho de leitura que melhor atende aos seus objetivos",
        ],
        "intro_title": "Como ler este livro",
        "intro_body": (
            "O diagrama abaixo mapeia os {concepts} conceitos principais deste livro e como eles dependem uns dos outros. "
            "O índice a seguir lista todos os {chapters} capítulos — leia de cima para baixo para seguir a ordem recomendada, "
            "ou vá direto ao capítulo que mais despertar sua curiosidade."
        ),
        "untitled_book": "Este livro",
        "concept_map_title": "Mapa de conceitos",
        "chapter_index_title": "Índice de capítulos",
        "chapter_index_heading": "## Índice de capítulos",
    },
    "en": {
        "chapter_title": "How to read this book",
        "chapter_summary": (
            "Auto-generated overview of the book's concept graph and chapter index."
        ),
        "objectives": [
            "See the full chapter map at a glance",
            "Understand how concepts depend on each other",
            "Pick the reading path that fits your goals",
        ],
        "intro_title": "How to read this book",
        "intro_body": (
            "The diagram below maps the {concepts} core concepts in this book and "
            "how they depend on each other. The chapter index that follows lists "
            "all {chapters} chapters — read top-to-bottom for the recommended "
            "path, or jump straight to whatever you're most curious about."
        ),
        "untitled_book": "This book",
        "concept_map_title": "Concept map",
        "chapter_index_title": "Chapter index",
        "chapter_index_heading": "## Chapter index",
    },
    "zh": {
        "chapter_title": "本书导览",
        "chapter_summary": "自动生成的概念图与章节索引，作为本书的入口。",
        "objectives": [
            "了解整本书的章节脉络",
            "掌握各章之间的概念依赖关系",
            "选择最合适的阅读顺序",
        ],
        "intro_title": "如何阅读这本书",
        "intro_body": (
            "下方的概念图展示了本书 {concepts} 个核心概念以及它们之间的依赖关系；"
            "再下方是 {chapters} 个章节的入口。"
            "你可以按从上到下的顺序阅读，也可以根据自己的兴趣或先验知识选择切入点。"
        ),
        "untitled_book": "本书",
        "concept_map_title": "概念图",
        "chapter_index_title": "章节索引",
        "chapter_index_heading": "## 章节索引",
    },
    "vi": {
        "chapter_title": "Cách đọc cuốn sách này",
        "chapter_summary": "Tổng quan được tạo tự động về sơ đồ khái niệm và mục lục các chương của sách.",
        "objectives": [
            "Nắm toàn bộ bản đồ các chương chỉ trong một cái nhìn",
            "Hiểu các khái niệm phụ thuộc lẫn nhau như thế nào",
            "Chọn lộ trình đọc phù hợp với mục tiêu của bạn",
        ],
        "intro_title": "Cách đọc cuốn sách này",
        "intro_body": (
            "Sơ đồ bên dưới thể hiện {concepts} khái niệm cốt lõi của cuốn sách và "
            "mối quan hệ phụ thuộc giữa chúng. Mục lục chương ngay sau đó liệt kê "
            "cả {chapters} chương — bạn có thể đọc từ trên xuống dưới theo lộ trình "
            "được đề xuất, hoặc chuyển thẳng đến phần mình quan tâm nhất."
        ),
        "untitled_book": "Cuốn sách này",
        "concept_map_title": "Sơ đồ khái niệm",
        "chapter_index_title": "Mục lục chương",
        "chapter_index_heading": "## Mục lục chương",
    },
    "fr": {
        "chapter_title": "Comment lire ce livre",
        "chapter_summary": (
            "Vue d’ensemble générée automatiquement à partir du graphe de concepts "
            "et de l’index des chapitres."
        ),
        "objectives": [
            "Voir la carte complète des chapitres en un coup d’œil",
            "Comprendre les dépendances entre les concepts",
            "Choisir le parcours de lecture adapté à vos objectifs",
        ],
        "intro_title": "Comment lire ce livre",
        "intro_body": (
            "Le schéma ci-dessous cartographie les {concepts} concepts clés de ce livre "
            "et leurs dépendances. L’index des chapitres qui suit liste les {chapters} "
            "chapitres — lisez de haut en bas pour suivre le parcours recommandé, ou "
            "allez directement au sujet qui vous intéresse le plus."
        ),
        "untitled_book": "Ce livre",
        "concept_map_title": "Carte des concepts",
        "chapter_index_title": "Index des chapitres",
        "chapter_index_heading": "## Index des chapitres",
    },
    "tr": {
        "chapter_title": "Bu kitap nasıl okunur",
        "chapter_summary": (
            "Kitabın kavram grafiğinin ve bölüm dizininin otomatik oluşturulmuş özeti."
        ),
        "objectives": [
            "Tüm bölüm haritasını tek bakışta görün",
            "Kavramların birbirine nasıl bağlı olduğunu anlayın",
            "Hedeflerinize uygun okuma yolunu seçin",
        ],
        "intro_title": "Bu kitap nasıl okunur",
        "intro_body": (
            "Aşağıdaki diyagram, bu kitaptaki {concepts} temel kavramı ve bunların "
            "birbirine nasıl bağlı olduğunu gösterir. Ardından gelen bölüm dizini "
            "{chapters} bölümün tamamını listeler; önerilen yol için yukarıdan aşağıya "
            "okuyabilir ya da en çok merak ettiğiniz bölüme doğrudan geçebilirsiniz."
        ),
        "untitled_book": "Bu kitap",
        "concept_map_title": "Kavram haritası",
        "chapter_index_title": "Bölüm dizini",
        "chapter_index_heading": "## Bölüm dizini",
    },
}


def overview_copy(language: str | None) -> dict[str, Any]:
    """Copy for *language*, falling back to English (then to the base tag).

    ``zh-tw`` finds no exact entry, tries ``zh``, and only then falls back —
    matching how the prompt layer resolves language tags.
    """
    code = (language or "en").strip().lower()
    return _COPY.get(code) or _COPY.get(code.split("-", 1)[0]) or _COPY["en"]


def missing_languages(supported: list[str]) -> list[str]:
    """Which of *supported* still render the Overview page in English.

    Not a failure — the page stays readable — but a book generated in a
    language listed here has an English front page in front of prose that is
    not English. Used by tests to keep the gap honest and countable.
    """
    return [
        code
        for code in supported
        if code.strip().lower() not in _COPY and code.strip().lower().split("-", 1)[0] not in _COPY
    ]


__all__ = ["REQUIRED_KEYS", "missing_languages", "overview_copy"]
