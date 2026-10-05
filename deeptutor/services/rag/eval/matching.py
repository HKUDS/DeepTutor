"""Gold-passage matching for retrieval evaluation.

An engine returns ranked chunks, not ground-truth identifiers, so relevance has
to be decided from text. A chunk counts as covering a gold passage when either

* one normalized text contains the other — the common cases are a chunk holding
  the excerpt verbatim, and a *truncated* citation whose opening text sits inside
  a longer gold passage (LlamaIndex and GraphRAG both cap ``content`` at 200
  characters); or
* the two share enough tokens — this catches a paraphrased or synthesized
  citation (LightRAG reports, GraphRAG community summaries) that never repeats
  the excerpt word for word.

The token rule needs both a coverage ratio and a minimum shared-token count, so a
short generic phrase ("the model") cannot claim a long passage it merely happens
to appear in. Tokens are ASCII words plus individual CJK characters, which keeps
a Chinese excerpt comparable without a segmenter dependency.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import re
from typing import Any

#: Share of the shorter side's tokens that must overlap for an overlap match.
DEFAULT_MIN_RATIO = 0.5
#: Shared tokens required before an overlap match is accepted.
DEFAULT_MIN_TOKENS = 4

_WHITESPACE = re.compile(r"\s+")
# ASCII words and digits, or one token per CJK / Kana / Hangul character.
_TOKEN = re.compile(
    r"[0-9a-z]+"
    r"|[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uac00-\ud7af]"
)

#: Keys that hold a citation's text across the shipped engines.
SOURCE_TEXT_KEYS = ("content", "text", "snippet", "excerpt", "summary")


def normalize_text(value: str) -> str:
    """Lower-case ``value`` and collapse whitespace for containment checks."""
    return _WHITESPACE.sub(" ", (value or "").strip().lower())


def tokenize(value: str) -> list[str]:
    """Split ``value`` into comparison tokens (ASCII words + CJK characters)."""
    return _TOKEN.findall((value or "").lower())


def source_text(source: Any) -> str:
    """Return the text of one citation record, across the engines' shapes.

    Every pipeline normalizes what it retrieved into ``content``, but a
    hand-written record or a future engine may use another key; an unrecognized
    or non-mapping record yields an empty string, which never matches.
    """
    if not isinstance(source, Mapping):
        return ""
    for key in SOURCE_TEXT_KEYS:
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


@dataclass(frozen=True)
class MatchPolicy:
    """Thresholds for treating a retrieved chunk as covering a gold passage."""

    min_ratio: float = DEFAULT_MIN_RATIO
    min_tokens: int = DEFAULT_MIN_TOKENS

    def __post_init__(self) -> None:
        """Reject thresholds that would make matching either trivial or impossible."""
        if not 0.0 < float(self.min_ratio) <= 1.0:
            raise ValueError("min_ratio must be in (0, 1]")
        if int(self.min_tokens) < 1:
            raise ValueError("min_tokens must be >= 1")


@dataclass(frozen=True)
class MatchResult:
    """Which gold passages a chunk covers, plus the strongest coverage ratio."""

    indices: tuple[int, ...] = ()
    ratio: float = 0.0

    def __bool__(self) -> bool:
        """True when the chunk covers at least one gold passage."""
        return bool(self.indices)


@dataclass(frozen=True)
class GoldPassage:
    """A gold passage prepared once, then matched against every retrieved chunk."""

    index: int
    text: str
    normalized: str
    tokens: Counter[str]
    token_count: int

    @classmethod
    def from_text(cls, index: int, text: str) -> GoldPassage:
        """Tokenize one gold passage for repeated comparison."""
        token_list = tokenize(text)
        return cls(
            index=index,
            text=text,
            normalized=normalize_text(text),
            tokens=Counter(token_list),
            token_count=len(token_list),
        )


def _overlap(
    chunk_tokens: Counter[str],
    chunk_count: int,
    passage: GoldPassage,
) -> tuple[float, int]:
    """Return ``(ratio, shared)`` for one chunk/passage pair.

    The ratio divides by the shorter side's token count, so a truncated citation
    whose tokens are all inside the passage still scores 1.0.
    """
    if chunk_count <= 0 or passage.token_count <= 0:
        return 0.0, 0
    shared = 0
    for token, count in chunk_tokens.items():
        passage_count = passage.tokens.get(token, 0)
        if passage_count:
            shared += min(count, passage_count)
    shorter = min(chunk_count, passage.token_count)
    return shared / shorter, shared


class RelevanceMatcher:
    """Decide whether retrieved chunks cover one case's gold passages.

    The matcher is built per case: it prepares each gold passage once and then
    scores every ranked chunk against them.

    Args:
        gold: The case's gold excerpts, in dataset order.
        policy: Matching thresholds; defaults to :class:`MatchPolicy`.
    """

    def __init__(self, gold: Sequence[str], policy: MatchPolicy | None = None) -> None:
        self.policy = policy or MatchPolicy()
        self.gold: tuple[GoldPassage, ...] = tuple(
            GoldPassage.from_text(index, passage)
            for index, passage in enumerate(gold)
            if isinstance(passage, str) and passage.strip()
        )

    @property
    def gold_count(self) -> int:
        """Number of non-blank gold passages this matcher scored against."""
        return len(self.gold)

    def match(self, text: str) -> MatchResult:
        """Return the gold passages ``text`` covers and the best coverage ratio."""
        normalized = normalize_text(text)
        if not normalized or not self.gold:
            return MatchResult()

        chunk_tokens = Counter(tokenize(text))
        chunk_count = sum(chunk_tokens.values())

        indices: list[int] = []
        best = 0.0
        for passage in self.gold:
            ratio = self._ratio(normalized, chunk_tokens, chunk_count, passage)
            if ratio > 0.0:
                indices.append(passage.index)
                best = max(best, ratio)
        return MatchResult(tuple(indices), round(best, 4))

    def _ratio(
        self,
        normalized: str,
        chunk_tokens: Counter[str],
        chunk_count: int,
        passage: GoldPassage,
    ) -> float:
        """Coverage ratio for one passage (0.0 when it is not a match)."""
        if not passage.normalized:
            return 0.0
        if passage.normalized in normalized:
            return 1.0
        # A truncated citation is shorter than the passage it quotes, so an
        # exact reverse containment is only meaningful once it carries enough
        # tokens to be more than an incidental substring.
        if chunk_count >= max(1, int(self.policy.min_tokens)) and normalized in passage.normalized:
            return 1.0

        ratio, shared = _overlap(chunk_tokens, chunk_count, passage)
        if ratio < float(self.policy.min_ratio) or shared < int(self.policy.min_tokens):
            return 0.0
        return ratio


__all__ = [
    "DEFAULT_MIN_RATIO",
    "DEFAULT_MIN_TOKENS",
    "GoldPassage",
    "MatchPolicy",
    "MatchResult",
    "RelevanceMatcher",
    "SOURCE_TEXT_KEYS",
    "normalize_text",
    "source_text",
    "tokenize",
]
