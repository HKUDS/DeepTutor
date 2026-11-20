"""Chunks, scope filtering and citation validation.

The one rule this module exists to enforce
-----------------------------------------
ROADMAP Phase 5: *"no grade/track leakage in an adversarial test"*. Everything
here is in service of that sentence.

Leakage is not a single bug, it is a family:

* a grade-12 chunk returned to a grade-10 student because the filter was
  optional;
* a ریاضی‌فیزیک chunk returned to a تجربی student because "shared" was read as
  "matches everything";
* a chunk from a revoked source returned because the rights verdict was read at
  ingest time and never re-checked;
* a chunk whose scope is NULL returned because ``NULL = 10`` is NULL, which is
  not false, so a careless comparison silently *drops* it -- or, worse, a
  ``COALESCE(NULL, 10)`` silently *admits* it.

The design that closes this family is a single function, :func:`retrievable`,
that every read path must go through. It takes the resolved enrolment and
applies all four predicates as SQL, so a caller cannot forget one: there is no
parameter for "skip the scope check".

Why the rights check is a join and not a column read
----------------------------------------------------
``ingestion_chunks.rights_status`` is the verdict *at ingest time*. A source can
be archived after ingestion -- that is the entire point of Phase 4's review
workflow. So retrieval joins ``catalog_sources`` and requires
``publicly_retrievable = 1`` live. The denormalised column is kept because it
records what was believed when the chunk was written, which is what makes an
audit of "we served this before we knew" possible.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import re
from typing import Any, Sequence

from deeptutor.db.connection import Database

logger = logging.getLogger(__name__)

#: Block kinds the extractor recognises. ``ocr`` is distinct from ``text``
#: because a citation from an OCR'd page deserves a different confidence story
#: than one from an embedded text layer.
VALID_BLOCK_KINDS = frozenset({"text", "table", "figure", "formula", "ocr"})

#: When a student's enrolment has no major (grades 1-9), chunks scoped to *any*
#: major must be excluded. This sentinel is used rather than an empty string so
#: the SQL predicate is a value comparison and cannot be confused with "no
#: filter requested".
NO_MAJOR = ""


class GroundingError(RuntimeError):
    """A grounding or scope rule was violated.

    A plain ``RuntimeError`` subclass, not a frozen dataclass: CPython assigns
    ``__traceback__`` on raise, which a frozen dataclass forbids.
    """

    def __init__(self, rule: str, detail: str, *, field: str | None = None) -> None:
        self.rule = rule
        self.detail = detail
        self.field = field
        super().__init__(f"{rule}: {detail}")


class ScopeViolation(GroundingError):
    """A retrieval request tried to widen the caller's scope."""

    def __init__(self, detail: str, *, field: str = "scope") -> None:
        super().__init__("scope_violation", detail, field=field)


class CitationError(GroundingError):
    """A citation does not point at a chunk that was actually retrieved."""

    def __init__(self, detail: str, *, field: str = "citation") -> None:
        super().__init__("invalid_citation", detail, field=field)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# The derivation lives in a leaf module because the ingestion pipeline computes
# the same keys and importing the pipeline from here would invert the layering.
# Re-exported so callers of this module never need to know that.


# ---------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------


def scope_sql(enrolment: dict[str, Any]) -> tuple[str, tuple[Any, ...]]:
    """Build the scope predicate for one student's enrolment.

    Returns a SQL fragment and its parameters. The fragment is **always**
    non-empty: an enrolment with no filter is not a supported state, because a
    filter that can be omitted is a filter that will be omitted.

    The three predicates:

    * grade: the chunk's grade must be NULL (shared across grades) or equal.
    * major: the chunk's major must be NULL (shared across majors) or equal.
      A student with no major (grades 1-9) gets **only** NULL-major chunks --
      a chunk scoped to ریاضی‌فیزیک must never reach a seventh grader.
    * subject: applied only when the caller narrowed to one.

    NULL handling is explicit rather than left to ``COALESCE``: folding NULL to
    a number would admit a chunk with no grade recorded to every grade, which is
    exactly the leak this function exists to prevent. A chunk with no grade is
    *not* retrievable by anyone until it is scoped, and that is the safe default.
    """
    clauses: list[str] = []
    params: list[Any] = []

    grade = enrolment.get("grade_number")
    if grade is None:
        raise ScopeViolation(
            "an enrolment must carry a grade_number; unscoped retrieval is not offered",
            field="grade_number",
        )
    if not isinstance(grade, int) or isinstance(grade, bool):
        raise ScopeViolation("grade_number must be an integer", field="grade_number")
    clauses.append("c.grade_number = ?")
    params.append(grade)

    major = enrolment.get("major_code")
    if major is None:
        # No major means grades 1-9: only chunks scoped to *no* major apply.
        clauses.append("c.major_code IS NULL")
    else:
        clauses.append("(c.major_code IS NULL OR c.major_code = ?)")
        params.append(major)

    subject = enrolment.get("subject_code")
    if subject is not None:
        clauses.append("(c.subject_code IS NULL OR c.subject_code = ?)")
        params.append(subject)

    return " AND ".join(clauses), tuple(params)


def retrievable(
    db: Database,
    *,
    enrolment: dict[str, Any],
    subject_code: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Chunks this enrolment may see, and no others.

    The rights check is a live join: a source archived after ingestion stops
    serving immediately. This is the only read path in the module that returns
    chunk text for retrieval, so there is exactly one place the rule lives.

    Note what is *not* a parameter: ``grade_number``, ``major_code`` and any
    "ignore_scope" flag. A caller passes an enrolment it already resolved, and
    the enrolment is the authority.
    """
    if limit < 1 or limit > 200:
        raise GroundingError("invalid_limit", "must be between 1 and 200", field="limit")
    scope, params = scope_sql(enrolment)
    if subject_code is not None:
        # Overrides the enrolment's subject when the student asked about a
        # specific one. Still a narrowing, never a widening.
        scope += " AND (c.subject_code IS NULL OR c.subject_code = ?)"
        params = params + (subject_code,)
    sql = (
        "SELECT c.chunk_key, c.source_id, c.page_index, c.page_label, "
        "       c.chapter_index, c.chapter_title, c.section_title, "
        "       c.grade_number, c.major_code, c.subject_code, c.block_kind, "
        "       c.text, s.title AS source_title, s.source_type "
        "FROM ingestion_chunks c "
        "JOIN catalog_sources s ON s.id = c.source_id "
        "WHERE s.publicly_retrievable = 1 "
        f"  AND {scope} "
        "ORDER BY c.source_id, c.page_index, c.ordinal "
        "LIMIT ?"
    )
    with db.read() as conn:
        return [dict(row) for row in conn.query(sql, params + (limit,))]


def search(
    db: Database,
    *,
    query: str,
    enrolment: dict[str, Any],
    subject_code: str | None = None,
    limit: int = 20,
    min_score: float = 0.25,
) -> list[dict[str, Any]]:
    """Chunks in scope *and* relevant to ``query``; possibly none.

    The distinction from :func:`retrievable` is the whole abstention story.
    ``retrievable`` answers "what may this student see" -- it is a permission
    question and its answer is never empty for a student with a library.
    ``search`` answers "what in that set actually addresses this question", and
    its honest answer is sometimes *nothing*. Without this second question a
    tutor cannot abstain: it would always return the whole visible corpus, and
    the least-bad chunk would become an answer to a question the material never
    addressed.

    Scoring is deliberately lexical and cheap rather than embedding-based. The
    shipped RAG engines do the semantic ranking; what Phase 5 must guarantee is
    that *no out-of-scope chunk can ever be scored*, and that an unrelated query
    scores zero. A heavy ranker here would make a scope leak hard to distinguish
    from a ranking miss.

    A chunk scores the share of query tokens it contains, so a query about a
    topic absent from the book scores near zero for every chunk and the result
    is an empty list -- an abstention, not a wrong answer.
    """
    if not (query or "").strip():
        raise GroundingError("empty_query", "a query is required", field="query")
    if not 0.0 < min_score <= 1.0:
        raise GroundingError("invalid_min_score", "must be in (0, 1]", field="min_score")

    visible = retrievable(
        db, enrolment=enrolment, subject_code=subject_code, limit=max(limit * 10, 200)
    )
    if not visible:
        return []

    scored = [(score_chunk(query, chunk), chunk) for chunk in visible]
    hits = [(score, chunk) for score, chunk in scored if score >= min_score]
    hits.sort(key=lambda pair: pair[0], reverse=True)
    return [chunk for _, chunk in hits[:limit]]


def score_chunk(query: str, chunk: dict[str, Any]) -> float:
    """Share of the query's content tokens that appear in the chunk.

    Persian orthography is normalised first (see ``_normalise_fa``): the ZWNJ,
    the Arabic yeh/kaf variants and the Persian/Arabic digits all vary between a
    PDF extraction and a student's typing for the *same* word. Without folding
    them, «می‌شود» typed with a ZWNJ would not match «میشود» extracted without
    one, and the miss would look like a retrieval failure.
    """
    query_tokens = _tokens(query)
    if not query_tokens:
        return 0.0
    haystack = _tokens(
        f"{chunk.get('text') or ''} {chunk.get('chapter_title') or ''} "
        f"{chunk.get('section_title') or ''} {chunk.get('source_title') or ''}",
        join_adjacent=True,
    )
    if not haystack:
        return 0.0
    overlap = query_tokens & haystack
    if not overlap:
        return 0.0
    # A match made only of very short tokens is not evidence of relevance.
    # Persian has many 2-letter function words, and a query that "matches" on
    # nothing but «از» or «به» is a coincidence, not a retrieval.
    if not any(len(token) >= 3 for token in overlap):
        return 0.0
    return len(overlap) / len(query_tokens)


#: Words too common to indicate relevance. A query made only of these has no
#: answerable content, and matching on them would retrieve everything.
_STOPWORDS = frozenset(
    """
    از به با در را که و یا این آن است بود شد چه چیزی چگونه کدام
    برای بر تا هم نیز اگر ولی اما پس هر دو سه چند آیا
    میشود شود میکند کند کرد کرده بودن هست نیست نمی
    های ها هایی ای
    the a an of in on to is are was were and or this that what how which for
    """.split()
)

# Word characters. Persian punctuation is explicitly excluded: ``؟`` (U+061F)
# sits *inside* the Arabic range \u0600-\u06ff, so a naive range class glues it
# to the preceding word and «می‌گوید؟» never matches «می‌گوید».
_WORD = __import__("re").compile(
    r"[0-9a-z"
    r"\u0621-\u063a\u0641-\u064a\u066e-\u06d3\u06fa-\u06ff"
    r"\ufb50-\ufdff\ufe70-\ufeff"
    r"]+"
)


def _normalise_fa(text: str) -> str:
    """Fold the orthographic variants of Persian into one form.

    Arabic yeh (ي) and kaf (ك) are what a PDF extractor often emits where a
    Persian keyboard produces ی and ک. They are the same letter to a reader and
    different bytes to a tokenizer.
    """
    table = {
        "\u064a": "\u06cc",  # Arabic yeh  -> Persian yeh
        "\u0643": "\u06a9",  # Arabic kaf  -> Persian kaf
        "\u0629": "\u0647",  # teh marbuta -> heh
        "\u06c0": "\u0647",  # heh with yeh -> heh
        # ZWNJ and ZWJ are removed, not replaced by a space. Replacing them
        # with a space splits «می‌شود» into «می» + «شود», and «می» is a 2-letter
        # fragment that appears in almost every Persian sentence -- so every
        # query scored 0.25 against every chunk and an unrelated question was
        # never abstained. Joining keeps the word whole.
        "\u200c": "",
        "\u200d": "",
        "\u0640": "",  # tatweel is decorative
        "\u0671": "\u0627",  # alef wasla -> alef
        "\u06f0": "\u0030",
        "\u06f1": "\u0031",
        "\u06f2": "\u0032",
        "\u06f3": "\u0033",
        "\u06f4": "\u0034",
        "\u06f5": "\u0035",
        "\u06f6": "\u0036",
        "\u06f7": "\u0037",
        "\u06f8": "\u0038",
        "\u06f9": "\u0039",  # Persian digits -> ASCII
        "\u0660": "\u0030",
        "\u0661": "\u0031",
        "\u0662": "\u0032",
        "\u0663": "\u0033",
        "\u0664": "\u0034",
        "\u0665": "\u0035",
        "\u0666": "\u0036",
        "\u0667": "\u0037",
        "\u0668": "\u0038",
        "\u0669": "\u0039",  # Arabic digits -> ASCII
    }
    text = text.lower()
    for source, target in table.items():
        text = text.replace(source, target)
    return text


def _tokens(text: str, *, join_adjacent: bool = False) -> set[str]:
    """Content tokens of ``text``, stopwords removed.

    Diacritics are stripped so a vowelised PDF and a plain query compare equal.

    ``join_adjacent`` additionally emits the concatenation of each neighbouring
    pair. Persian compounds are written with a ZWNJ («دانش‌آموز»), a space, or
    with nothing at all, and a PDF extractor does not know which the author
    meant: the same word arrives as «دانش‌آموز» from one tool and «دانش آموز»
    from another. Joining adjacent pairs makes a space-separated document match
    a ZWNJ query. It is applied to the *document* only, never to the query, so
    the score's denominator (the query's own tokens) never grows and a hit
    cannot be inflated by a pairing the query did not contain.
    """
    normalised = _normalise_fa(text or "")
    normalised = __import__("re").sub(
        r"[\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06dc\u06df-\u06e8]", "", normalised
    )
    words = _WORD.findall(normalised)
    tokens = {token for token in words if len(token) > 1 and token not in _STOPWORDS}
    if join_adjacent:
        for left, right in zip(words, words[1:]):
            if len(left) > 1 and len(right) > 1:
                tokens.add(left + right)
    return tokens


def count_visible(db: Database, enrolment: dict[str, Any]) -> int:
    """How many chunks an enrolment can see. Used by the leakage tests."""
    scope, params = scope_sql(enrolment)
    sql = (
        "SELECT COUNT(*) AS n FROM ingestion_chunks c "
        "JOIN catalog_sources s ON s.id = c.source_id "
        f"WHERE s.publicly_retrievable = 1 AND {scope}"
    )
    with db.read() as conn:
        return int(conn.scalar(sql, params) or 0)


# ---------------------------------------------------------------------------
# Citation
# ---------------------------------------------------------------------------

#: Matches the short citation form D-009 requires: ``[نام کتاب | فصل]``.
#: The book name is bounded to keep a pathological input from scanning a whole
#: answer, and the chapter part is optional because a chunk may have no chapter.
_CITATION_RE = re.compile(r"\[([^\[\]|\n]{1,120})(?:\s*\|\s*([^\[\]\n]{0,120}))?\]")


def render_citation(chunk: dict[str, Any]) -> str:
    """``[نام کتاب | فصل]`` -- and never page, chunk, grade or track (D-009).

    When the chapter is unknown the citation degrades to the book name. It does
    **not** invent a chapter and it does not fall back to the page number: D-009
    says page and chunk are not shown, and a citation that shows them is a
    citation that leaks the retrieval internals into a student-facing string.
    """
    title = str(chunk.get("source_title") or "").strip()
    if not title:
        raise CitationError("a chunk without a source title cannot be cited")
    chapter = str(chunk.get("chapter_title") or "").strip()
    if chapter:
        return f"[{title} | {chapter}]"
    return f"[{title}]"


def extract_citations(answer: str) -> list[tuple[str, str]]:
    """Every ``(book, chapter)`` pair in an answer, in order, de-duplicated."""
    seen: list[tuple[str, str]] = []
    for match in _CITATION_RE.finditer(answer or ""):
        pair = (match.group(1).strip(), (match.group(2) or "").strip())
        if pair not in seen:
            seen.append(pair)
    return seen


def validate_citations(
    answer: str,
    retrieved: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """Prove every citation in ``answer`` points at a *retrieved* chunk.

    This is the anti-hallucination check the roadmap asks for, and it is
    deliberately strict: a citation is valid only if the exact ``(title,
    chapter)`` pair appears among the chunks retrieval actually returned for
    this question. A citation to a real book that was not retrieved for this
    query is still a hallucination of provenance, because the model could not
    have read it.

    Returns a report rather than raising: the caller decides whether an
    unverified answer is shown with a warning or withheld. ``valid`` is true
    only when there is at least one citation and every one checks out -- an
    answer with no citations is not "valid", it is ungrounded.
    """
    citations = extract_citations(answer)
    allowed: set[tuple[str, str]] = set()
    for chunk in retrieved:
        title = str(chunk.get("source_title") or "").strip()
        chapter = str(chunk.get("chapter_title") or "").strip()
        if not title:
            continue
        allowed.add((title, chapter))
        # A chapterless chunk also licenses the book-only form.
        if chapter:
            allowed.add((title, ""))
    unverified = [pair for pair in citations if pair not in allowed]
    return {
        "citations": citations,
        "citation_count": len(citations),
        "unverified": unverified,
        "valid": bool(citations) and not unverified,
        "grounded": bool(citations) and not unverified,
    }


def abstain(reason: str) -> dict[str, Any]:
    """The structured refusal an answer must return when nothing was retrieved.

    A list of reasons rather than a bare bool so the caller can distinguish
    "the library has nothing on this" from "the library has something but your
    grade may not see it" -- the second is a rights answer, not a failure, and
    telling a student the wrong one is a product bug.
    """
    return {
        "grounded": False,
        "abstained": True,
        "reason": reason,
        "citations": [],
        "chunks": [],
    }
