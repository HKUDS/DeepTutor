"""Paragraph-level alignment core, vendored from epub-bilingual-translator (MIT).

Pure-stdlib (re/dataclasses/json). Extracts English paragraphs and Chinese
translation units from XHTML, runs hierarchical DP alignment (supports 1:1,
1:2, 2:1, 2:2, 1:3, 3:1), and yields renderable paragraph pairs.

Two public entry points:
  * ``align_groups`` -- raw ``Group`` index ranges (for EPUB generation).
  * ``extract_align_pairs`` -- slice the groups into plain-text paragraph pairs
    (for in-app rendering and storage).
"""

from __future__ import annotations

from dataclasses import dataclass, field
import html
import json
from pathlib import Path
import re
from typing import Any, Iterable, List, Sequence, Tuple

BLOCK_RE = re.compile(r"<(p|h2|h3|h4|blockquote)([^>]*)>(.*?)</\1>", re.DOTALL | re.IGNORECASE)
TAG_RE = re.compile(r"<[^>]+>")
TAG_TOKEN_RE = re.compile(r"(<[^>]+>)")
BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
STANDALONE_ZH_NOTE_RE = re.compile(
    r"^[\u3010\s]*[\u8a3b\u6ce8](?:\s*[0-9\uff10-\uff19\u4e00-\u4e95\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341\u767e]+)?[\s\u3011]*"
)
ID_RE = re.compile(r"\bid=(['\"])([^'\"]+)\1")
WS_RE = re.compile(r"\s+")
VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}
YEAR_RE = re.compile(r"(?<![a-zA-Z0-9])(?:1[0-9]{3}|20[0-2][0-9])(?![a-zA-Z0-9])")
NUM_RE = re.compile(r"(?<![0-9.])\d+(?:\.\d+)?(?![0-9.])")
LATIN_RE = re.compile(r"(?<![a-zA-Z])[A-Za-z][A-Za-z\-']{2,}(?![a-zA-Z])")

ABBREVIATIONS = {
    "mr",
    "mrs",
    "ms",
    "dr",
    "prof",
    "sr",
    "jr",
    "st",
    "co",
    "inc",
    "ltd",
    "corp",
    "vs",
    "v",
    "e.g",
    "i.e",
    "etc",
    "cf",
    "vol",
    "vols",
    "no",
    "nos",
    "sec",
    "fig",
    "figs",
    "p",
    "pp",
    "ch",
    "ed",
    "eds",
    "trans",
    "app",
    "dept",
    "univ",
    "approx",
    "ibid",
    "u.s",
    "u.k",
    "u.n",
    "d.c",
    "a.m",
    "p.m",
}

_REVIEW_COST_THRESHOLD = 1.2
_REVIEW_RATIO_MAX = 3.5
_REVIEW_RATIO_MIN = 0.28


@dataclass
class EnPara:
    tag: str
    attrs: str
    inner: str
    text: str
    source: str
    start: int
    end: int
    ident: str
    feats: dict


@dataclass
class ZhUnit:
    tag: str
    attrs: str
    inner: str
    text: str
    heading_html: str
    heading_text: str
    ident: str
    feats: dict


@dataclass
class Group:
    en_start: int
    en_end: int
    zh_start: int
    zh_end: int
    cost: float
    forced: bool = False


@dataclass
class AlignPair:
    """A renderable paragraph group: English paragraphs paired with Chinese."""

    en: List[str] = field(default_factory=list)
    zh: List[str] = field(default_factory=list)
    shape: str = "1:1"
    cost: float = 0.0
    forced: bool = False
    low_confidence: bool = False


def halfwidth(text: str) -> str:
    return "".join(
        chr(ord(ch) - 65248) if 65281 <= ord(ch) <= 65374 else " " if ord(ch) == 12288 else ch
        for ch in text
    )


def plain_text(inner: str) -> str:
    return WS_RE.sub(" ", halfwidth(html.unescape(TAG_RE.sub("", inner)))).strip()


def attr_id(attrs: str) -> str:
    match = ID_RE.search(attrs)
    return match.group(2) if match else ""


def feature_set(text: str) -> dict:
    latin = set(word.lower() for word in LATIN_RE.findall(text))
    stop = {
        "the",
        "and",
        "for",
        "that",
        "with",
        "this",
        "from",
        "were",
        "was",
        "are",
        "have",
        "has",
        "had",
        "not",
        "but",
        "they",
        "their",
        "them",
        "what",
        "when",
        "where",
        "than",
        "then",
        "into",
        "onto",
        "about",
        "over",
        "under",
        "after",
        "before",
        "also",
        "only",
        "more",
        "most",
        "such",
        "some",
        "any",
        "all",
        "can",
        "could",
        "would",
        "should",
        "may",
        "might",
        "will",
        "shall",
        "one",
        "two",
        "three",
        "four",
        "five",
        "six",
        "seven",
        "eight",
        "nine",
        "ten",
        "information",
        "network",
        "human",
        "history",
        "chapter",
        "book",
    }
    return {
        "years": set(YEAR_RE.findall(text)),
        "nums": set(NUM_RE.findall(text)),
        "latin": {word for word in latin if word not in stop and len(word) >= 4},
        "len": max(1, len(text)),
    }


def combine_features(items: Iterable[dict]) -> dict:
    out: dict[str, Any] = {"years": set(), "nums": set(), "latin": set(), "len": 0}
    for feat in items:
        out["years"] |= feat["years"]
        out["nums"] |= feat["nums"]
        out["latin"] |= feat["latin"]
        out["len"] += feat["len"]
    out["len"] = max(1, out["len"])
    return out


def extract_en_paragraphs(xml: str) -> List[EnPara]:
    """Extract <p> and <blockquote> elements from English XHTML."""
    result: List[EnPara] = []
    for match in BLOCK_RE.finditer(xml):
        tag, attrs, inner = match.group(1).lower(), match.group(2), match.group(3)
        if tag not in {"p", "blockquote"}:
            continue
        text = plain_text(inner)
        if text:
            result.append(
                EnPara(
                    tag,
                    attrs,
                    inner,
                    text,
                    match.group(0),
                    match.start(),
                    match.end(),
                    attr_id(attrs),
                    feature_set(text),
                )
            )
    return result


def _prefix_zh_ids(markup: str) -> str:
    def prefix_id(match: re.Match[str]) -> str:
        quote, ident = match.group(1), match.group(2)
        return f"id={quote}{ident if ident.startswith('zh-') else 'zh-' + ident}{quote}"

    markup = re.sub(r"\bid=(['\"])([^'\"]+)\1", prefix_id, markup)
    return re.sub(
        r"\bhref=(['\"])#([^'\"]+)\1",
        lambda m: (
            f"href={m.group(1)}#{m.group(2) if m.group(2).startswith('zh-') else 'zh-' + m.group(2)}{m.group(1)}"
        ),
        markup,
    )


def _without_class(attrs: str) -> str:
    return re.sub(r"""\sclass=(?:"[^"]*"|'[^']*')""", "", attrs)


def fold_standalone_zh_notes(units: Sequence[ZhUnit]) -> List[ZhUnit]:
    """Fold standalone translator-note fragments (beginning with note markers)
    into the preceding translated paragraph so they don't shift alignment."""
    folded: List[ZhUnit] = []
    leading_notes: List[ZhUnit] = []
    for unit in units:
        if STANDALONE_ZH_NOTE_RE.match(unit.text.lstrip()):
            if not folded:
                leading_notes.append(unit)
                continue
            previous = folded[-1]
            previous.inner = f"{previous.inner.rstrip()}<br/>{unit.inner.lstrip()}"
            previous.text = f"{previous.text.rstrip()} {unit.text.lstrip()}"
            previous.feats = feature_set(f"{previous.heading_text} {previous.text}".strip())
            continue
        if leading_notes:
            note_inner = "<br/>".join(note.inner.strip() for note in leading_notes)
            note_text = " ".join(note.text.strip() for note in leading_notes)
            unit.inner = f"{note_inner}<br/>{unit.inner.lstrip()}"
            unit.text = f"{note_text} {unit.text.lstrip()}"
            unit.feats = feature_set(f"{unit.heading_text} {unit.text}".strip())
            leading_notes = []
        folded.append(unit)
    if leading_notes and folded:
        previous = folded[-1]
        note_inner = "<br/>".join(note.inner.strip() for note in leading_notes)
        note_text = " ".join(note.text.strip() for note in leading_notes)
        previous.inner = f"{previous.inner.rstrip()}<br/>{note_inner}"
        previous.text = f"{previous.text.rstrip()} {note_text}"
        previous.feats = feature_set(f"{previous.heading_text} {previous.text}".strip())
    return folded


def extract_zh_units(xml: str) -> Tuple[List[ZhUnit], str]:
    """Extract Chinese translation units and optional footnotes from XHTML."""
    body, footnotes = xml, ""
    if 'class="footnote"' in xml:
        body, footnotes = xml.split('class="footnote"', 1)
    elif "<hr" in xml and ('id="fnX-' in xml or 'id="fX-' in xml):
        parts = re.split(r"<hr\s*/?>", xml)
        if len(parts) > 1:
            body, footnotes = parts[0], parts[-1]
    pending: List[Tuple[str, str, str, str]] = []
    units: List[ZhUnit] = []
    for match in BLOCK_RE.finditer(body):
        tag, attrs, inner = match.group(1).lower(), match.group(2), match.group(3)
        text = plain_text(inner)
        if not text or text.startswith("\u5ef6\u4f38\u95b1\u8b80"):
            continue
        if tag in {"h2", "h3", "h4"}:
            pending.append((tag, attrs, inner, text))
            continue
        if tag not in {"p", "blockquote"}:
            continue
        heading_html, heading_text = "", ""
        if pending:
            heading_html = "\n".join(
                f'<{h_tag} class="zh-subheading"{_prefix_zh_ids(_without_class(h_attrs))}>{_prefix_zh_ids(h_inner)}</{h_tag}>'
                for h_tag, h_attrs, h_inner, _ in pending
            )
            heading_text = " / ".join(item[3] for item in pending)
            pending = []
        prefixed_attrs = _prefix_zh_ids(attrs)
        prefixed_inner = _prefix_zh_ids(inner)
        full_text = (heading_text + " " + text).strip()
        units.append(
            ZhUnit(
                tag,
                prefixed_attrs,
                prefixed_inner,
                text,
                heading_html,
                heading_text,
                attr_id(attrs),
                feature_set(full_text),
            )
        )
    # Calibre bare-text exports use <br/> as paragraph separators and omit <p>.
    if BR_RE.search(body) and len(BR_RE.findall(body)) > len(units):
        units = []
        body_match = re.search(
            r"<body\b[^>]*>(.*?)</body\s*>", body, flags=re.IGNORECASE | re.DOTALL
        )
        fallback_body = body_match.group(1) if body_match else body
        fallback_body = re.sub(
            r"<head\b[^>]*>.*?</head\s*>", "", fallback_body, flags=re.IGNORECASE | re.DOTALL
        )
        for fragment in BR_RE.split(fallback_body):
            fragment = re.sub(r"</?p\b[^>]*>", "", fragment, flags=re.IGNORECASE)
            text = plain_text(fragment)
            if (
                not text
                or text.startswith("\u5ef6\u4f38\u95b1\u8b80")
                or "\u203b" in text
                or re.fullmatch(
                    r"\u7b2c?[\u4e00-\u4e95\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341\u767e\u96f6\u3007\u4e8c0-9]+\u7ae0?",
                    text,
                )
            ):
                continue
            prefixed_inner = _prefix_zh_ids(fragment.strip())
            units.append(ZhUnit("p", "", prefixed_inner, text, "", "", "", feature_set(text)))
    return fold_standalone_zh_notes(units), footnotes


def _length_cost(en_feat: dict, zh_feat: dict, target_en_len: float) -> float:
    length_error = abs(en_feat["len"] - target_en_len) / (target_en_len + 35.0)
    return length_error * length_error


def _feature_cost(en_feat: dict, zh_feat: dict) -> float:
    year_shared = len(en_feat["years"] & zh_feat["years"])
    num_shared = len(en_feat["nums"] & zh_feat["nums"])
    latin_shared = len(en_feat["latin"] & zh_feat["latin"])
    year_miss = len(en_feat["years"] ^ zh_feat["years"])
    return -1.30 * year_shared - 0.35 * num_shared - 0.55 * latin_shared + 0.30 * year_miss


def pair_cost(en_feat: dict, zh_feat: dict, target_en_len: float) -> float:
    return _length_cost(en_feat, zh_feat, target_en_len) + _feature_cost(en_feat, zh_feat)


def align_interval(
    en: Sequence[EnPara], zh: Sequence[ZhUnit], en_offset: int, zh_offset: int
) -> List[Group]:
    if not en or not zh:
        return []
    m, n = len(en), len(zh)
    total_en = sum(item.feats["len"] for item in en)
    total_zh = sum(item.feats["len"] for item in zh)
    inf = float("inf")
    dp = [[inf] * (n + 1) for _ in range(m + 1)]
    back: List[List[Tuple[int, int] | None]] = [[None] * (n + 1) for _ in range(m + 1)]
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
                en_feat = combine_features(item.feats for item in en[i:ni])
                zh_feat = combine_features(item.feats for item in zh[j:nj])
                target = total_en * (zh_feat["len"] / total_zh)
                group_size = max(take_en, take_zh)
                complexity = 0.12 * (take_en + take_zh - 2)
                cost = (
                    dp[i][j]
                    + _length_cost(en_feat, zh_feat, target)
                    + _feature_cost(en_feat, zh_feat) / group_size
                    + complexity
                )
                if cost < dp[ni][nj]:
                    dp[ni][nj], back[ni][nj] = cost, (take_en, take_zh)
    if dp[m][n] == inf:
        return [
            Group(
                en_offset + i,
                en_offset + i + 1,
                zh_offset + min(i, n - 1),
                zh_offset + min(i + 1, n),
                9.0,
            )
            for i in range(min(m, n))
        ]
    groups: List[Group] = []
    i, j = m, n
    while i or j:
        step = back[i][j]
        if step is None:
            raise ValueError("Paragraph alignment has no backtrace")
        take_en, take_zh = step
        start_i, start_j = i - take_en, j - take_zh
        groups.append(
            Group(
                en_offset + start_i,
                en_offset + i,
                zh_offset + start_j,
                zh_offset + j,
                dp[i][j] - dp[start_i][start_j],
            )
        )
        i, j = start_i, start_j
    return list(reversed(groups))


def load_overrides(path: Path | None) -> dict[str, List[dict]]:
    if path is None:
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    items = raw.get("overrides", raw) if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        raise ValueError(
            "alignment overrides must be a JSON list or an object with an overrides list"
        )
    result: dict[str, List[dict]] = {}
    for item in items:
        result.setdefault(item["chapter"], []).append(item)
    return result


def align_groups(
    en: Sequence[EnPara], zh: Sequence[ZhUnit], chapter: str, overrides: dict[str, List[dict]]
) -> List[Group]:
    en_ids = {item.ident: index for index, item in enumerate(en) if item.ident}
    zh_ids = {item.ident: index for index, item in enumerate(zh) if item.ident}
    fixed = []
    for item in overrides.get(chapter, []):
        en_range = [en_ids[ident] for ident in item["english_ids"]]
        zh_range = [zh_ids[ident] for ident in item["translation_ids"]]
        if en_range != list(range(min(en_range), max(en_range) + 1)) or zh_range != list(
            range(min(zh_range), max(zh_range) + 1)
        ):
            raise ValueError(f"Non-contiguous alignment override in {chapter}")
        fixed.append((min(en_range), max(en_range) + 1, min(zh_range), max(zh_range) + 1))
    fixed.sort()
    result, en_pos, zh_pos = [], 0, 0
    for en_start, en_end, zh_start, zh_end in fixed:
        if en_start < en_pos or zh_start < zh_pos:
            raise ValueError(f"Overlapping or out-of-order alignment override in {chapter}")
        result.extend(align_interval(en[en_pos:en_start], zh[zh_pos:zh_start], en_pos, zh_pos))
        result.append(Group(en_start, en_end, zh_start, zh_end, 0.0, True))
        en_pos, zh_pos = en_end, zh_end
    result.extend(align_interval(en[en_pos:], zh[zh_pos:], en_pos, zh_pos))
    return result


# -- Sentence-splitting helpers for 1:N paragraph rendering --------------


def _tag_name(markup: str) -> str:
    match = re.match(r"<\s*([A-Za-z0-9:_-]+)", markup)
    return match.group(1).lower() if match else ""


def _reopening_tag(markup: str) -> str:
    """Strip id from an opening tag so it can be reopened safely in a fragment."""
    return ID_RE.sub("", markup)


def split_sentences(text: str) -> List[str]:
    """Split English text into sentences, respecting abbreviations."""
    if not text:
        return []
    tokens, start = [], 0
    for match in re.finditer(r"""([.!?]['"\u201d\u2019\)]*)\s+""", text):
        tokens.append(text[start : match.start()] + match.group(1))
        start = match.end()
    if start < len(text):
        tokens.append(text[start:])
    sentences, buffered = [], ""
    for token in tokens:
        buffered = (buffered + " " + token).strip() if buffered else token
        last = re.search(r"""([A-Za-z0-9.]+)[.!?]['"\u201d\u2019\)]*$""", buffered)
        word = last.group(1).lower().rstrip(".") if last else ""
        if (
            word in ABBREVIATIONS
            or re.fullmatch(r"[a-z]\.[a-z]", word)
            or re.search(r"\d\.\d$", buffered)
        ):
            continue
        if re.fullmatch(r"\d+", buffered):
            if sentences:
                sentences[-1] += " " + buffered
            else:
                sentences.append(buffered)
        else:
            sentences.append(buffered)
        buffered = ""
    if buffered:
        sentences.append(buffered)
    return sentences


def fragment_inner(inner: str, sentence_count_ends: Sequence[int]) -> List[str]:
    """Split mixed XHTML after sentence boundaries while retaining valid markup."""
    boundaries = list(sentence_count_ends[:-1])
    if not boundaries:
        return [inner]
    pieces: List[List[str]] = [[]]
    open_tags: List[Tuple[str, str]] = []
    normalized_pos, boundary_pos, in_space = 0, 0, False

    def cut() -> None:
        nonlocal boundary_pos
        for name, _ in reversed(open_tags):
            pieces[-1].append(f"</{name}>")
        pieces.append([_reopening_tag(markup) for _, markup in open_tags])
        boundary_pos += 1

    for token in TAG_TOKEN_RE.split(inner):
        if not token:
            continue
        if token.startswith("<"):
            pieces[-1].append(token)
            if token.startswith("</"):
                name = re.match(r"</\s*([A-Za-z0-9:_-]+)", token)
                if name:
                    for index in range(len(open_tags) - 1, -1, -1):
                        if open_tags[index][0] == name.group(1).lower():
                            del open_tags[index:]
                            break
            elif not token.startswith("<!") and not token.startswith("<?"):
                tag_name = _tag_name(token)
                if tag_name and tag_name not in VOID_TAGS and not token.rstrip().endswith("/>"):
                    open_tags.append((tag_name, token))
            continue
        for char in token:
            if char.isspace():
                if normalized_pos == 0 or (pieces[-1] and not "".join(pieces[-1]).strip()):
                    continue
                pieces[-1].append(char)
                if not in_space:
                    normalized_pos += 1
                in_space = True
            else:
                pieces[-1].append(char)
                normalized_pos += 1
                in_space = False
            if boundary_pos < len(boundaries) and normalized_pos >= boundaries[boundary_pos]:
                cut()
    while len(pieces) < len(sentence_count_ends):
        pieces.append([])
    return ["".join(piece).strip() for piece in pieces]


def sentence_partitions(sentences: Sequence[str], zh: Sequence[ZhUnit]) -> List[Tuple[int, int]]:
    """DP-partition sentences into len(zh) contiguous groups."""
    m, n = len(sentences), len(zh)
    if not sentences:
        return []
    if m < n:
        return [(0, m)]
    total_en = sum(len(s) for s in sentences)
    total_zh = sum(unit.feats["len"] for unit in zh)
    inf = float("inf")
    dp = [[inf] * (m + 1) for _ in range(n + 1)]
    back = [[-1] * (m + 1) for _ in range(n + 1)]
    dp[0][0] = 0.0
    for j in range(1, n + 1):
        target = total_en * (zh[j - 1].feats["len"] / total_zh)
        for end in range(j, m - (n - j) + 1):
            for start in range(j - 1, end):
                length = sum(len(s) for s in sentences[start:end])
                cost = dp[j - 1][start] + pair_cost(
                    {"years": set(), "nums": set(), "latin": set(), "len": length},
                    zh[j - 1].feats,
                    target,
                )
                if cost < dp[j][end]:
                    dp[j][end], back[j][end] = cost, start
    result, end = [], m
    for j in range(n, 0, -1):
        start = back[j][end]
        if start < 0:
            return [(0, m)]
        result.append((start, end))
        end = start
    return list(reversed(result))


def extract_align_pairs(
    en_xhtml: str,
    zh_xhtml: str,
    overrides: dict[str, List[dict]] | None = None,
    chapter: str = "chapter",
) -> dict[str, Any]:
    """Align English and Chinese XHTML, returning renderable paragraph pairs.

    Returns a dict with:
      * ``chapter``: the chapter id.
      * ``en_title``: best-effort English heading from the first heading element.
      * ``pairs``: count of Chinese units aligned.
      * ``groups``: list of ``AlignPair``-shaped dicts for rendering.
      * ``review``: groups flagged for manual review (non-1:1, forced, or low-confidence).
    """
    overrides = overrides or {}
    en = extract_en_paragraphs(en_xhtml)
    zh, _zh_footnotes = extract_zh_units(zh_xhtml)

    en_title = ""
    title_match = re.search(r"<h[1-4][^>]*>(.*?)</h[1-4]>", en_xhtml, re.DOTALL | re.IGNORECASE)
    if title_match:
        en_title = plain_text(title_match.group(1))

    if not en or not zh:
        return {
            "chapter": chapter,
            "en_title": en_title,
            "pairs": 0,
            "groups": [],
            "review": [],
        }

    groups = align_groups(en, zh, chapter, overrides)
    render_pairs: List[dict[str, Any]] = []
    review: List[dict[str, Any]] = []
    for group in groups:
        en_slice = en[group.en_start : group.en_end]
        zh_slice = zh[group.zh_start : group.zh_end]
        en_feat = combine_features(item.feats for item in en_slice)
        zh_feat = combine_features(item.feats for item in zh_slice)
        ratio = en_feat["len"] / max(1, zh_feat["len"])
        shape = f"{group.en_end - group.en_start}:{group.zh_end - group.zh_start}"
        is_low = (
            shape != "1:1"
            or group.cost > _REVIEW_COST_THRESHOLD
            or ratio > _REVIEW_RATIO_MAX
            or ratio < _REVIEW_RATIO_MIN
        )
        pair = AlignPair(
            en=[item.text for item in en_slice],
            zh=[item.text for item in zh_slice],
            shape=shape,
            cost=round(group.cost, 3),
            forced=group.forced,
            low_confidence=is_low,
        )
        render_pairs.append(pair.__dict__)
        if shape != "1:1" or group.forced or is_low:
            review.append(
                {
                    **pair.__dict__,
                    "en_preview": " ".join(item.text for item in en_slice)[:180],
                    "zh_preview": " ".join(item.text for item in zh_slice)[:180],
                }
            )
    return {
        "chapter": chapter,
        "en_title": en_title,
        "pairs": len(zh),
        "groups": render_pairs,
        "review": review,
    }
