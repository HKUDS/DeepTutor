"""Persian golden-set evaluation for the Phase 5 grounded tutor.

Why a separate model from ``EvalCase``
--------------------------------------
``EvalCase`` matches against verbatim gold *passages* and forbids extra fields.
Phase 5's acceptance criteria are stated in terms of **chapter** ("exact
retrieval of the intended topic and chapter") and in terms of **abstention**
("an out-of-source query abstains correctly"). Neither is expressible in a
passage-only schema: a chapter is a scope assertion, and abstention is the
absence of a result. So the golden set has its own model and this module
adapts it to the shipped metrics rather than bending them.

How a case is scored
--------------------
Each case declares the chapters that *should* be retrieved for its query. The
runner retrieves under the case's enrolment, then scores:

* **recall** — of the expected chapters, how many appear in the top ``k``. A
  case passes at recall 1.0: finding one of two intended chapters is a bad
  answer to a student, not half a good one.
* **abstention** — for a case with no expected chapters, passing means
  retrieval returned nothing. Returning *something* is a failure, however
  relevant it looks, because the whole point is that the material is absent.

The aggregate is reported per group as well as overall, because "92% recall"
hides a set that is perfect on topics and broken on tables.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from deeptutor.services.rag.eval.matching import normalize_text

DEFAULT_K = 5


class GoldenSetError(ValueError):
    """The golden set is malformed, or a case asserts something contradictory."""


@dataclass(frozen=True)
class ExpectedChapter:
    """The book and chapter a query should retrieve, plus a verbatim excerpt."""

    title: str
    chapter: str = ""
    gold: str = ""

    def matches(self, chunk: Mapping[str, Any]) -> bool:
        """True when ``chunk`` is this chapter.

        The book is compared exactly (after normalisation) because two different
        books with the same chapter name is the normal case, not the exception:
        every grade-10 book has a «فصل ۱». Comparing chapters alone would score a
        hit for the wrong book.
        """
        if normalize_text(chunk.get("source_title") or "") != normalize_text(self.title):
            return False
        if not self.chapter:
            return True
        return normalize_text(chunk.get("chapter_title") or "") == normalize_text(self.chapter)


@dataclass(frozen=True)
class GoldenCase:
    id: str
    query: str
    grade_number: int
    major_code: str | None
    expected: tuple[ExpectedChapter, ...] = ()
    group: str = "topic"
    expect_abstain: bool = False
    notes: str = ""
    subject_code: str | None = None

    @property
    def enrolment(self) -> dict[str, Any]:
        return {"grade_number": self.grade_number, "major_code": self.major_code}


@dataclass
class CaseResult:
    case_id: str
    group: str
    passed: bool
    recalled: int
    expected: int
    abstained: bool
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "group": self.group,
            "passed": self.passed,
            "recalled": self.recalled,
            "expected": self.expected,
            "abstained": self.abstained,
            "detail": self.detail,
        }


@dataclass
class GoldenReport:
    results: list[CaseResult] = field(default_factory=list)
    k: int = DEFAULT_K

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for result in self.results if result.passed)

    @property
    def recall(self) -> float:
        """Mean recall over cases that expect something. Abstention cases excluded.

        Folding abstention into recall would let a system that abstains on
        everything score 1.0 on the abstention cases and 0.0 on the rest, which
        averages to a number that describes neither behaviour.
        """
        scored = [result for result in self.results if result.expected]
        if not scored:
            return 0.0
        return sum(result.recalled / result.expected for result in scored) / len(scored)

    @property
    def abstention_accuracy(self) -> float:
        abstain_cases = [result for result in self.results if result.expected == 0]
        if not abstain_cases:
            return 1.0
        return sum(1 for result in abstain_cases if result.passed) / len(abstain_cases)

    def by_group(self) -> dict[str, dict[str, Any]]:
        groups: dict[str, list[CaseResult]] = {}
        for result in self.results:
            groups.setdefault(result.group, []).append(result)
        return {
            group: {
                "total": len(items),
                "passed": sum(1 for item in items if item.passed),
                "failed_ids": [item.case_id for item in items if not item.passed],
            }
            for group, items in sorted(groups.items())
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "k": self.k,
            "total": self.total,
            "passed": self.passed,
            "recall": round(self.recall, 4),
            "abstention_accuracy": round(self.abstention_accuracy, 4),
            "by_group": self.by_group(),
            "failures": [result.as_dict() for result in self.results if not result.passed],
        }


def load_golden_set(path: Path | str) -> tuple[list[GoldenCase], int]:
    """Read a golden set from JSON, validating as it goes.

    Validation is strict on purpose: a golden set with a typo in a chapter name
    silently lowers the score forever, and nobody re-reads a fixture that
    "just works less well than expected".
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    raw_cases = data.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise GoldenSetError("the golden set has no cases")

    cases: list[GoldenCase] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_cases):
        if not isinstance(raw, Mapping):
            raise GoldenSetError(f"case {index} is not an object")
        case_id = str(raw.get("id") or f"q{index + 1}")
        if case_id in seen:
            raise GoldenSetError(f"duplicate case id: {case_id}")
        seen.add(case_id)

        query = str(raw.get("query") or "").strip()
        if not query:
            raise GoldenSetError(f"case {case_id} has no query")

        grade = raw.get("grade_number")
        if not isinstance(grade, int) or grade < 1:
            raise GoldenSetError(f"case {case_id} has no valid grade_number")

        expected = tuple(
            ExpectedChapter(
                title=str(item.get("title") or "").strip(),
                chapter=str(item.get("chapter") or "").strip(),
                gold=str(item.get("gold") or "").strip(),
            )
            for item in raw.get("expected_chapters") or ()
        )
        for chapter in expected:
            if not chapter.title:
                raise GoldenSetError(f"case {case_id} has an expected chapter with no title")

        expect_abstain = bool(raw.get("expect_abstain", False))
        if expect_abstain and expected:
            # Otherwise the case cannot pass: it demands both a result and none.
            raise GoldenSetError(
                f"case {case_id} expects abstention but also lists expected chapters"
            )
        if not expect_abstain and not expected:
            raise GoldenSetError(f"case {case_id} expects nothing and does not abstain")

        cases.append(
            GoldenCase(
                id=case_id,
                query=query,
                grade_number=grade,
                major_code=raw.get("major_code"),
                subject_code=raw.get("subject_code"),
                expected=expected,
                group=str(raw.get("group") or "topic"),
                expect_abstain=expect_abstain,
                notes=str(raw.get("notes") or ""),
            )
        )
    return cases, int(data.get("k") or DEFAULT_K)


def run_case(db: Any, case: GoldenCase, *, k: int = DEFAULT_K, retrieve=None) -> CaseResult:
    """Search for one case and score it.

    ``search`` rather than ``retrievable``: the latter lists the whole visible
    corpus, so it can never abstain and every out-of-source case would "fail"
    by returning the library. Search asks the second question -- is any of it
    relevant -- and that is the one abstention depends on.
    """
    from deeptutor.db.repositories import grounding

    retrieve = retrieve or grounding.search
    chunks = list(retrieve(db, query=case.query, enrolment=case.enrolment, limit=k))

    if case.expect_abstain:
        # A scope-correct system returns nothing for out-of-source material.
        # Anything returned here means either the scope filter leaked or the
        # library contains the material, and both must fail loudly.
        passed = not chunks
        return CaseResult(
            case_id=case.id,
            group=case.group,
            passed=passed,
            recalled=0,
            expected=0,
            abstained=not chunks,
            detail="" if passed else f"returned {len(chunks)} chunks for an out-of-source query",
        )

    # ``search`` already returns best-first, so the top-k is just the head.
    ranked = chunks[:k]

    recalled = 0
    for expected in case.expected:
        if any(expected.matches(chunk) for chunk in ranked):
            recalled += 1

    return CaseResult(
        case_id=case.id,
        group=case.group,
        passed=recalled == len(case.expected),
        recalled=recalled,
        expected=len(case.expected),
        abstained=not chunks,
        detail=""
        if recalled == len(case.expected)
        else f"recalled {recalled}/{len(case.expected)} expected chapters",
    )


def evaluate(db: Any, cases: Iterable[GoldenCase], *, k: int = DEFAULT_K) -> GoldenReport:
    report = GoldenReport(k=k)
    for case in cases:
        report.results.append(run_case(db, case, k=k))
    return report


@dataclass
class CitationAudit:
    """Citation-level honesty across an answer set.

    The roadmap's criterion is "zero hallucinated citations in the evaluation
    set". That is a count, not a rate: one fabricated citation in a hundred
    answers is still a fabricated citation, and a percentage makes it look like
    rounding.
    """

    checked: int = 0
    valid: int = 0
    hallucinated: int = 0
    invalid_answers: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return self.hallucinated == 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "checked": self.checked,
            "valid": self.valid,
            "hallucinated": self.hallucinated,
            "clean": self.clean,
            "invalid_answers": self.invalid_answers,
        }


def audit_citations(
    db: Any, answers: Sequence[Mapping[str, Any]], *, retrieve=None
) -> CitationAudit:
    """Validate every citation in ``answers`` against what retrieval returns.

    Each answer supplies its own ``enrolment``, so an answer produced for one
    grade is checked against that grade's corpus. Auditing everything against a
    single scope would hide a leak in exactly the direction it matters.
    """
    from deeptutor.db.repositories import grounding

    retrieve = retrieve or grounding.retrievable
    audit = CitationAudit()
    cache: dict[tuple[Any, ...], list[dict[str, Any]]] = {}

    for answer in answers:
        enrolment = answer.get("enrolment") or {}
        key = (enrolment.get("grade_number"), enrolment.get("major_code"))
        if key not in cache:
            cache[key] = list(retrieve(db, enrolment=enrolment))
        chunks = cache[key]

        report = grounding.validate_citations(str(answer.get("answer") or ""), chunks)
        audit.checked += 1
        audit.hallucinated += len(report["unverified"])
        if report["valid"]:
            audit.valid += 1
        else:
            audit.invalid_answers.append(str(answer.get("id") or ""))
    return audit
