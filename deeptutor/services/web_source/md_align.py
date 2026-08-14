"""Markdown-level bilingual alignment for documentation pages.

Splits EN and ZH Markdown into semantic blocks (code-fence aware), locks
sections by heading, and runs hierarchical DP alignment within each section
to produce renderable content groups.

The algorithm is adapted from ``immersive_reading/bilingual/align.py`` but
operates on raw Markdown instead of XHTML, and preserves Markdown formatting
so the result can be rendered natively by the KB preview component.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Sequence

# -- Block types -------------------------------------------------------

HEADING = "heading"
PARAGRAPH = "paragraph"
LIST = "list"
TABLE = "table"
CODE = "code"
BLOCKQUOTE = "blockquote"
IMAGE = "image"
HR = "hr"
OTHER = "other"

# Block types that are language-neutral and shown only once (in the EN panel).
SHOW_ONCE_TYPES = {CODE, IMAGE, HR}

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")
FENCE_RE = re.compile(r"^(\s*)(```|~~~)")
LIST_RE = re.compile(r"^(\s*)([-*+]|\d+\.)\s+")
TABLE_RE = re.compile(r"^\|.*\|\s*$")
IMAGE_RE = re.compile(r"!\[.*?\]\(.*?\)")
HR_RE = re.compile(r"^(-{3,}|\*{3,}|_{3,})\s*$")
BLOCKQUOTE_RE = re.compile(r"^(\s*)>\s?")
SOURCE_COMMENT_RE = re.compile(r"^<!--\s*source:.*?-->\s*$")

REVIEW_COST_THRESHOLD = 1.5
REVIEW_RATIO_MAX = 4.0
REVIEW_RATIO_MIN = 0.20


@dataclass
class MdBlock:
    """A semantic block extracted from Markdown text."""

    block_type: str
    content: str  # raw Markdown lines (joined)
    text: str = ""  # plain text for feature extraction
    level: int = 0  # heading level (1-6) or 0
    feats: dict = field(default_factory=dict)


@dataclass
class AlignGroup:
    """A renderable content group pairing EN and ZH blocks."""

    group_id: str
    en_content: str
    zh_content: str
    shape: str = "1:1"
    confidence: float = 1.0
    show_once: list[str] = field(default_factory=list)
    low_confidence: bool = False

    def to_dict(self) -> dict:
        return {
            "group_id": self.group_id,
            "en_content": self.en_content,
            "zh_content": self.zh_content,
            "shape": self.shape,
            "confidence": round(self.confidence, 3),
            "show_once": self.show_once,
            "low_confidence": self.low_confidence,
        }


# -- Block splitting (code-fence aware) --------------------------------

def split_blocks(md_text: str) -> list[MdBlock]:
    """Split Markdown text into semantic blocks.

    Handles code fences, headings, lists, tables, blockquotes, images, and
    horizontal rules.  Consecutive lines of the same type are grouped.
    """
    lines = md_text.split("\n")
    blocks: list[MdBlock] = []
    current: list[str] = []
    current_type: str | None = None
    in_fence = False
    fence_marker = ""

    def flush() -> None:
        nonlocal current, current_type
        if not current or current_type is None:
            current = []
            current_type = None
            return
        content = "\n".join(current).strip()
        if not content:
            current = []
            current_type = None
            return
        text = _extract_plain_text(content, current_type)
        level = 0
        if current_type == HEADING:
            m = HEADING_RE.match(content)
            if m:
                level = len(m.group(1))
        feats = _feature_set(text) if current_type not in SHOW_ONCE_TYPES else {}
        blocks.append(MdBlock(
            block_type=current_type,
            content=content,
            text=text,
            level=level,
            feats=feats,
        ))
        current = []
        current_type = None

    for line in lines:
        stripped = line.rstrip()

        # Skip source comments.
        if SOURCE_COMMENT_RE.match(stripped) and not current and not in_fence:
            continue

        # Track code fences.
        fence_match = FENCE_RE.match(stripped)
        if fence_match:
            if not in_fence:
                # Starting a code fence — flush any pending non-code block.
                if current_type and current_type not in {CODE}:
                    flush()
                in_fence = True
                fence_marker = fence_match.group(2)
                current_type = CODE
                current.append(line)
                continue
            elif stripped.lstrip().startswith(fence_marker):
                # Closing fence.
                current.append(line)
                in_fence = False
                fence_marker = ""
                flush()
                continue
            else:
                # Different fence inside fence — just content.
                current.append(line)
                continue

        if in_fence:
            current.append(line)
            continue

        btype = _classify_line(stripped)

        # Blank line: potential block separator.
        if not stripped:
            if current_type and current_type not in {PARAGRAPH}:
                flush()
            elif current_type == PARAGRAPH:
                # Blank line ends a paragraph.
                flush()
            continue

        # Same type: extend current block.
        if btype == current_type:
            # For headings, each heading is its own block.
            if current_type == HEADING:
                flush()
                current_type = btype
                current = [line]
                continue
            current.append(line)
            continue

        # Different type: flush and start new.
        flush()
        current_type = btype
        current = [line]

    flush()
    return blocks


def _classify_line(line: str) -> str:
    """Classify a non-fenced Markdown line."""
    if HEADING_RE.match(line):
        return HEADING
    if TABLE_RE.match(line):
        return TABLE
    if LIST_RE.match(line):
        return LIST
    if HR_RE.match(line):
        return HR
    if IMAGE_RE.match(line) and not line.startswith("|"):
        return IMAGE
    if BLOCKQUOTE_RE.match(line):
        return BLOCKQUOTE
    return PARAGRAPH


def _extract_plain_text(content: str, block_type: str) -> str:
    """Extract plain text from a Markdown block for feature extraction."""
    if block_type == CODE:
        return ""
    # Remove Markdown syntax to get plain text.
    text = content
    text = re.sub(r"```[\s\S]*?```", "", text)  # inline code fences
    text = re.sub(r"`[^`]+`", "", text)  # inline code
    text = re.sub(r"!\[.*?\]\(.*?\)", "", text)  # images
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)  # links -> text
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)  # headings
    text = re.sub(r"[*_~`>#|-]", " ", text)  # formatting chars
    text = re.sub(r"\s+", " ", text).strip()
    return text


# -- Feature extraction ------------------------------------------------

def _feature_set(text: str) -> dict:
    latin = set(w.lower() for w in re.findall(r"\b[A-Za-z][A-Za-z\-']{2,}\b", text))
    stop = {
        "the", "and", "for", "that", "with", "this", "from", "were", "was",
        "are", "have", "has", "had", "not", "but", "they", "their", "them",
        "what", "when", "where", "than", "then", "into", "onto", "about",
        "over", "under", "after", "before", "also", "only", "more", "most",
        "such", "some", "any", "all", "can", "could", "would", "should",
        "may", "might", "will", "shall", "one", "two", "three",
    }
    return {
        "years": set(re.findall(r"\b(?:1[0-9]{3}|20[0-2][0-9])\b", text)),
        "nums": set(re.findall(r"\b\d+(?:\.\d+)?\b", text)),
        "latin": {w for w in latin if w not in stop and len(w) >= 4},
        "code": set(re.findall(r"`([^`]+)`", text)),
        "len": max(1, len(text)),
    }


def _combine_features(items: Sequence[dict]) -> dict:
    out: dict = {"years": set(), "nums": set(), "latin": set(), "code": set(), "len": 0}
    for f in items:
        out["years"] |= f.get("years", set())
        out["nums"] |= f.get("nums", set())
        out["latin"] |= f.get("latin", set())
        out["code"] |= f.get("code", set())
        out["len"] += f.get("len", 0)
    out["len"] = max(1, out["len"])
    return out


def _pair_cost(en_feat: dict, zh_feat: dict, target_en_len: float) -> float:
    length_error = abs(en_feat["len"] - target_en_len) / (target_en_len + 35.0)
    year_shared = len(en_feat.get("years", set()) & zh_feat.get("years", set()))
    num_shared = len(en_feat.get("nums", set()) & zh_feat.get("nums", set()))
    latin_shared = len(en_feat.get("latin", set()) & zh_feat.get("latin", set()))
    code_shared = len(en_feat.get("code", set()) & zh_feat.get("code", set()))
    year_miss = len(en_feat.get("years", set()) ^ zh_feat.get("years", set()))
    return (
        length_error * length_error
        - 1.30 * year_shared
        - 0.35 * num_shared
        - 0.55 * latin_shared
        - 0.80 * code_shared
        + 0.30 * year_miss
    )


# -- Section-locked alignment ------------------------------------------

@dataclass
class _Section:
    """A group of blocks under the same heading."""
    heading: MdBlock | None
    blocks: list[MdBlock] = field(default_factory=list)


def _group_into_sections(blocks: list[MdBlock]) -> list[_Section]:
    """Group blocks into sections delimited by headings.

    A heading block starts a new section and is the section's title.
    Non-heading blocks before the first heading form a preamble section.
    """
    sections: list[_Section] = []
    current = _Section(heading=None)
    for blk in blocks:
        if blk.block_type == HEADING:
            if current.blocks or current.heading:
                sections.append(current)
            current = _Section(heading=blk)
        else:
            current.blocks.append(blk)
    if current.blocks or current.heading:
        sections.append(current)
    return sections


def _align_interval(
    en: Sequence[MdBlock], zh: Sequence[MdBlock],
    en_offset: int, zh_offset: int,
) -> list[tuple[int, int, int, int, float]]:
    """DP alignment of two block sequences, returning index groups.

    Returns ``[(en_start, en_end, zh_start, zh_end, cost), ...]``.
    Supports 1:1, 1:2, 2:1, 2:2, 1:3, 3:1 groupings.
    """
    if not en or not zh:
        return []
    m, n = len(en), len(zh)
    total_en = sum(b.feats.get("len", 1) for b in en)
    total_zh = sum(b.feats.get("len", 1) for b in zh)
    inf = float("inf")
    dp = [[inf] * (n + 1) for _ in range(m + 1)]
    back: list[list[tuple[int, int] | None]] = [[None] * (n + 1) for _ in range(m + 1)]
    dp[0][0] = 0.0
    transitions = ((1, 1), (1, 2), (2, 1), (2, 2), (1, 3), (3, 1))

    for i in range(m + 1):
        for j in range(n + 1):
            if dp[i][j] == inf:
                continue
            for take_en, take_zh in transitions:
                ni, nj = i + take_en, j + take_zh
                if ni > m or nj > n:
                    continue
                en_feat = _combine_features([b.feats for b in en[i:ni]])
                zh_feat = _combine_features([b.feats for b in zh[j:nj]])
                target = total_en * (zh_feat["len"] / max(1, total_zh))
                complexity = 0.10 * (take_en + take_zh - 2)
                cost = dp[i][j] + _pair_cost(en_feat, zh_feat, target) + complexity
                if cost < dp[ni][nj]:
                    dp[ni][nj] = cost
                    back[ni][nj] = (take_en, take_zh)

    if dp[m][n] == inf:
        # Fallback: positional 1:1 up to min length.
        result = []
        for k in range(min(m, n)):
            result.append((en_offset + k, en_offset + k + 1, zh_offset + k, zh_offset + k + 1, 9.0))
        return result

    groups: list[tuple[int, int, int, int, float]] = []
    i, j = m, n
    while i or j:
        step = back[i][j]
        if step is None:
            break
        take_en, take_zh = step
        si, sj = i - take_en, j - take_zh
        groups.append((
            en_offset + si, en_offset + i,
            zh_offset + sj, zh_offset + j,
            dp[i][j] - dp[si][sj],
        ))
        i, j = si, sj
    return list(reversed(groups))


def _stable_group_id(en_content: str, zh_content: str, index: int) -> str:
    """Deterministic short ID from content + position."""
    raw = f"{index}:{en_content[:200]}:{zh_content[:200]}"
    return hashlib.md5(raw.encode(), usedforsecurity=False).hexdigest()[:10]


def _is_show_once(block: MdBlock) -> str | None:
    """Return the show-once element type for a block, or None."""
    if block.block_type == CODE:
        return "code"
    if block.block_type == IMAGE:
        return "image"
    if block.block_type == HR:
        return "hr"
    return None


# -- Public alignment entry point --------------------------------------

def align_markdown(en_md: str, zh_md: str) -> dict:
    """Align EN and ZH Markdown pages, returning structured content groups.

    Returns a dict with:
        ``page_class``: ``"bilingual" | "en_only" | "zh_only"``
        ``groups``: list of :meth:`AlignGroup.to_dict` dicts
        ``review_count``: number of low-confidence groups
        ``en_hash`` / ``zh_hash``: content hashes for change detection
    """
    # Strip source comments.
    en_md = SOURCE_COMMENT_RE.sub("", en_md).strip()
    zh_md = SOURCE_COMMENT_RE.sub("", zh_md).strip()

    en_blocks = split_blocks(en_md)
    zh_blocks = split_blocks(zh_md)

    en_hash = hashlib.sha256(en_md.encode()).hexdigest()[:16]
    zh_hash = hashlib.sha256(zh_md.encode()).hexdigest()[:16]

    if not en_blocks and not zh_blocks:
        return {"page_class": "en_only", "groups": [], "review_count": 0,
                "en_hash": en_hash, "zh_hash": zh_hash}
    if not zh_blocks:
        return {"page_class": "en_only", "groups": [], "review_count": 0,
                "en_hash": en_hash, "zh_hash": zh_hash}
    if not en_blocks:
        return {"page_class": "zh_only", "groups": [], "review_count": 0,
                "en_hash": en_hash, "zh_hash": zh_hash}

    en_sections = _group_into_sections(en_blocks)
    zh_sections = _group_into_sections(zh_blocks)

    groups: list[AlignGroup] = []

    # Pair sections by position (same-page translations have matching structure).
    max_sections = max(len(en_sections), len(zh_sections))
    for si in range(max_sections):
        en_sec = en_sections[si] if si < len(en_sections) else None
        zh_sec = zh_sections[si] if si < len(zh_sections) else None

        # Emit heading as its own group (show-once if both have it, EN-only otherwise).
        if en_sec and en_sec.heading:
            groups.append(AlignGroup(
                group_id=_stable_group_id(en_sec.heading.content, "", len(groups)),
                en_content=en_sec.heading.content,
                zh_content=zh_sec.heading.content if zh_sec and zh_sec.heading else "",
                shape="1:1",
                confidence=1.0,
            ))

        if not en_sec or not en_sec.blocks:
            # ZH-only blocks in this section.
            if zh_sec and zh_sec.blocks:
                for blk in zh_sec.blocks:
                    groups.append(AlignGroup(
                        group_id=_stable_group_id("", blk.content, len(groups)),
                        en_content="",
                        zh_content=blk.content,
                        shape="0:1",
                        confidence=0.0,
                    ))
            continue

        if not zh_sec or not zh_sec.blocks:
            # EN-only blocks in this section.
            for blk in en_sec.blocks:
                show = _is_show_once(blk)
                groups.append(AlignGroup(
                    group_id=_stable_group_id(blk.content, "", len(groups)),
                    en_content=blk.content,
                    zh_content="",
                    shape="1:0",
                    confidence=1.0 if show else 0.0,
                    show_once=[show] if show else [],
                ))
            continue

        # Align blocks within the section.
        raw_groups = _align_interval(en_sec.blocks, zh_sec.blocks, 0, 0)
        for en_s, en_e, zh_s, zh_e, cost in raw_groups:
            en_slice = en_sec.blocks[en_s:en_e]
            zh_slice = zh_sec.blocks[zh_s:zh_e]
            en_content = "\n\n".join(b.content for b in en_slice)
            zh_content = "\n\n".join(b.content for b in zh_slice)
            shape = f"{en_e - en_s}:{zh_e - zh_s}"

            en_feat = _combine_features([b.feats for b in en_slice])
            zh_feat = _combine_features([b.feats for b in zh_slice])
            ratio = en_feat["len"] / max(1, zh_feat["len"])
            show_once: list[str] = []
            for blk in en_slice:
                s = _is_show_once(blk)
                if s and s not in show_once:
                    show_once.append(s)

            # Language-neutral elements (code, images, hr) are shown once
            # in the EN panel — never duplicated in the ZH panel.
            if show_once:
                zh_content = ""

            is_low = (
                shape not in ("1:1", "1:0", "0:1")
                or abs(cost) > REVIEW_COST_THRESHOLD
                or ratio > REVIEW_RATIO_MAX
                or ratio < REVIEW_RATIO_MIN
            )
            groups.append(AlignGroup(
                group_id=_stable_group_id(en_content, zh_content, len(groups)),
                en_content=en_content,
                zh_content=zh_content,
                shape=shape,
                confidence=1.0 / (1.0 + abs(cost)),
                show_once=show_once,
                low_confidence=is_low,
            ))

    review_count = sum(1 for g in groups if g.low_confidence)
    return {
        "page_class": "bilingual",
        "groups": [g.to_dict() for g in groups],
        "review_count": review_count,
        "en_hash": en_hash,
        "zh_hash": zh_hash,
    }


def align_markdown_en_only(en_md: str) -> dict:
    """Produce an en_only alignment result for a page without ZH translation."""
    en_md = SOURCE_COMMENT_RE.sub("", en_md).strip()
    en_blocks = split_blocks(en_md)
    en_hash = hashlib.sha256(en_md.encode()).hexdigest()[:16]
    groups: list[AlignGroup] = []
    for blk in en_blocks:
        show = _is_show_once(blk)
        groups.append(AlignGroup(
            group_id=_stable_group_id(blk.content, "", len(groups)),
            en_content=blk.content,
            zh_content="",
            shape="1:0",
            confidence=1.0 if show else 0.0,
            show_once=[show] if show else [],
        ))
    return {
        "page_class": "en_only",
        "groups": [g.to_dict() for g in groups],
        "review_count": 0,
        "en_hash": en_hash,
        "zh_hash": "",
    }
