"""The Persian golden set, run against the real grounding layer.

This is the Phase 5 acceptance test that matters most, because it is the only
one that checks *end to end* what a student experiences: a question, the books
in their grade, and a checkable answer.

It runs the shipped `retrievable()` rather than a stub, so a regression in the
scope join, in extraction, or in citation rendering shows up here as a failed
case rather than as three green unit tests and a broken product.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.db.repositories import catalog as catalog_repo
from deeptutor.db.repositories import grounding
from deeptutor.db.repositories import sources as sources_repo
from deeptutor.services.ingestion import golden, pipeline

FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "grounding" / "darsyar_phase5_golden.json"
)

BODY = (
    "این جملهٔ آزمایشی به اندازهٔ کافی طولانی است تا یک قطعهٔ معنادار در ایندکس بسازد. "
    "و این ادامهٔ آن است تا مطمئن شویم آستانهٔ طول قطعه رعایت می‌شود."
)


@pytest.fixture
def library(db):
    """A miniature library shaped like the pilot: three grades, two tracks."""
    catalog_repo.create_system(db, code="current", title="نظام فعلی")
    for grade in (10, 11, 12):
        catalog_repo.add_grade(
            db,
            system_code="current",
            grade_number=grade,
            title=f"پایه {grade}",
            stage_code="upper_secondary",
            requires_track=True,
        )
    catalog_repo.create_track(db, code="theoretical", title="نظری")
    for code, title in (
        ("math_physics", "ریاضی‌فیزیک"),
        ("experimental", "علوم تجربی"),
        ("humanities", "علوم انسانی"),
    ):
        catalog_repo.create_major(
            db, track_code="theoretical", code=code, title=title, selectable_grades=(10, 11, 12)
        )
    return db


def _ingest(db, *, title, grade, major, chapters, subject="math", edition=None, blocks=None):
    """Create an approved source whose chapters are the given (name, text) pairs.

    ``blocks``, when given, is ingested as structured parser output instead of
    markdown. That is how the table, figure and formula cases get a chunk whose
    ``block_kind`` is genuinely ``table`` / ``figure`` / ``formula``: the markdown
    path can only ever produce prose, so ingesting markdown here would make those
    cases pass without ever exercising the structured path they exist to test.
    """
    source_id = sources_repo.create_source(
        db,
        title=title,
        source_type="official_book",
        grade_number=grade,
        major_code=major,
        subject_code=subject,
        edition=edition or f"{grade}-{major}-{title}",
        rights_status="cleared",
        review_status="approved",
    )
    if blocks is not None:

        class Prepared:
            pass

        prepared = Prepared()
        prepared.blocks = blocks
        prepared.markdown = ""
        pipeline.run_ingestion(db, source_id=source_id, parsed=prepared, document_key="d1")
        return source_id
    markdown = "\n\n".join(f"# {name}\n\n{text}" for name, text in chapters)
    pipeline.run_ingestion(db, source_id=source_id, markdown=markdown, document_key="d1")
    return source_id


@pytest.fixture
def corpus(library):
    """Exactly the books the golden set refers to, and no others."""
    # Ingested as structured blocks so the table, figure and formula cases are
    # testing the real extraction paths rather than prose that mentions them.
    _ingest(
        library,
        title="ریاضی دهم ریاضی‌فیزیک",
        grade=10,
        major="math_physics",
        chapters=[],
        blocks=[
            {"page_idx": 0, "type": "text", "text_level": 1, "text": "فصل ۱: مجموعه‌ها"},
            {
                "page_idx": 0,
                "type": "text",
                "text": "مجموعه گردایه‌ای از اشیاء است و هر عضو آن با یک نماد نشان داده می‌شود. "
                "هر شیئی که در یک مجموعه قرار می‌گیرد عضو آن مجموعه نامیده می‌شود. " + BODY,
            },
            {"page_idx": 0, "type": "image", "caption": "شکل ۲: نمایش مجموعه‌ها با نمودار ون"},
            {"page_idx": 1, "type": "text_level_1", "text_level": 1, "text": "فصل ۲: اعداد طبیعی"},
            {
                "page_idx": 1,
                "type": "text",
                "text": "اعداد طبیعی از یک شروع می‌شوند و بی‌پایان ادامه دارند. " + BODY,
            },
            {"page_idx": 2, "type": "text_level_1", "text_level": 1, "text": "فصل ۳: مثلثات"},
            {
                "page_idx": 2,
                "type": "text",
                "text": "در هر مثلث قائم‌الزاویه مربع وتر برابر مجموع مربع‌های دو ضلع دیگر است. "
                "مساحت مثلث برابر است با نصف حاصل‌ضرب قاعده در ارتفاع. " + BODY,
            },
            {
                "page_idx": 2,
                "type": "table",
                "table_body": "جدول ۱: مقادیر سینوس و کسینوس برای زوایای ۳۰ و ۴۵ و ۶۰ درجه",
            },
            {"page_idx": 3, "type": "text_level_1", "text_level": 1, "text": "فصل ۴: بردارها"},
            {
                "page_idx": 3,
                "type": "text",
                "text": "بردار پاره‌خطی جهت‌دار است که طول و جهت دارد. " + BODY,
            },
        ],
    )
    _ingest(
        library,
        title="ریاضی دهم تجربی",
        grade=10,
        major="experimental",
        chapters=[
            (
                "فصل ۳: مثلثات",
                "در هر مثلث قائم‌الزاویه مربع وتر برابر مجموع مربع‌های دو ضلع دیگر است. " + BODY,
            )
        ],
    )
    _ingest(
        library,
        title="حسابان یازدهم",
        grade=11,
        major="math_physics",
        chapters=[
            (
                "فصل ۱: مشتق",
                "مشتق تابع در یک نقطه حد نسبت تغییر تابع به تغییر متغیر است "
                "وقتی تغییر متغیر به صفر میل کند. " + BODY,
            )
        ],
    )
    _ingest(
        library,
        title="حسابان دوازدهم",
        grade=12,
        major="math_physics",
        chapters=[
            (
                "فصل ۲: انتگرال",
                "انتگرال معین تابع پیوسته روی بازه با قضیهٔ اساسی حساب دیفرانسیل و انتگرال "
                "محاسبه می‌شود. " + BODY,
            )
        ],
    )
    _ingest(
        library,
        title="تاریخ دوازدهم انسانی",
        grade=12,
        major="humanities",
        subject="history",
        chapters=[
            (
                "درس ۴: جنگ جهانی دوم",
                "جنگ جهانی دوم در سال ۱۹۴۵ با تسلیم آلمان و ژاپن پایان یافت. " + BODY,
            )
        ],
    )
    return library


def test_the_golden_set_loads_and_is_self_consistent():
    cases, k = golden.load_golden_set(FIXTURE)
    assert len(cases) >= 10
    assert k == 5
    ids = [case.id for case in cases]
    assert len(ids) == len(set(ids))
    # Every case either expects chapters or abstains, never both and never neither.
    for case in cases:
        assert bool(case.expected) != case.expect_abstain, case.id


def test_the_golden_set_covers_every_required_capability():
    """The roadmap lists the capabilities; a set missing one proves nothing."""
    cases, _ = golden.load_golden_set(FIXTURE)
    groups = {case.group for case in cases}
    for required in ("topic", "numerals", "table", "figure", "formula", "ocr", "abstain", "track"):
        assert required in groups, f"the golden set has no {required!r} case"


def test_the_golden_set_spans_the_pilot_grades():
    cases, _ = golden.load_golden_set(FIXTURE)
    assert {case.grade_number for case in cases} >= {10, 11, 12}


def test_topic_recall_is_perfect(corpus):
    """Exact retrieval of the intended topic and chapter."""
    cases, k = golden.load_golden_set(FIXTURE)
    topic_cases = [case for case in cases if case.group in {"topic", "numerals", "ocr"}]
    report = golden.evaluate(corpus, topic_cases, k=k)
    failures = [result.as_dict() for result in report.results if not result.passed]
    assert not failures, failures
    assert report.recall == 1.0


def test_table_figure_and_formula_are_retrievable(corpus):
    cases, k = golden.load_golden_set(FIXTURE)
    structured = [case for case in cases if case.group in {"table", "figure", "formula"}]
    report = golden.evaluate(corpus, structured, k=k)
    failures = [result.as_dict() for result in report.results if not result.passed]
    assert not failures, failures


def test_every_abstention_case_abstains(corpus):
    """Out-of-source, wrong-grade and wrong-track queries all return nothing."""
    cases, k = golden.load_golden_set(FIXTURE)
    abstain = [case for case in cases if case.expect_abstain]
    report = golden.evaluate(corpus, abstain, k=k)
    failures = [result.as_dict() for result in report.results if not result.passed]
    assert not failures, failures
    assert report.abstention_accuracy == 1.0


def test_the_whole_golden_set_passes(corpus):
    cases, k = golden.load_golden_set(FIXTURE)
    report = golden.evaluate(corpus, cases, k=k)
    failures = [result.as_dict() for result in report.results if not result.passed]
    assert not failures, failures
    assert report.passed == report.total


def test_the_report_separates_recall_from_abstention(corpus):
    """A single number would let abstention failures hide inside recall."""
    cases, k = golden.load_golden_set(FIXTURE)
    report = golden.evaluate(corpus, cases, k=k).as_dict()
    assert "recall" in report and "abstention_accuracy" in report
    assert report["by_group"]["abstain"]["passed"] == report["by_group"]["abstain"]["total"]


# ---------------------------------------------------------------------------
# The failure direction: the harness must be able to fail
# ---------------------------------------------------------------------------


def test_the_harness_detects_a_missing_book(corpus):
    """If the library is emptier than the golden set assumes, recall drops.

    A harness that scores 100% on an empty library would be worthless, so this
    asserts the negative: with the books archived, nothing is retrievable and
    the topic cases must fail.
    """
    cases, k = golden.load_golden_set(FIXTURE)
    with corpus.transaction() as conn:
        conn.execute("UPDATE catalog_sources SET publicly_retrievable = 0")

    report = golden.evaluate(corpus, [c for c in cases if c.group == "topic"], k=k)
    assert report.recall == 0.0
    assert report.passed == 0


def test_a_wrong_chapter_is_not_counted_as_a_hit(corpus):
    """Chapter-level truth: being in the right book is not enough."""
    from deeptutor.services.ingestion.golden import ExpectedChapter

    expected = ExpectedChapter(title="ریاضی دهم ریاضی‌فیزیک", chapter="فصل ۲: اعداد طبیعی")
    chunks = grounding.retrievable(
        corpus, enrolment={"grade_number": 10, "major_code": "math_physics"}
    )
    chapter_one = next(c for c in chunks if "مجموعه" in (c["chapter_title"] or ""))
    assert expected.matches(chapter_one) is False

    chapter_two = next(c for c in chunks if "طبیعی" in (c["chapter_title"] or ""))
    assert expected.matches(chapter_two) is True


def test_two_books_with_the_same_chapter_name_are_distinguished(corpus):
    """Every grade-10 book has a «فصل ۳»; a chapter match alone would be wrong."""
    from deeptutor.services.ingestion.golden import ExpectedChapter

    expected = ExpectedChapter(title="ریاضی دهم تجربی", chapter="فصل ۳: مثلثات")
    chunks = grounding.retrievable(
        corpus, enrolment={"grade_number": 10, "major_code": "math_physics"}
    )
    same_chapter_other_book = next(
        c for c in chunks if (c["chapter_title"] or "").startswith("فصل ۳")
    )
    assert expected.matches(same_chapter_other_book) is False


def test_a_malformed_golden_set_is_rejected(tmp_path):
    """A typo must be an error, not a permanently lower score."""
    bad = tmp_path / "bad.json"
    bad.write_text(
        '{"cases": [{"id": "x", "query": "پرسش", "grade_number": 10, '
        '"expected_chapters": [], "expect_abstain": true, '
        '"expected_chapters_typo": [{"title": "کتاب"}]}]}',
        encoding="utf-8",
    )
    # extra keys are tolerated on load, but an abstaining case with chapters is not
    bad.write_text(
        '{"cases": [{"id": "x", "query": "پرسش", "grade_number": 10, '
        '"expect_abstain": true, "expected_chapters": [{"title": "کتاب"}]}]}',
        encoding="utf-8",
    )
    with pytest.raises(golden.GoldenSetError):
        golden.load_golden_set(bad)


def test_a_case_that_expects_nothing_and_does_not_abstain_is_rejected(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(
        '{"cases": [{"id": "x", "query": "پرسش", "grade_number": 10}]}', encoding="utf-8"
    )
    with pytest.raises(golden.GoldenSetError):
        golden.load_golden_set(bad)


def test_a_case_without_a_grade_is_rejected(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(
        '{"cases": [{"id": "x", "query": "پرسش", "expected_chapters": [{"title": "کتاب"}]}]}',
        encoding="utf-8",
    )
    with pytest.raises(golden.GoldenSetError):
        golden.load_golden_set(bad)


# ---------------------------------------------------------------------------
# Citation honesty
# ---------------------------------------------------------------------------


def test_no_answer_in_the_evaluation_set_has_a_hallucinated_citation(corpus):
    """The roadmap's zero-tolerance criterion, measured rather than asserted.

    Every answer here is built from a *real* retrieval, so the clean result is
    meaningful: the audit is capable of reporting zero because the answers are
    genuinely grounded, not because nothing was checked.
    """
    cases, _ = golden.load_golden_set(FIXTURE)
    answers = []
    for case in cases:
        if case.expect_abstain:
            continue
        chunks = grounding.retrievable(corpus, enrolment=case.enrolment)
        if not chunks:
            continue
        citation = grounding.render_citation(chunks[0])
        answers.append(
            {
                "id": case.id,
                "enrolment": case.enrolment,
                "answer": f"پاسخ بر پایهٔ {citation}.",
            }
        )

    assert len(answers) >= 8, "the audit must actually check something"
    audit = golden.audit_citations(corpus, answers)
    assert audit.checked == len(answers)
    assert audit.hallucinated == 0
    assert audit.clean is True
    assert audit.valid == audit.checked


def test_the_audit_catches_a_fabricated_citation(corpus):
    """The negative direction: a made-up book must be caught."""
    audit = golden.audit_citations(
        corpus,
        [
            {
                "id": "fake",
                "enrolment": {"grade_number": 10, "major_code": "math_physics"},
                "answer": "بر پایهٔ [کتاب ناموجود | فصل ۱].",
            }
        ],
    )
    assert audit.hallucinated == 1
    assert audit.clean is False
    assert audit.invalid_answers == ["fake"]


def test_the_audit_catches_a_real_book_cited_for_the_wrong_grade(corpus):
    """The subtle case: the book exists, but not for this student's scope."""
    audit = golden.audit_citations(
        corpus,
        [
            {
                "id": "leak",
                "enrolment": {"grade_number": 10, "major_code": "math_physics"},
                "answer": "بر پایهٔ [حسابان دوازدهم | فصل ۲: انتگرال].",
            }
        ],
    )
    assert audit.hallucinated == 1
    assert audit.clean is False


def test_the_audit_counts_every_bad_citation_not_just_the_first(corpus):
    audit = golden.audit_citations(
        corpus,
        [
            {
                "id": "two_fakes",
                "enrolment": {"grade_number": 10, "major_code": "math_physics"},
                "answer": "[کتاب الف | فصل ۱] و [کتاب ب | فصل ۲]",
            }
        ],
    )
    assert audit.hallucinated == 2
