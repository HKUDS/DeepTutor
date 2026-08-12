# GuruAI MVP

This branch is the first safe vertical slice of GuruAI on top of DeepTutor. It does not delete or disable existing DeepTutor capabilities.

## Product

GuruAI lets a learner upload a syllabus PDF or past-paper PDF, ask in Sinhala or English, and receive a grounded explanation with page citations. Practice Mode uses a linked marking scheme to award method marks and provide revision feedback.

## New package

- `deeptutor/guruai/schemas.py`: validated bilingual answer and grading contracts.
- `deeptutor/guruai/prompts.py`: grounding and marking rules.

## Next implementation order

1. Connect uploaded PDFs to the existing DeepTutor knowledge-base ingestion flow.
2. Preserve page metadata and add `grade`, `subject`, `medium`, `topic`, `question_no`, and `linked_marking_scheme_id` payloads.
3. Add a `guruai_explain` capability that calls existing retrieval and returns `GuruAnswer`.
4. Add a `guruai_practice_grade` capability that retrieves the linked marking scheme and returns `GradeResult`.
5. Add a new browser route and UI shell after the backend contracts pass tests.
6. Add Sinhala speech and opt-in browser-only focus check last.

## Boundaries

- Local prototype first.
- No authentication or shared deployment work in this slice.
- Co-Writer, Research, Book authoring, Notebooks, and Admin settings stay intact.
- DeepTutor and LiquidGlass attribution must remain visible in the README, technical document, and UI footer.
