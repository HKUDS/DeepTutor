"""HTML-to-markdown extraction for documentation sites.

Strips navigation chrome, sidebars, and boilerplate, then converts the
main article content to clean markdown preserving structure.
"""

from __future__ import annotations

import html as _html
import logging
import re
from urllib.parse import urljoin, urlparse

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

# CSS-ish selectors (via XPath) that nominate possible article roots.  They are
# scored rather than treated as a first-match list: pages commonly contain an
# ``article`` teaser before their real ``main``, while article bodies are often
# nested inside a broader semantic container.
_CONTENT_XPATHS = [
    "//*[@itemprop='articleBody']",
    "//article",
    "//div[contains(@class, 'sl-markdown')]",
    "//div[contains(@class, 'theme-doc-markdown')]",
    "//div[contains(@class, 'markdown-body')]",
    "//div[contains(@class, 'md-content')]",
    "//*[@role='main']",
    "//main",
    "//*[@id='main-content']",
    "//div[contains(@class, 'content')]",
]

# Exact class/id components that normally identify navigation or page chrome.
# Splitting names on punctuation is deliberate: a raw substring check for
# ``header``/``toc`` also matches unrelated implementation names and can detach
# the article itself before content selection has a chance to see it.
_CHROME_NAME_PARTS = frozenset(
    {
        "backtotop",
        "breadcrumb",
        "breadcrumbs",
        "editsection",
        "editthispage",
        "footer",
        "lastupdated",
        "leftsidebar",
        "menu",
        "mobileheader",
        "navbar",
        "navbox",
        "navigation",
        "pagination",
        "printfooter",
        "rightsidebar",
        "search",
        "share",
        "sharing",
        "sidebar",
        "siteheader",
        "skiptocontent",
        "skiplink",
        "social",
        "socialicons",
        "sronly",
        "tableofcontents",
        "themetoggle",
        "toc",
        "toolbar",
    }
)
_CHROME_ROLES = frozenset({"banner", "complementary", "contentinfo", "navigation", "search"})


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

    from lxml import html as lxml_html  # nosec B410 - HTML parser, not XML

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
            tag = _tag_name(child)
            if not tag:
                continue

            # Anchor: emit a navigation entry.
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
                if absolute in seen:
                    continue
                seen.add(absolute)
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


def _tag_name(el) -> str:
    """Return a lower-case HTML tag, or ``""`` for comments/PI nodes.

    lxml represents comments with a callable sentinel in ``node.tag``.  Treating
    it as a string raises during conversion; callers then fell back to a regex
    text dump that flattened every heading and retained the whole page chrome.
    """
    tag = getattr(el, "tag", "")
    return tag.lower() if isinstance(tag, str) else ""


def _content_score(el) -> tuple[int, int, int]:
    """Rank a possible article root by prose, structure, then total text."""
    paragraphs = el.xpath(".//p")
    prose_chars = sum(len(re.sub(r"\s+", " ", row.text_content()).strip()) for row in paragraphs)
    heading_count = len(el.xpath(".//h1 | .//h2 | .//h3 | .//h4 | .//h5 | .//h6"))
    text_chars = len(re.sub(r"\s+", " ", el.text_content()).strip())
    # Paragraph prose is a stronger article signal than a link-heavy menu.  A
    # heading bonus keeps documentation pages useful even when their content is
    # mostly lists and code rather than conventional paragraphs.
    return (prose_chars * 4 + heading_count * 400 + text_chars, prose_chars, heading_count)


def _select_content_element(tree):
    """Choose the strongest semantic/content candidate from the document."""
    candidates = []
    seen: set[int] = set()
    for xpath in _CONTENT_XPATHS:
        for el in tree.xpath(xpath):
            identity = id(el)
            if identity in seen:
                continue
            seen.add(identity)
            candidates.append(el)
    if candidates:
        return max(candidates, key=_content_score)
    body = tree.xpath("//body")
    return body[0] if body else tree


def _looks_like_chrome(el) -> bool:
    """Whether an element is labelled as navigation or surrounding chrome."""
    role = str(el.get("role") or "").strip().lower()
    if role in _CHROME_ROLES:
        return True
    names = f"{el.get('class') or ''} {el.get('id') or ''}".lower()
    parts = set(re.findall(r"[a-z0-9]+", names))
    # Keep both components (``sidebar`` in ``docs-sidebar``) and collapsed CSS
    # names (``backtotop`` in ``back-to-top``).  Exact matching at both levels
    # avoids the destructive false positives caused by raw substring checks.
    parts.update(re.sub(r"[^a-z0-9]", "", name) for name in names.split())
    return bool(parts & _CHROME_NAME_PARTS)


def _remove_element(el) -> None:
    """Detach an lxml element when it still has a parent."""
    parent = el.getparent()
    if parent is not None:
        parent.remove(el)


def extract_article_markdown(raw_html: str, base_url: str = "") -> tuple[str, str]:
    """Extract ``(title, markdown)`` from a doc-site HTML page.

    Falls back to full-body text if no article container is found, but
    always strips navigation, scripts, and other boilerplate first.
    """
    from lxml import html as lxml_html  # nosec B410 - HTML parser, not XML

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

    # Select before pruning.  Cleanup selectors are necessarily heuristic, and
    # mutating the whole document first can detach the only useful root because
    # a framework happened to use a chrome-like word in an ancestor class.
    content_el = _select_content_element(tree)

    # Remove boilerplate elements within the selected article only.  Site-wide
    # navigation is normally outside this root; these rules handle embedded
    # tables of contents, sharing toolbars, and footer/navigation widgets.
    for tag in _STRIP_TAGS:
        for el in content_el.xpath(f".//{tag}"):
            _remove_element(el)

    # Remove aria-hidden elements (decorative, screen-reader text)
    for el in content_el.xpath(".//*[@aria-hidden='true']"):
        _remove_element(el)

    for el in content_el.xpath(".//*"):
        if _looks_like_chrome(el):
            _remove_element(el)

    # Convert to markdown
    md = _element_to_markdown(content_el, base_url=base_url)
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
        tag = _tag_name(node)
        if not tag:
            continue
        if tag == "br":
            parts.append("\n")
        elif node.text:
            parts.append(node.text)
        if node.tail:
            parts.append(node.tail)
    return "".join(parts)


def _element_to_markdown(el, base_url: str = "") -> str:
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
        tag = _tag_name(child)
        if not tag:
            # Comments and processing instructions are metadata, not readable
            # prose. Their tail can contain real text and must still survive.
            if child.tail:
                parts.append(child.tail)
            continue
        if tag in _STRIP_TAGS:
            # Still need to preserve the tail of a stripped element.
            if child.tail:
                parts.append(child.tail)
            continue

        text = _element_to_markdown(child, base_url=base_url)

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
            items = _list_to_markdown(child, ordered=(tag == "ol"), base_url=base_url)
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
                href = _normalise_captured_url(href, base_url)
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
                src = _normalise_captured_url(src, base_url)
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


def _normalise_captured_url(value: str, base_url: str) -> str:
    candidate = str(value or "").strip()
    if not candidate or candidate.startswith("#") or not base_url:
        return candidate
    parsed = urlparse(candidate)
    if parsed.scheme and parsed.scheme.lower() not in {"http", "https"}:
        return candidate
    return urljoin(base_url, candidate)


def _list_to_markdown(el, ordered: bool = False, base_url: str = "") -> str:
    """Convert a <ul> or <ol> element to markdown."""
    lines: list[str] = []
    idx = 0
    for child in el:
        if _tag_name(child) == "li":
            idx += 1
            prefix = f"{idx}. " if ordered else "- "
            text = _element_to_markdown(child, base_url=base_url).strip()
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
    # Remove line-end indentation before collapsing blank lines. Pretty-printed
    # HTML leaves spaces on otherwise empty lines, which would hide them from a
    # newline-only regex and produce a very sparse reading view.
    lines = [line.rstrip() for line in md.split("\n")]
    md = "\n".join(lines)
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip()
