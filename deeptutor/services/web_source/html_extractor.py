"""HTML-to-markdown extraction for documentation sites.

Strips navigation chrome, sidebars, and boilerplate, then converts the
main article content to clean markdown preserving structure.
"""

from __future__ import annotations

from dataclasses import dataclass
import html as _html
import logging
import re

logger = logging.getLogger(__name__)

# Tags to completely remove before extraction
_STRIP_TAGS = (
    "script",
    "style",
    "noscript",
    "nav",
    "header",
    "footer",
    "aside",
    "iframe",
    "svg",
    "form",
    "button",
    "input",
    "select",
)

# CSS-ish selectors (via XPath) to find the main content in priority order.
# Docusaurus, MkDocs, GitBook, ReadTheDocs, generic.
_CONTENT_XPATHS = [
    "//article",
    "//div[contains(@class, 'sl-markdown')]",
    "//div[contains(@class, 'theme-doc-markdown')]",
    "//div[contains(@class, 'markdown-body')]",
    "//div[contains(@class, 'md-content')]",
    "//div[@role='main']",
    "//main",
    "//div[contains(@class, 'content')]",
]


# ── Navigation extraction ────────────────────────────────────────────

# XPath selectors for sidebar / navigation containers, in priority order.
# Checked before _STRIP_TAGS removes them.
_SIDEBAR_XPATHS = [
    # Docusaurus / Starlight
    "//nav[contains(@class, 'theme-doc-sidebar-menu')]",
    "//div[contains(@class, 'theme-doc-sidebar-container')]//nav",
    "//nav[contains(@class, 'sidebar')]//nav",
    # MkDocs
    "//div[contains(@class, 'md-sidebar--primary')]//nav",
    "//nav[contains(@class, 'md-nav--primary')]",
    # GitBook
    "//div[contains(@class, 'book-summary')]",
    "//nav[contains(@class, 'navigation-sidebar')]",
    # ReadTheDocs / Sphinx
    "//div[contains(@class, 'wy-nav-side')]//ul",
    "//div[contains(@class, 'sphinxsidebar')]",
    # VuePress / VitePress
    "//div[contains(@class, 'sidebar')]//nav",
    # Generic fallbacks (nav before aside — aside often matches right-side TOC)
    "//nav[contains(@class, 'sidebar')]",
    "//aside[contains(@class, 'sidebar')]",
    "//div[contains(@class, 'toc-tree')]",
]


# Tags whose subtrees _walk should NOT descend into.  Any element not in
# this set gets recursed into, catching custom-element components from
# Astro/Starlight, web-components, etc. that a static tag-allowlist would miss.
_WALK_SKIP_TAGS = frozenset(
    {
        "script",
        "style",
        "svg",
        "input",
        "button",
        "form",
        "meta",
        "link",
        "br",
        "hr",
        "img",
    }
)


def extract_navigation(raw_html: str, base_url: str) -> list[dict]:
    """Extract navigation links from a doc-site page sidebar.

    Returns a flat ordered list of ``{title, url, path, depth}`` dicts,
    preserving the sidebar's visual order and nesting depth.  Falls back
    to an empty list when no sidebar container is found.

    Must be called on the **raw** HTML (before :func:`extract_article_markdown`
    strips ``nav``/``aside`` elements).
    """
    from urllib.parse import urljoin, urlparse

    from lxml import html as lxml_html

    try:
        tree = lxml_html.fromstring(raw_html)
    except Exception:
        return []

    # Try each selector until we extract enough links from one.
    # A selector might match the wrong container (e.g. right-side TOC)
    # and yield no usable links — keep trying the next one.
    links: list[dict] = []
    seen: set[str] = set()

    def _walk(el, depth: int):
        """Recursively walk sidebar DOM, emitting links with depth info."""
        for child in el:
            tag = (child.tag or "").lower()

            # Anchor: emit a navigation entry.
            if tag == "summary":
                # Starlight renders non-link section groups as <summary>. Keep
                # them as URL-less parents so the original sidebar hierarchy is
                # not flattened into a list of pages.
                title = child.text_content().strip()
                if title:
                    links.append(
                        {
                            "title": title,
                            "url": "",
                            "path": "",
                            "depth": depth,
                            "is_group": True,
                        }
                    )
                continue

            if tag == "a":
                href = (child.get("href") or "").strip()
                title = child.text_content().strip()
                if not href or not title or href.startswith("#"):
                    _walk(child, depth)
                    continue
                lower = href.lower()
                if lower.startswith(("javascript:", "mailto:", "tel:", "data:")):
                    continue
                absolute = urljoin(base_url, href.split("#")[0])
                parsed = urlparse(absolute)
                if parsed.scheme.lower() not in ("http", "https"):
                    continue
                base_host = urlparse(base_url).hostname
                if not base_host or parsed.hostname != base_host:
                    continue
                identity = f"link:{absolute}"
                if identity in seen:
                    continue
                seen.add(identity)
                links.append(
                    {
                        "title": title,
                        "url": absolute,
                        "path": parsed.path,
                        "depth": depth,
                    }
                )

            elif tag in ("ul", "ol"):
                _walk(child, depth + 1)
            elif tag not in _WALK_SKIP_TAGS:
                # Descend into any container we don't explicitly skip.
                # This catches custom-element components (Astro/Starlight,
                # web-components) that would be missed by a static tag list.
                _walk(child, depth)

    for xp in _SIDEBAR_XPATHS:
        found = tree.xpath(xp)
        if not found:
            continue
        # Walk the first matched element.
        links.clear()
        seen.clear()
        _walk(found[0], -1)
        if len(links) >= 2:
            break  # got a real sidebar

    if len(links) < 2:
        return []

    # Normalize depths so the shallowest link is at depth 0.
    min_depth = min(lnk["depth"] for lnk in links)
    if min_depth > 0:
        for lnk in links:
            lnk["depth"] -= min_depth

    return links


def extract_headings(markdown: str) -> list[dict]:
    """Extract ATX-style headings from markdown text.

    Returns a list of ``{level, text, slug}`` dicts.  Code-fence aware:
    ``#`` characters inside fenced blocks are ignored.

    Used for the current-page table of contents.
    """
    headings: list[dict] = []
    in_fence = False

    for line in markdown.split("\n"):
        stripped = line.lstrip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = re.match(r"^(#{1,6})\s+(.+)$", line)
        if m:
            level = len(m.group(1))
            text = m.group(2).strip()
            # Remove trailing markdown (links, formatting)
            clean = re.sub(r"\[([^]]*)\]\([^)]*\)", r"\1", text)
            clean = re.sub(r"[*`_~]", "", clean).strip()
            slug = re.sub(r"[^a-z0-9\s-]", "", clean.lower())
            slug = re.sub(r"\s+", "-", slug).strip("-")
            headings.append({"level": level, "text": clean, "slug": slug})

    return headings


@dataclass(frozen=True)
class ExtractionQuality:
    """Small, auditable quality signal for a crawled learning page."""

    score: int
    warnings: tuple[str, ...] = ()


def assess_extraction_quality(markdown: str, *, title: str = "") -> ExtractionQuality:
    """Score extraction output without using it to replace content silently."""
    body = (markdown or "").strip()
    plain = re.sub(r"\x60\x60\x60.*?\x60\x60\x60", " ", body, flags=re.S)
    plain = re.sub(r"[#*`>|\-]+", " ", plain)
    plain = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", plain)
    plain = re.sub(r"\s+", " ", plain).strip()

    warnings: list[str] = []
    score = 100
    if not plain:
        warnings.append("empty body")
        if not title.strip():
            warnings.append("missing title")
        if not re.search(r"(?m)^#{1,6}\s+\S", body):
            warnings.append("no headings")
        return ExtractionQuality(score=0, warnings=tuple(dict.fromkeys(warnings)))
    elif len(plain) < 160:
        score -= 35
        warnings.append("very short body")
    if not (title or "").strip():
        score -= 10
        warnings.append("missing title")
    if not re.search(r"(?m)^#{1,6}\s+\S", body):
        score -= 15
        warnings.append("no headings")

    chrome_markers = (
        "skip to main content",
        "table of contents",
        "previous article",
        "next article",
        "back to top",
    )
    lower = plain.lower()
    found_chrome = [marker for marker in chrome_markers if marker in lower]
    if found_chrome:
        score -= min(25, 10 * len(found_chrome))
        warnings.append("navigation residue: " + ", ".join(found_chrome))
    if "…[truncated]" in body:
        score -= 10
        warnings.append("body truncated")

    if len(plain) >= 500:
        score += 5
    if re.search(r"(?m)^\x60\x60\x60", body):
        score += 5
    if re.search(r"(?m)^\|.*\|", body):
        score += 3
    if re.search(r"(?m)^(?:[-*+]\s|\d+\.\s)\S", body):
        score += 3

    return ExtractionQuality(
        score=max(0, min(100, score)),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def extract_article_markdown(raw_html: str) -> tuple[str, str]:
    """Extract ``(title, markdown)`` from a doc-site HTML page.

    Falls back to full-body text if no article container is found, but
    always strips navigation, scripts, and other boilerplate first.
    """
    from lxml import html as lxml_html

    title = ""
    try:
        tree = lxml_html.fromstring(raw_html)
    except Exception:
        # Malformed HTML — fall back to regex title extraction
        m = re.search(r"<title[^>]*>(.*?)</title>", raw_html, re.I | re.S)
        if m:
            title = re.sub(r"\s+", " ", m.group(1)).strip()
        # Crude strip of tags
        text = re.sub(r"<[^>]+>", " ", raw_html)
        text = _html.unescape(text)
        text = re.sub(r"\s+", " ", text).strip()
        return title, text

    # Title from <title> tag or first <h1>
    title_els = tree.xpath("//title/text()")
    if title_els:
        title = re.sub(r"\s+", " ", title_els[0]).strip()
        # Strip site suffix like " | DeepTutor"
        title = re.sub(r"\s*[|｜]\s*[^|]+$", "", title).strip()

    # Remove boilerplate elements
    for tag in _STRIP_TAGS:
        for el in tree.xpath(f"//{tag}"):
            parent = el.getparent()
            if parent is not None:
                parent.remove(el)

    # Remove aria-hidden elements (decorative, screen-reader text)
    for el in tree.xpath("//*[@aria-hidden='true']"):
        parent = el.getparent()
        if parent is not None:
            parent.remove(el)

    # Also remove elements with common nav/chrome classes
    for cls_kw in [
        "navbar",
        "sidebar",
        "toc",
        "breadcrumb",
        "pagination",
        "menu",
        "search",
        "theme-toggle",
        "skip-to-content",
        "back-to-top",
        "edit-this-page",
        "last-updated",
        "sr-only",
        "sl-anchor-link",
        "sl-toc",
        "social-icons",
        "header",
        "mobile-header",
        "right-sidebar",
        "left-sidebar",
    ]:
        for el in tree.xpath(f"//*[contains(@class, '{cls_kw}')]"):
            parent = el.getparent()
            if parent is not None:
                parent.remove(el)

    # Find the main content container
    content_el = None
    for xp in _CONTENT_XPATHS:
        found = tree.xpath(xp)
        if found:
            content_el = found[0]
            break

    if content_el is None:
        body = tree.xpath("//body")
        content_el = body[0] if body else tree

    # Convert to markdown
    md = _element_to_markdown(content_el)
    md = _clean_markdown(md)

    if not title:
        h1 = content_el.xpath(".//h1/text()")
        if h1:
            title = h1[0].strip()

    if title and not md.lstrip().startswith("#"):
        md = f"# {title}\n\n{md}"

    return title, md


def _pre_to_text(el) -> str:
    """Extract text from a <pre> element, preserving code line structure.

    Modern doc-site code blocks (Expressive Code, Shiki, Prism) wrap each
    line in a ``<div class="ec-line">``, ``<span class="line">``, or similar
    container with *no* inter-line whitespace.  ``text_content()`` would
    mash everything onto one line.  This helper detects those wrappers and
    inserts real newlines.
    """
    # Expressive Code / Starlight: <div class="ec-line"><div class="code">...
    line_els = el.xpath(
        ".//div[contains(@class, 'ec-line')]"
        " | .//div[contains(@class, 'code-line')]"
        " | .//span[contains(@class, 'line')]"
        " | .//div[contains(@class, 'code-line')]"
    )
    if line_els:
        return "\n".join(le.text_content() for le in line_els)

    # Fallback: walk all children, converting <br> to newlines.
    parts: list[str] = []
    if el.text:
        parts.append(el.text)
    for node in el.iter():
        if node.tag == "br":
            parts.append("\n")
        elif node.text:
            parts.append(node.text)
        if node.tail:
            parts.append(node.tail)
    return "".join(parts)


def _element_to_markdown(el) -> str:
    """Recursively convert an lxml element to markdown text.

    Correctly preserves inter-element whitespace by including both
    ``el.text`` (text before the first child) and each ``child.tail``
    (text after a child element).  This fixes the missing-space bug where
    inline markup like ``word<strong>bold</strong>word`` collapsed into
    ``word**bold**word``.
    """
    parts: list[str] = []

    # Text before the first child element (el.text).
    if el.text:
        parts.append(el.text)

    for child in el:
        tag = (child.tag or "").lower()
        if tag in _STRIP_TAGS:
            # Still need to preserve the tail of a stripped element.
            if child.tail:
                parts.append(child.tail)
            continue

        text = _element_to_markdown(child)

        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            level = int(tag[1])
            heading_text = child.text_content().strip()
            heading_text = re.sub(r"\s*Section titled.*$", "", heading_text).strip()
            parts.append(f"\n\n{'#' * level} {heading_text}\n\n")
        elif tag == "p":
            parts.append(f"\n\n{text}\n\n")
        elif tag == "pre":
            code = _pre_to_text(child)
            # Detect language from data-language attr, class, or child classes
            lang = child.get("data-language", "") or ""
            if not lang:
                classes = child.get("class", "") or " ".join(
                    c.get("class", "") for c in child.iterchildren()
                )
                for m in re.finditer(r"(?:language-|lang-)(\w+)", classes):
                    lang = m.group(1)
                    break
            parts.append(f"\n\n```{lang}\n{code.strip()}\n```\n\n")
        elif tag == "code":
            # Inline code (not inside pre).
            code_text = child.text_content().strip()
            if code_text:
                parts.append(f"`{code_text}`")
            else:
                parts.append(text)
        elif tag in ("ul", "ol"):
            items = _list_to_markdown(child, ordered=(tag == "ol"))
            parts.append(f"\n\n{items}\n\n")
        elif tag == "blockquote":
            quoted = "\n".join(f"> {line}" for line in text.strip().split("\n"))
            parts.append(f"\n\n{quoted}\n\n")
        elif tag == "hr":
            parts.append("\n\n---\n\n")
        elif tag == "br":
            parts.append("\n")
        elif tag == "table":
            table_md = _table_to_markdown(child)
            if table_md:
                parts.append(f"\n\n{table_md}\n\n")
        elif tag == "a":
            href = child.get("href", "")
            link_text = child.text_content().strip()
            if href and link_text and not href.startswith("#"):
                parts.append(f"[{link_text}]({href})")
            elif link_text:
                parts.append(link_text)
        elif tag in ("strong", "b"):
            t = child.text_content().strip()
            if t:
                parts.append(f"**{t}**")
        elif tag in ("em", "i"):
            t = child.text_content().strip()
            if t:
                parts.append(f"*{t}*")
        elif tag == "img":
            alt = child.get("alt", "")
            src = child.get("src", "")
            if src:
                parts.append(f"![{alt}]({src})")
        elif tag in ("div", "section", "span", "article", "main"):
            parts.append(text)
        else:
            inner_text = (child.text or "").strip()
            if inner_text:
                parts.append(inner_text)
            parts.append(text)

        # Crucial: preserve the tail text (whitespace + text after this child).
        if child.tail:
            parts.append(child.tail)

    return "".join(parts)


def _list_to_markdown(el, ordered: bool = False) -> str:
    """Convert a <ul> or <ol> element to markdown."""
    lines: list[str] = []
    idx = 0
    for child in el:
        if (child.tag or "").lower() == "li":
            idx += 1
            prefix = f"{idx}. " if ordered else "- "
            text = _element_to_markdown(child).strip()
            # Handle nested lists
            text = text.replace("\n", "\n  ")
            lines.append(f"{prefix}{text}")
    return "\n".join(lines)


def _table_to_markdown(el) -> str:
    """Best-effort conversion of a <table> to markdown table."""
    rows = []
    for tr in el.xpath(".//tr"):
        cells = []
        for cell in tr.xpath(".//td | .//th"):
            cells.append(cell.text_content().strip().replace("|", "\\|"))
        if cells:
            rows.append("| " + " | ".join(cells) + " |")
    if not rows:
        return ""
    # Add header separator after first row
    header_cols = rows[0].count("|") - 1
    separator = "| " + " | ".join(["---"] * header_cols) + " |"
    rows.insert(1, separator)
    return "\n".join(rows)


def _clean_markdown(md: str) -> str:
    """Normalize whitespace, collapse excessive blank lines."""
    # Decode HTML entities that survived
    md = _html.unescape(md)
    # Collapse 3+ blank lines to 2
    md = re.sub(r"\n{3,}", "\n\n", md)
    # Remove leading/trailing whitespace on lines
    lines = [line.rstrip() for line in md.split("\n")]
    md = "\n".join(lines)
    return md.strip()
