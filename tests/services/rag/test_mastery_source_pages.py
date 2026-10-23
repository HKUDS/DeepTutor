"""Small proofs of page identity, selected-corpus retrieval and source-gated mastery."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from llama_index.core import VectorStoreIndex
from llama_index.core.embeddings import MockEmbedding
from llama_index.core.schema import TextNode
import pymupdf
import pytest

from deeptutor.learning import lesson_evidence as lessons
from deeptutor.learning.models import (
    KnowledgePoint,
    LearnerProfile,
    LearningModule,
    LearningProgress,
    PendingQuestion,
    TopicMetadata,
    TopicSource,
    TopicSourceKind,
)
from deeptutor.learning.service import LearningService, MasteryInteractionError
from deeptutor.learning.storage import LearningStore
from deeptutor.services.rag.source_pages import (
    SourcePageError,
    SourceRef,
    build_pdf_documents,
    persist_page_catalog,
    render_source_page,
    source_digest,
)


@pytest.mark.asyncio
async def test_successful_explicit_preparation_supersedes_same_turn_failure(material, monkeypatch):
    from unittest.mock import AsyncMock

    from deeptutor.capabilities.mastery.pipeline import MasteryLoopPipeline
    from deeptutor.capabilities.mastery.tools import MasteryPrepareLessonTool
    from deeptutor.core.context import UnifiedContext
    from deeptutor.runtime.stream_bus import StreamBus

    _install_preparation(material, monkeypatch)
    actual_prepare = lessons.prepare_lesson
    automatic = AsyncMock(side_effect=lessons.LessonUnavailable("Initial coverage incomplete"))
    monkeypatch.setattr(lessons, "prepare_lesson", automatic)
    monkeypatch.setattr("deeptutor.learning.storage.LearningStore", lambda: material.store)
    monkeypatch.setattr(
        "deeptutor.capabilities.mastery.tools._new_service", lambda: LearningService(material.store)
    )
    monkeypatch.setattr("deeptutor.services.llm.config.get_llm_config", lambda: material.config)
    pipeline = MasteryLoopPipeline(language="en")
    pipeline.llm_config = material.config
    context = UnifiedContext(user_message="Continue teaching", metadata={"mastery_path_id": "path"})
    messages = [{"role": "user", "content": context.user_message}]
    stream = StreamBus()
    assert await pipeline.prepare_model_request(context, stream, messages) == []
    assert "not prepared" in messages[-1]["content"]
    automatic.assert_not_awaited()
    before = material.store.load("path").model_dump()
    with pytest.raises(MasteryInteractionError):
        LearningService(material.store).register_question(
            "path",
            PendingQuestion(
                question_id="unsupported", knowledge_point_id="kp", expected_answer="lipids"
            ),
        )
    assert material.store.load("path").model_dump() == before
    failed = await MasteryPrepareLessonTool().execute(
        knowledge_point_id="kp", _mastery_path_id="path"
    )
    assert not failed.success and "Initial coverage incomplete" in failed.content
    assert await pipeline.prepare_model_request(context, stream, messages) == []
    assert automatic.await_count == 1  # The explicit tool attempt, not the hook.
    monkeypatch.setattr(lessons, "prepare_lesson", actual_prepare)
    prepared = await MasteryPrepareLessonTool().execute(
        knowledge_point_id="kp", _mastery_path_id="path"
    )
    assert prepared.success and "VERIFIED ACTIVE LESSON" in prepared.content
    assert await pipeline.prepare_model_request(context, stream, messages)
    assert automatic.await_count == 1
    assert len([m for m in messages if m.get("_lesson_packet")]) == 1
    assert "VERIFIED ACTIVE LESSON" in messages[-1]["content"]
    assert not material.store.load("path").mastery_levels


@pytest.mark.asyncio
@pytest.mark.parametrize("language, expected", [("en", "Finding sources"), ("zh", "查找资料")])
async def test_explicit_preparation_reports_localized_stages_on_the_owned_stream(
    material, monkeypatch, language, expected
):
    from deeptutor.capabilities.mastery.tools import MasteryPrepareLessonTool
    from deeptutor.runtime.stream_bus import StreamBus, register_bus, unregister_bus

    _install_preparation(material, monkeypatch)
    monkeypatch.setattr(
        "deeptutor.capabilities.mastery.tools._new_service", lambda: LearningService(material.store)
    )
    monkeypatch.setattr("deeptutor.services.llm.config.get_llm_config", lambda: material.config)
    stream = StreamBus()
    register_bus("preparing", stream)
    try:
        result = await MasteryPrepareLessonTool().execute(
            _mastery_path_id="path",
            knowledge_point_id="kp",
            _turn_id="preparing",
            _language=language,
        )
        await stream.close()
        events = [event async for event in stream.subscribe()]
        assert result.success, result.content
        assert any(expected in event.content for event in events)
        assert not any(event.type.value == "content" for event in events)
    finally:
        unregister_bus("preparing")


@pytest.fixture
def material(tmp_path, monkeypatch):
    raw = tmp_path / "kb" / "raw"
    raw.mkdir(parents=True)
    path = raw / "lesson.pdf"
    pdf = pymupdf.open()
    for number in range(72):
        page = pdf.new_page(width=300, height=200)
        page.insert_text(
            (12, 20),
            "Membrane lipids form a bilayer." if number == 70 else f"Unrelated section {number}.",
        )
        if number == 70:
            page.draw_rect(pymupdf.Rect(20, 50, 100, 130), color=(1, 0, 0), fill=(1, 0, 0))
            page.draw_circle(pymupdf.Point(230, 90), 32, color=(0, 0, 1), fill=(0, 0, 1))
    pdf.save(path)
    pdf.close()
    parsed = SimpleNamespace(
        blocks=[],
        markdown="Unlocated parser summary",
        engine="markitdown",
        parser_signature="test-v1",
    )
    documents = build_pdf_documents(path, parsed, raw.parent)
    storage = raw.parent / "version-1"
    storage.mkdir()
    persist_page_catalog(documents, storage)

    def resolve(kb, key):
        target = (raw / key).resolve()
        return (
            target
            if kb == "selected" and target.is_relative_to(raw.resolve()) and target.is_file()
            else None
        )

    monkeypatch.setattr("deeptutor.multi_user.knowledge_access.resolve_kb_document_path", resolve)
    monkeypatch.setattr(
        "deeptutor.multi_user.knowledge_access.resolve_for_rag",
        lambda kb: (
            SimpleNamespace(base_dir=raw.parent.parent, name="kb") if kb == "selected" else None
        ),
    )
    monkeypatch.setattr(
        "deeptutor.services.rag.embedding_signature.signature_from_embedding_config", lambda: None
    )
    monkeypatch.setattr(
        "deeptutor.services.rag.index_versioning.resolve_storage_dir_for_read",
        lambda *args: storage,
    )
    monkeypatch.setattr("deeptutor.services.llm.capabilities.supports_vision", lambda *args: True)
    store = LearningStore(tmp_path / "learning")
    progress = LearningProgress(
        book_id="path",
        modules=[
            LearningModule(
                id="m",
                name="Cells",
                order=0,
                knowledge_points=[
                    KnowledgePoint(
                        id="kp",
                        name="Sejthártya szerkezete",
                        type="memory",
                        module_id="m",
                        topic_source_ids=["s"],
                    )
                ],
            )
        ],
    )
    store.save(progress)
    store.put_topic(
        TopicMetadata(path_id="path"),
        [
            TopicSource(
                id="s",
                kind=TopicSourceKind.FILE,
                label="Lesson",
                source_id="lesson.pdf",
                metadata={"kb_name": "selected", "path": "lesson.pdf"},
            )
        ],
    )
    ref = SourceRef(
        kb_ref="selected",
        document_key="lesson.pdf",
        source_digest=source_digest(path),
        page_index=70,
    )
    return SimpleNamespace(
        path=path,
        raw=raw,
        documents=documents,
        storage=storage,
        store=store,
        ref=ref,
        config=SimpleNamespace(model="vision-test", binding="openai"),
    )


def test_source_guard_rejects_recording_unprepared_teaching(material, monkeypatch):
    from deeptutor.capabilities.mastery import tools

    monkeypatch.setattr(tools, "_new_service", lambda: LearningService(material.store))
    before = material.store.load("path").model_dump()
    result = asyncio.run(
        tools.MasteryNoteExplainedTool().execute(
            _mastery_path_id="path", knowledge_point_id="kp", summary="A proposed explanation"
        )
    )
    assert not result.success
    assert material.store.load("path").model_dump() == before


def test_source_guard_records_only_partial_coverage_and_rechecks_access(material, monkeypatch):
    from deeptutor.capabilities.mastery import tools

    _install_preparation(material, monkeypatch, rankings=[_partial_selection()])
    asyncio.run(lessons.prepare_lesson(material.store, "path", "kp", material.config))
    monkeypatch.setattr(tools, "_new_service", lambda: LearningService(material.store))
    from deeptutor.runtime.stream_bus import StreamBus

    explanation = "The membrane's bilayer forms the supported boundary around the cell."
    bus = StreamBus(assign_seq=True)
    asyncio.run(bus.content(explanation, source="mastery_path", stage="responding"))
    teaching = {
        "_session_id": "session",
        "_turn_id": "turn",
        "explanation_quote": explanation,
        "_teaching_delivery": lambda: {
            "path_id": "path",
            "session_id": "session",
            "turn_id": "turn",
            "segments": bus.public_content_snapshot(source="mastery_path", stage="responding"),
        },
    }
    result = asyncio.run(
        tools.MasteryNoteExplainedTool().execute(
            _mastery_path_id="path",
            knowledge_point_id="kp",
            summary="Only the supported bilayer slice",
            **teaching,
        )
    )
    assert result.success, result.content
    progress = material.store.load("path")
    assert progress.explained_objectives["kp"]["coverage"] == "partial"
    assert (
        not progress.mastery_levels
        and not progress.quiz_attempts
        and not progress.learning_evidence
    )
    before = progress.model_dump()
    monkeypatch.setattr("deeptutor.multi_user.knowledge_access.resolve_for_rag", lambda _: None)
    denied = asyncio.run(
        tools.MasteryNoteExplainedTool().execute(
            _mastery_path_id="path",
            knowledge_point_id="kp",
            summary="An unsupported later claim",
            **teaching,
        )
    )
    assert not denied.success
    assert material.store.load("path").model_dump() == before


def test_physical_pages_beyond_64_and_unlocated_text_preserved(material):
    pages = [d for d in material.documents if "page_index" in d.metadata]
    assert len(pages) == 72
    assert pages[70].metadata["page_index"] == 70
    assert pages[70].metadata["page"] == 71
    assert "bilayer" in pages[70].text
    assert material.documents[-1].metadata["page_status"] == "unlocated"
    assert "Unlocated parser summary" in material.documents[-1].text
    pixels = pymupdf.Pixmap(render_source_page(material.ref))
    assert pixels.width <= 2400 and pixels.width * pixels.height < 3_910_000


def test_text_only_objectives_keep_existing_route_and_old_pdf_question_is_rejected(material):
    material.path.unlink()
    (material.raw / "notes.txt").write_text("Text-only lesson", encoding="utf-8")
    progress = material.store.load("path")
    progress.source_grounded = True  # A different objective can have PDF evidence.
    material.store.put_topic(
        TopicMetadata(path_id="path"),
        [TopicSource(id="s", kind="knowledge_base", label="Text", source_id="selected")],
    )
    topic = material.store.get_topic("path")
    assert lessons.selected_scope(topic, progress, "kp") == {}
    lessons.validate_evidence(material.store, progress, "kp", {})
    with pytest.raises(lessons.LessonUnavailable, match="changed"):
        lessons.validate_evidence(material.store, progress, "kp", {"status": "ready"})


def test_every_selected_page_reaches_the_tutor_and_payload_is_bounded(material, monkeypatch):
    sources = [
        {"ref": material.ref.model_copy(update={"page_index": n}).model_dump()}
        for n in (68, 69, 70)
    ]
    message = lessons.image_message(sources)
    assert sum(p.get("type") == "image_url" for p in message["content"]) == 3
    monkeypatch.setattr(lessons, "render_source_page", lambda ref: b"x" * (5 * 1024 * 1024))
    with pytest.raises(lessons.LessonUnavailable, match="budget"):
        lessons.image_message(sources)


@pytest.mark.parametrize("crop", [(0, 0, 0, 1), (-1, 0, 1, 1), (0, 0, float("nan"), 1)])
def test_invalid_crops_rejected(material, crop):
    with pytest.raises(SourcePageError):
        render_source_page(material.ref.model_copy(update={"crop": crop}))


def test_rotated_page_and_safe_path_and_changed_source(material):
    pdf = pymupdf.open(material.path)
    pdf[70].set_rotation(90)
    pdf.saveIncr()
    pdf.close()
    ref = material.ref.model_copy(
        update={"source_digest": source_digest(material.path), "crop": (0, 0, 0.5, 1)}
    )
    assert render_source_page(ref)
    import numpy as np

    top = ref.model_copy(update={"crop": (0, 0, 1, 0.5)})
    pixmap = pymupdf.Pixmap(render_source_page(top))
    assert pixmap.width / pixmap.height == pytest.approx(4 / 3, rel=0.002)
    pixels = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
        pixmap.height, pixmap.width, pixmap.n
    )
    red = (pixels[:, :, 0] > 180) & (pixels[:, :, 1] < 80) & (pixels[:, :, 2] < 80)
    blue = (pixels[:, :, 2] > 180) & (pixels[:, :, 0] < 80) & (pixels[:, :, 1] < 80)
    assert red.mean() > 0.02 and blue.mean() < 0.001
    for changed in [
        material.ref,
        ref.model_copy(update={"document_key": "../../outside.pdf"}),
        ref.model_copy(update={"page_index": 500}),
        ref.model_copy(update={"kb_ref": "unselected"}),
    ]:
        with pytest.raises(SourcePageError):
            render_source_page(changed)


@pytest.mark.parametrize("faiss", [False, True])
def test_hybrid_search_is_pre_scoped_without_reembedding(faiss, monkeypatch):
    from deeptutor.services.rag.pipelines.llamaindex.retrievers import (
        _scoped_index,
        retrieve_scoped_nodes,
    )
    from deeptutor.services.rag.pipelines.llamaindex.vector_store import (
        faiss_available,
        storage_context_for_nodes,
    )

    if faiss and not faiss_available():
        pytest.skip("Optional FAISS is not installed")
    embed = MockEmbedding(embed_dim=4)
    wanted = TextNode(
        id_="wanted",
        text="Membrane lipids form a bilayer.",
        embedding=[1.0, 0.0, 0.0, 0.0],
        metadata={"document_key": "wanted.pdf", "page_status": "searchable"},
    )
    wrong = TextNode(
        id_="wrong",
        text="Membrane membrane membrane lipids bilayer.",
        embedding=[0.0, 1.0, 0.0, 0.0],
        metadata={"document_key": "wrong.pdf", "page_status": "searchable"},
    )
    nodes = [wanted, wrong]
    index = VectorStoreIndex(
        nodes=nodes,
        embed_model=embed,
        storage_context=storage_context_for_nodes(nodes) if faiss else None,
    )
    # KeyvalDocumentStore.docs deserializes the entire corpus on each access.
    # Inspect the real scoped-index call, not a fake retrieval implementation.
    store_type = type(index.docstore)
    original_docs = store_type.docs
    reads = []

    def counted_docs(store):
        if store is index.docstore:
            reads.append(1)
        return original_docs.__get__(store, store_type)

    monkeypatch.setattr(store_type, "docs", property(counted_docs))
    scoped = _scoped_index(index, ("wanted.pdf",))
    assert len(reads) == 1
    assert set(scoped.docstore.docs) == {"wanted"}
    hits = retrieve_scoped_nodes(index, "membrane bilayer", ["wanted.pdf"], top_k=8)
    assert [h.node.node_id for h in hits] == ["wanted"]
    assert retrieve_scoped_nodes(index, "membrane", ["missing.pdf"]) == []


def _install_preparation(
    material, monkeypatch, *, bad_quote=False, vision_responses=None, rankings=None
):
    calls = []
    vision_responses = list(vision_responses or [])
    rankings = list(rankings or [])
    material.search_queries = []

    async def search(self, query, kb_name, **kwargs):
        assert kwargs["document_keys"] == ["lesson.pdf"]
        material.search_queries.append(query)
        doc = material.documents[70]
        return {"sources": [{**doc.metadata, "chunk_id": "n70", "evidence_text": doc.text}]}

    async def ask(config, instruction, payload, images=None):
        calls.append((payload, images))
        if instruction.startswith('Return JSON {"queries"'):
            return {"queries": ["sejthártya", "membrane lipid bilayer"]}
        if "selected" in instruction:
            if rankings:
                return rankings.pop(0)
            return {
                "sufficient": True,
                "selected": [
                    {
                        "id": "c0",
                        "quote": "invented answer" if bad_quote else "lipids form a bilayer",
                        "reason": "Membrane structure",
                        "neighbor": 0,
                    }
                ],
            }
        assert sum(p.get("type") == "image_url" for p in images) == len(payload["sources"])
        assert any(
            p.get("image_url", {})
            .get("url", "")
            .startswith(("data:image/jpeg;base64,", "data:image/png;base64,"))
            for p in images
        )
        if vision_responses:
            return vision_responses.pop(0)
        return {
            "usable": True,
            "observations": "Red square left, blue circle right.",
            "limitations": "Synthetic diagram.",
        }

    monkeypatch.setattr(
        "deeptutor.services.rag.pipelines.llamaindex.pipeline.LlamaIndexPipeline.search", search
    )
    monkeypatch.setattr(lessons, "_ask", ask)
    return calls


def test_auto_lesson_cache_and_server_side_question_snapshot(material, monkeypatch):
    calls = _install_preparation(material, monkeypatch)
    evidence = asyncio.run(lessons.prepare_lesson(material.store, "path", "kp", material.config))
    assert evidence["status"] == "ready" and evidence["sources"][0]["ref"]["page_index"] == 70
    assert len(calls) == 3
    cached = asyncio.run(lessons.prepare_lesson(material.store, "path", "kp", material.config))
    assert cached["id"] == evidence["id"] and len(calls) == 3
    service = LearningService(material.store)
    progress, interaction, _ = service.register_question(
        "path",
        PendingQuestion(
            question_id="q",
            knowledge_point_id="kp",
            module_id="m",
            prompt="What forms a bilayer?",
            expected_answer="lipids",
        ),
    )
    assert interaction.question.source_evidence["id"] == evidence["id"]
    from deeptutor.learning.pending import public_pending_question

    card = json.dumps(public_pending_question(interaction.question).to_dict())
    assert "source_evidence" not in card and "expected_answer" not in card
    assert "base64" not in json.dumps(progress.model_dump())
    graded, _, _ = service.grade_interaction("path", question_id="q", answer="lipids")
    assert len(graded.quiz_attempts) == 1


def test_selector_uses_the_actual_module_learning_purpose(material, monkeypatch):
    from deeptutor.learning.models import LearnerProfile

    calls = _install_preparation(material, monkeypatch)
    progress = material.store.load("path")
    progress.modules[0].objective = "Identify the major components in introductory examples."
    progress.learner_profile = LearnerProfile(
        target_level="Introductory course, not research-level mechanisms"
    )
    material.store.save(progress)
    asyncio.run(lessons.prepare_lesson(material.store, "path", "kp", material.config))
    selector_payload = calls[1][0]
    assert selector_payload["purpose"] == progress.modules[0].objective
    assert selector_payload["module"] == "Cells"
    assert selector_payload["target_level"] == progress.learner_profile.target_level
    assert "course_goal" in selector_payload


@pytest.mark.parametrize("field", ["course_goal", "target_level"])
def test_changed_course_intent_reprepares_without_erasing_answer_evidence(
    material, monkeypatch, field
):
    calls = _install_preparation(material, monkeypatch)
    old = asyncio.run(lessons.prepare_lesson(material.store, "path", "kp", material.config))
    service = LearningService(material.store)
    service.register_question(
        "path", PendingQuestion(question_id="q", knowledge_point_id="kp", expected_answer="lipids")
    )
    if field == "course_goal":
        topic = material.store.get_topic("path")
        topic.metadata.goal = "Explain membrane transport for a graduate course."
        material.store.put_topic(topic.metadata, topic.sources)
    else:
        progress = material.store.load("path")
        progress.learner_profile = LearnerProfile(
            target_level="Graduate mechanisms, not introductory names"
        )
        material.store.save(progress)
    progress = material.store.load("path")
    assert lessons.cached_lesson(material.store, progress, "kp", material.config) is None
    fresh = asyncio.run(lessons.prepare_lesson(material.store, "path", "kp", material.config))
    assert fresh["id"] != old["id"] and len(calls) == 6
    assert calls[4][0][field]
    # Changed teaching intent does not change a previously verified factual key.
    graded, _, _ = service.grade_interaction("path", question_id="q", answer="lipids")
    assert len(graded.quiz_attempts) == 1 and graded.quiz_attempts[0].is_correct


def test_pacing_feedback_keeps_valid_lesson_without_paid_repreparation(material, monkeypatch):
    calls = _install_preparation(material, monkeypatch)
    old = asyncio.run(lessons.prepare_lesson(material.store, "path", "kp", material.config))
    progress = material.store.load("path")
    progress.learner_profile = LearnerProfile(preferences="Give shorter explanations")
    material.store.save(progress)
    current = asyncio.run(lessons.prepare_lesson(material.store, "path", "kp", material.config))
    assert current["id"] == old["id"] and len(calls) == 3


@pytest.mark.parametrize("field", ["course_goal", "target_level"])
def test_course_intent_change_during_preparation_cannot_publish_stale_packet(
    material, monkeypatch, field
):
    _install_preparation(material, monkeypatch)
    ask = lessons._ask

    async def change_during_selection(*args, **kwargs):
        result = await ask(*args, **kwargs)
        if field == "course_goal":
            topic = material.store.get_topic("path")
            topic.metadata.goal = "Changed course requirements"
            material.store.put_topic(topic.metadata, topic.sources)
        else:
            progress = material.store.load("path")
            progress.learner_profile = LearnerProfile(target_level="Changed intended level")
            material.store.save(progress)
        return result

    monkeypatch.setattr(lessons, "_ask", change_during_selection)
    with pytest.raises(lessons.LessonUnavailable, match="changed"):
        asyncio.run(lessons.prepare_lesson(material.store, "path", "kp", material.config))
    assert not material.store.load("path").lesson_evidence


@pytest.mark.asyncio
async def test_cached_lesson_reports_revoked_access_without_repeating_preparation(
    material, monkeypatch
):
    from deeptutor.capabilities.mastery.pipeline import MasteryLoopPipeline
    from deeptutor.core.context import UnifiedContext
    from deeptutor.runtime.stream_bus import StreamBus

    calls = _install_preparation(material, monkeypatch)
    await lessons.prepare_lesson(material.store, "path", "kp", material.config)
    monkeypatch.setattr("deeptutor.learning.storage.LearningStore", lambda: material.store)
    monkeypatch.setattr(
        "deeptutor.multi_user.knowledge_access.resolve_kb_document_path", lambda *_args: None
    )
    pipeline = MasteryLoopPipeline(language="en")
    pipeline.llm_config = material.config
    context = UnifiedContext(user_message="Continue", metadata={"mastery_path_id": "path"})
    messages = [{"role": "user", "content": context.user_message}]
    for _ in range(2):
        assert await pipeline.prepare_model_request(context, StreamBus(), messages) == []
    assert "access was revoked" in messages[-1]["content"]
    assert "not prepared for this request" not in messages[-1]["content"]
    assert pipeline._lesson_pixels is None and len(calls) == 3


@pytest.mark.parametrize("count", [4, 7])
def test_broad_objective_can_use_more_pages_but_remains_bounded(material, monkeypatch, count):
    _install_preparation(material, monkeypatch)

    async def search(self, query, kb_name, **kwargs):
        return {
            "sources": [
                {**d.metadata, "chunk_id": f"n{i}", "evidence_text": d.text}
                for i, d in enumerate(material.documents[:count])
            ]
        }

    batches = []

    async def ask(config, instruction, payload, images=None):
        if instruction.startswith('Return JSON {"queries"'):
            return {"queries": ["cells"]}
        if "selected" in instruction:
            assert "smallest sufficient set" in instruction
            return {
                "sufficient": True,
                "selected": [
                    {
                        "id": f"c{i}",
                        "quote": f"Unrelated section {i}.",
                        "reason": "Part of objective",
                    }
                    for i in range(count)
                ],
            }
        batches.append(len(payload["sources"]))
        return {"usable": True, "observations": "Verified page", "limitations": ""}

    monkeypatch.setattr(
        "deeptutor.services.rag.pipelines.llamaindex.pipeline.LlamaIndexPipeline.search", search
    )
    monkeypatch.setattr(lessons, "_ask", ask)
    if count > lessons.MAX_LESSON_PAGES:
        with pytest.raises(lessons.LessonUnavailable, match="selection count"):
            asyncio.run(lessons.prepare_lesson(material.store, "path", "kp", material.config))
        assert not material.store.load("path").lesson_evidence
    else:
        evidence = asyncio.run(
            lessons.prepare_lesson(material.store, "path", "kp", material.config)
        )
        assert len(evidence["sources"]) == count
        assert batches == [2, 2]


@pytest.mark.parametrize("action", ["neighbor", "crop", "search"])
def test_one_targeted_repair_is_verified_and_cached(material, monkeypatch, action):
    repair = {
        "action": action,
        "reason": "Required figure detail needs inspection.",
        "source_index": 0,
        "offset": 1,
        "crop": [0.05, 0.2, 0.5, 0.75],
        "query": "membrane diagram structure detail",
    }
    calls = _install_preparation(
        material,
        monkeypatch,
        vision_responses=[
            {"usable": False, "limitations": "Missing figure detail", "repair": repair}
        ],
    )
    evidence = asyncio.run(lessons.prepare_lesson(material.store, "path", "kp", material.config))
    assert evidence["status"] == "ready" and evidence["repair"]["action"] == action
    assert len(calls) == (5 if action == "search" else 4)
    if action == "search":
        assert material.search_queries[-1] == repair["query"]
        assert calls[-2][0]["previous_gap"] == "Missing figure detail"
    else:
        assert len(evidence["sources"]) == 2
        original, added = evidence["sources"]
        assert original["ref"]["page_index"] == 70 and original["ref"]["crop"] is None
        assert added["ref"]["page_index"] == (71 if action == "neighbor" else 70)
        assert bool(added["ref"]["crop"]) == (action == "crop")
    assert "base64" not in json.dumps(evidence)
    cached = asyncio.run(lessons.prepare_lesson(material.store, "path", "kp", material.config))
    assert cached["id"] == evidence["id"] and len(calls) == (5 if action == "search" else 4)
    assert not material.store.load("path").mastery_levels


def test_text_coverage_gap_gets_one_targeted_search(material, monkeypatch):
    calls = _install_preparation(
        material,
        monkeypatch,
        rankings=[
            {
                "sufficient": False,
                "missing": "A figure explanation is needed.",
                "repair": {
                    "action": "search",
                    "query": "bilayer figure explanation",
                    "reason": "Missing explanatory passage.",
                },
            }
        ],
    )
    evidence = asyncio.run(lessons.prepare_lesson(material.store, "path", "kp", material.config))
    assert evidence["repair"]["action"] == "search" and len(calls) == 4
    assert material.search_queries[-1] == "bilayer figure explanation"


def _partial_selection(*, repair=False):
    ranking = {
        "sufficient": False,
        "missing": "One later mechanism is not covered.",
        "selected": [
            {
                "id": "c0",
                "quote": "lipids form a bilayer",
                "reason": "Bilayer structure",
                "neighbor": 0,
            }
        ],
    }
    if repair:
        ranking["repair"] = {
            "action": "search",
            "query": "later membrane mechanism",
            "reason": "Find the missing mechanism.",
        }
    return ranking


def test_useful_partial_lesson_is_cached_but_not_assessment_permission(material, monkeypatch):
    calls = _install_preparation(material, monkeypatch, rankings=[_partial_selection()])
    evidence = asyncio.run(lessons.prepare_lesson(material.store, "path", "kp", material.config))
    assert evidence["status"] == "ready" and not evidence["coverage"]["complete"]
    assert evidence["coverage"]["scope"] == "objective"
    assert "later mechanism" in evidence["coverage"]["missing"]
    assert evidence["sources"] and evidence["model_observations"]
    progress = material.store.load("path")
    assert (
        lessons.cached_lesson(material.store, progress, "kp", material.config)["id"]
        == evidence["id"]
    )
    lessons.validate_evidence(material.store, progress, "kp", evidence, allow_partial=True)
    with pytest.raises(lessons.LessonUnavailable, match="assessment"):
        lessons.question_snapshot(material.store, progress, "kp")
    cached = asyncio.run(lessons.prepare_lesson(material.store, "path", "kp", material.config))
    assert cached["id"] == evidence["id"] and len(calls) == 3
    assert not progress.mastery_levels and not progress.quiz_attempts


def test_final_repair_gap_preserves_already_inspected_useful_sources(material, monkeypatch):
    calls = _install_preparation(
        material, monkeypatch, rankings=[_partial_selection(repair=True), _partial_selection()]
    )
    evidence = asyncio.run(lessons.prepare_lesson(material.store, "path", "kp", material.config))
    assert evidence["status"] == "ready" and not evidence["coverage"]["complete"]
    assert evidence["repair"]["action"] == "search"
    assert len(material.search_queries) == 3
    assert len(calls) <= 5
    assert evidence["sources"][0]["ref"]["page_index"] == 70


@pytest.mark.parametrize("changed_support", [False, True])
def test_repair_reuses_only_identical_successful_inspection(material, monkeypatch, changed_support):
    repaired = _partial_selection()
    if changed_support:
        repaired["selected"][0]["reason"] = "A different relationship needs inspection"
    calls = _install_preparation(
        material, monkeypatch, rankings=[_partial_selection(repair=True), repaired]
    )
    evidence = asyncio.run(lessons.prepare_lesson(material.store, "path", "kp", material.config))
    pixel_calls = [payload for payload, images in calls if images]
    assert len(pixel_calls) == (2 if changed_support else 1)
    assert evidence["sources"] and evidence["model_observations"]
    assert not evidence["coverage"]["complete"]


def test_focus_and_current_request_reach_preparation_without_extra_cache_calls(
    material, monkeypatch
):
    calls = _install_preparation(material, monkeypatch)
    first = asyncio.run(
        lessons.prepare_lesson(
            material.store,
            "path",
            "kp",
            material.config,
            focus="Show two existing practice items",
            learner_request="Use my question bank first",
        )
    )
    assert all(call[0].get("focus") == "Show two existing practice items" for call in calls)
    assert all(call[0].get("learner_request") == "Use my question bank first" for call in calls)
    assert first["coverage"]["scope"] == "focus" and first["coverage"]["complete"]
    count = len(calls)
    reused = asyncio.run(
        lessons.prepare_lesson(
            material.store,
            "path",
            "kp",
            material.config,
            focus="Show two existing practice items",
            learner_request="Please continue",
        )
    )
    assert reused["id"] == first["id"] and len(calls) == count
    changed = asyncio.run(
        lessons.prepare_lesson(
            material.store, "path", "kp", material.config, focus="Teach bilayer structure"
        )
    )
    assert len(calls) == count + 3 and changed["id"] != first["id"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"focus": 42},
        {"focus": "x" * 801},
        {"learner_request": []},
        {"learner_request": "x" * 4001},
        {"refresh": "yes"},
    ],
)
def test_preparation_context_is_bounded_and_validated(material, monkeypatch, kwargs):
    calls = _install_preparation(material, monkeypatch)
    with pytest.raises(lessons.LessonUnavailable):
        asyncio.run(lessons.prepare_lesson(material.store, "path", "kp", material.config, **kwargs))
    assert not calls and not material.store.load("path").lesson_evidence


def test_explicit_refresh_changes_identity_when_original_pixels_change(material, monkeypatch):
    _install_preparation(material, monkeypatch)
    first = asyncio.run(lessons.prepare_lesson(material.store, "path", "kp", material.config))
    _install_preparation(
        material,
        monkeypatch,
        rankings=[
            {
                "sufficient": True,
                "selected": [
                    {
                        "id": "c0",
                        "quote": "lipids form a bilayer",
                        "reason": "Neighbor context",
                        "neighbor": -1,
                    }
                ],
            }
        ],
    )
    refreshed = asyncio.run(
        lessons.prepare_lesson(material.store, "path", "kp", material.config, refresh=True)
    )
    assert refreshed["id"] != first["id"]
    assert len(refreshed["sources"]) == 2


def test_partial_fallback_never_accepts_a_fabricated_quote(material, monkeypatch):
    invalid = _partial_selection()
    invalid["selected"][0]["quote"] = "invented scientific fact"
    _install_preparation(material, monkeypatch, rankings=[_partial_selection(repair=True), invalid])
    with pytest.raises(lessons.LessonUnavailable, match="quotation"):
        asyncio.run(lessons.prepare_lesson(material.store, "path", "kp", material.config))
    assert not material.store.load("path").lesson_evidence


def test_unusable_first_batch_does_not_hide_later_readable_page(material, monkeypatch):
    _install_preparation(
        material,
        monkeypatch,
        rankings=[
            {
                "sufficient": True,
                "selected": [
                    {"id": f"c{i}", "quote": quote, "reason": "Located page", "neighbor": 0}
                    for i, quote in enumerate(
                        ["Unrelated section 68", "Unrelated section 69", "lipids form a bilayer"]
                    )
                ],
            }
        ],
        vision_responses=[
            {"usable": False, "limitations": "First pages do not support the requested detail."},
            {"usable": True, "observations": "Lipids form a bilayer.", "limitations": ""},
        ],
    )

    async def search(self, query, kb_name, **kwargs):
        return {
            "sources": [
                {
                    **material.documents[n].metadata,
                    "chunk_id": f"n{n}",
                    "evidence_text": material.documents[n].text,
                }
                for n in (68, 69, 70)
            ]
        }

    monkeypatch.setattr(
        "deeptutor.services.rag.pipelines.llamaindex.pipeline.LlamaIndexPipeline.search", search
    )
    evidence = asyncio.run(lessons.prepare_lesson(material.store, "path", "kp", material.config))
    assert not evidence["coverage"]["complete"]
    assert [entry["ref"]["page_index"] for entry in evidence["sources"]] == [70]
    assert evidence["model_observations"][0]["source_indices"] == [0]
    assert "teach the supported slice now" in lessons.lesson_context(evidence)


@pytest.mark.parametrize(
    "repair_result", [{"sources": []}, {"error_type": "index_unavailable", "sources": []}]
)
def test_empty_repair_retains_evidence_but_index_error_still_fails(
    material, monkeypatch, repair_result
):
    _install_preparation(material, monkeypatch, rankings=[_partial_selection(repair=True)])

    async def search(self, query, kb_name, **kwargs):
        if query == "later membrane mechanism":
            return repair_result
        doc = material.documents[70]
        return {"sources": [{**doc.metadata, "chunk_id": "n70", "evidence_text": doc.text}]}

    monkeypatch.setattr(
        "deeptutor.services.rag.pipelines.llamaindex.pipeline.LlamaIndexPipeline.search", search
    )
    if repair_result.get("error_type"):
        with pytest.raises(lessons.LessonUnavailable, match="index"):
            asyncio.run(lessons.prepare_lesson(material.store, "path", "kp", material.config))
        assert not material.store.load("path").lesson_evidence
    else:
        evidence = asyncio.run(
            lessons.prepare_lesson(material.store, "path", "kp", material.config)
        )
        assert evidence["status"] == "ready" and not evidence["coverage"]["complete"]
        assert evidence["sources"][0]["ref"]["page_index"] == 70


def test_focused_teaching_packet_cannot_authorize_unrelated_quiz(material, monkeypatch):
    _install_preparation(material, monkeypatch)
    evidence = asyncio.run(
        lessons.prepare_lesson(
            material.store, "path", "kp", material.config, focus="Explain bilayer structure"
        )
    )
    assert evidence["coverage"]["complete"]
    lessons.validate_evidence(
        material.store, material.store.load("path"), "kp", evidence, allow_partial=True
    )
    with pytest.raises(lessons.LessonUnavailable, match="assessment"):
        lessons.question_snapshot(material.store, material.store.load("path"), "kp")


@pytest.mark.parametrize(
    "repair",
    [
        {"action": "unexpected", "reason": "Missing detail"},
        {"action": "search", "queries": ["x"] * 4, "reason": "Missing detail"},
    ],
)
def test_malformed_repair_does_not_discard_already_verified_material(material, monkeypatch, repair):
    ranking = _partial_selection()
    ranking["repair"] = repair
    _install_preparation(material, monkeypatch, rankings=[ranking])
    evidence = asyncio.run(lessons.prepare_lesson(material.store, "path", "kp", material.config))
    assert evidence["status"] == "ready" and not evidence["coverage"]["complete"]
    assert evidence["sources"]


def test_multiple_missing_facets_use_one_bounded_repair_phase(material, monkeypatch):
    queries = ["glycocalyx functions", "phospholipid synthesis site"]
    calls = _install_preparation(
        material,
        monkeypatch,
        rankings=[
            {
                "sufficient": False,
                "missing": "Two independent details are missing.",
                "repair": {
                    "action": "search",
                    "queries": queries,
                    "reason": "Recover both missing details together.",
                },
            }
        ],
    )
    evidence = asyncio.run(lessons.prepare_lesson(material.store, "path", "kp", material.config))
    assert evidence["status"] == "ready"
    assert material.search_queries[-2:] == queries
    assert len(calls) == 4  # Still one query plan, two selections, one pixel check.


@pytest.mark.parametrize("queries", [[], ["x"] * 4, [123], [" "], ["x" * 401], ["sejthártya"]])
def test_repair_query_budget_is_validated(material, monkeypatch, queries):
    _install_preparation(
        material,
        monkeypatch,
        rankings=[
            {
                "sufficient": False,
                "missing": "A detail is missing.",
                "repair": {"action": "search", "queries": queries, "reason": "Missing detail."},
            }
        ],
    )
    with pytest.raises(lessons.LessonUnavailable, match="bounded retrieval queries"):
        asyncio.run(lessons.prepare_lesson(material.store, "path", "kp", material.config))
    assert not material.store.load("path").lesson_evidence


def test_lesson_selection_keeps_evidence_from_every_generated_query(material, monkeypatch):
    """A broad objective must not lose its third facet before the selector sees it."""
    queries = ["first facet", "second facet", "third facet"]

    async def search(self, query, kb_name, **kwargs):
        start = queries.index(query) * 8
        return {
            "sources": [
                {**doc.metadata, "chunk_id": f"n{i}", "evidence_text": doc.text}
                for i, doc in enumerate(material.documents[start : start + 8], start)
            ]
        }

    async def ask(config, instruction, payload, images=None):
        if instruction.startswith('Return JSON {"queries"'):
            return {"queries": queries}
        if "selected" in instruction:
            by_page = {c["ref"]["page_index"]: c for c in payload["candidates"]}
            assert {0, 8, 16}.issubset(by_page), (
                "Existing third-facet evidence was discarded before verification"
            )
            return {
                "sufficient": True,
                "selected": [
                    {
                        "id": by_page[i]["id"],
                        "quote": f"Unrelated section {i}.",
                        "reason": f"Facet {i}",
                        "neighbor": 0,
                    }
                    for i in (0, 8, 16)
                ],
            }
        return {"usable": True, "observations": "Synthetic evidence", "limitations": ""}

    monkeypatch.setattr(
        "deeptutor.services.rag.pipelines.llamaindex.pipeline.LlamaIndexPipeline.search", search
    )
    monkeypatch.setattr(lessons, "_ask", ask)
    evidence = asyncio.run(lessons.prepare_lesson(material.store, "path", "kp", material.config))
    assert evidence["status"] == "ready"
    assert len(evidence["sources"]) == 3


def test_lesson_selector_reads_page_context_beyond_the_retrieved_chunk(material, monkeypatch):
    _install_preparation(material, monkeypatch)

    async def search(self, query, kb_name, **kwargs):
        doc = material.documents[70]
        return {
            "sources": [{**doc.metadata, "chunk_id": "short", "evidence_text": "Membrane lipids"}]
        }

    monkeypatch.setattr(
        "deeptutor.services.rag.pipelines.llamaindex.pipeline.LlamaIndexPipeline.search", search
    )
    evidence = asyncio.run(lessons.prepare_lesson(material.store, "path", "kp", material.config))
    assert evidence["sources"][0]["quote"] == "lipids form a bilayer"
    assert "Membrane lipids form a bilayer." in evidence["sources"][0]["text"]


def test_page_limit_counts_physical_pages_not_multiple_quotes_from_one_page(material, monkeypatch):
    selected = [
        {"id": "c0", "quote": "lipids form a bilayer", "reason": f"Supported facet {i}"}
        for i in range(7)
    ]
    _install_preparation(
        material, monkeypatch, rankings=[{"sufficient": True, "selected": selected}]
    )
    evidence = asyncio.run(lessons.prepare_lesson(material.store, "path", "kp", material.config))
    assert len(evidence["sources"]) == 1


def test_page_enrichment_never_discards_the_hit_near_end_of_a_long_page(material, monkeypatch):
    hit = "Membrane lipids form a bilayer."
    monkeypatch.setattr(
        pymupdf.Page, "get_text", lambda *args, **kwargs: "Unrelated filler. " * 900 + hit
    )
    candidate = {"ref": material.ref.model_dump(), "text": hit}
    enriched = lessons._enrich_pages([candidate])[0]
    assert hit in enriched["text"]
    assert len(enriched["text"]) <= 8000


def test_page_enrichment_retains_long_ocr_text_when_native_text_differs(material, monkeypatch):
    monkeypatch.setattr(pymupdf.Page, "get_text", lambda *args, **kwargs: "Native page text.")
    parsed = "OCR detail. " * 500 + "Important retrieved conclusion."
    candidate = {"ref": material.ref.model_dump(), "text": parsed}
    enriched = lessons._enrich_pages([candidate])[0]
    assert "Important retrieved conclusion." in enriched["text"]
    assert len(enriched["text"]) <= 8000


def test_page_budget_skips_duplicate_chunks_and_preserves_repair_context():
    def candidate(page):
        return {
            "ref": {"kb_ref": "selected", "document_key": "lesson.pdf", "page_index": page},
            "text": f"Page {page}",
        }

    original = [candidate(i) for i in range(12)]
    fresh = [candidate(i) for i in range(20, 28)]
    selected = lessons._balanced_candidates([[original[0]] * 8 + original, fresh])
    assert len(selected) == 12
    assert len({lessons._page_identity(c) for c in selected}) == 12
    assert {0, 1, 2, 3, 4, 5, 20, 21, 22, 23, 24, 25} == {c["ref"]["page_index"] for c in selected}
    assert [c["id"] for c in selected] == [f"c{i}" for i in range(12)]


def test_repair_retains_useful_pages_selected_near_end_of_initial_candidates():
    def candidate(page):
        return {
            "id": f"c{page}",
            "ref": {"kb_ref": "selected", "document_key": "lesson.pdf", "page_index": page},
            "text": f"Page {page}",
        }

    original = [candidate(i) for i in range(12)]
    fresh = [candidate(i) for i in range(20, 28)]
    ranking = {"sufficient": False, "selected": [{"id": f"c{i}"} for i in (6, 6, 6, 4, 4, 1, 1, 8)]}
    selected = lessons._repair_candidates(original, fresh, ranking)
    assert len(selected) == 12
    assert {6, 4, 1, 8, 20}.issubset({c["ref"]["page_index"] for c in selected})


@pytest.mark.parametrize(
    "language, message", [("en", "one targeted retry"), ("zh", "一次针对性重试")]
)
def test_repair_never_loops_or_publishes_failed_evidence(material, monkeypatch, language, message):
    failure = {
        "usable": False,
        "limitations": "Still unreadable",
        "repair": {
            "action": "crop",
            "source_index": 0,
            "crop": [0.1, 0.1, 0.7, 0.8],
            "reason": "Small labels",
        },
    }
    calls = _install_preparation(material, monkeypatch, vision_responses=[failure, failure])
    with pytest.raises(lessons.LessonUnavailable, match=message):
        asyncio.run(
            lessons.prepare_lesson(material.store, "path", "kp", material.config, language=language)
        )
    assert len(calls) == 4
    assert not material.store.load("path").lesson_evidence


@pytest.mark.parametrize(
    "repair",
    [
        {"action": "crop", "source_index": 2, "crop": [0.1, 0.1, 0.5, 0.5]},
        {"action": "crop", "source_index": 0, "crop": [-0.1, 0, 0.5, 0.5]},
        {"action": "crop", "source_index": 0, "crop": [0, 0, 1, 1]},
        {"action": "neighbor", "source_index": 0, "offset": 5},
        {"action": "neighbor", "source_index": True, "offset": 1},
    ],
)
def test_page_repair_is_bounded_and_source_anchored(material, repair):
    sources = [{"ref": material.ref.model_dump()}]
    with pytest.raises(lessons.LessonUnavailable):
        lessons._repair_page(sources, 0, repair, {"selected": {"pages": []}})


def test_repair_checks_original_with_detail_even_for_second_source(material):
    refs = [material.ref.model_copy(update={"page_index": n}).model_dump() for n in (69, 70)]
    sources = [{"ref": ref} for ref in refs]
    result = lessons._repair_page(
        sources,
        0,
        {
            "action": "crop",
            "source_index": 1,
            "crop": [0.05, 0.2, 0.5, 0.75],
            "reason": "Small label",
        },
        {},
    )
    assert result[0] is sources[1] and result[1]["ref"]["crop"]
    assert result[2] is sources[0]


def test_selection_id_without_quote_preserves_original_evidence(material, monkeypatch):
    calls = _install_preparation(
        material,
        monkeypatch,
        rankings=[{"sufficient": True, "selected": [{"id": "c0", "reason": "Membrane structure"}]}],
    )
    evidence = asyncio.run(lessons.prepare_lesson(material.store, "path", "kp", material.config))
    source = evidence["sources"][0]
    candidate = calls[1][0]["candidates"][0]
    assert source["text"] == candidate["text"]
    assert source["quote"] == candidate["text"][:300]
    assert calls[2][0]["sources"][0]["text"] == candidate["text"]
    assert calls[2][1] and len(calls) == 3


def test_selection_unknown_id_without_quote_is_rejected(material, monkeypatch):
    _install_preparation(
        material,
        monkeypatch,
        rankings=[
            {
                "sufficient": True,
                "selected": [{"id": "not-retrieved", "reason": "Membrane structure"}],
            }
        ],
    )
    with pytest.raises(lessons.LessonUnavailable, match="source ID"):
        asyncio.run(lessons.prepare_lesson(material.store, "path", "kp", material.config))
    assert not material.store.load("path").lesson_evidence


@pytest.mark.parametrize(
    "original,quote",
    [
        ("prefix lipids\n\tform a\u00a0bilayer suffix", "lipids form a bilayer"),
        ("prefix cafe\u0301 membrane suffix", "caf\u00e9 membrane"),
        ("prefix caf\u00e9 membrane suffix", "cafe\u0301 membrane"),
    ],
)
def test_legacy_selection_quote_normalization_preserves_original(original, quote):
    excerpt = lessons._selection_excerpt(original, {"quote": quote})
    assert excerpt in original
    assert excerpt == original[len("prefix ") : -len(" suffix")]


@pytest.mark.parametrize(
    "quote", ["membranes are made of lipids", "LIPIDS form a bilayer", "", "bilayer"]
)
def test_legacy_selection_quote_never_accepts_paraphrase_or_invalid_length(quote):
    with pytest.raises(lessons.LessonUnavailable, match="quotation"):
        lessons._selection_excerpt("Membrane lipids form a bilayer.", {"quote": quote})


def test_unknown_quote_is_not_ready_and_not_mastery(material, monkeypatch):
    _install_preparation(material, monkeypatch, bad_quote=True)
    with pytest.raises(lessons.LessonUnavailable, match="quotation"):
        asyncio.run(lessons.prepare_lesson(material.store, "path", "kp", material.config))
    progress = material.store.load("path")
    assert not progress.lesson_evidence and not progress.mastery_levels
    with pytest.raises(MasteryInteractionError):
        LearningService(material.store).register_question(
            "path",
            PendingQuestion(question_id="unsafe", knowledge_point_id="kp", expected_answer="x"),
        )


@pytest.mark.parametrize("change", ["objective", "source", "index", "selection"])
def test_stale_source_blocks_grading_without_erasing_history(material, monkeypatch, change):
    _install_preparation(material, monkeypatch)
    asyncio.run(lessons.prepare_lesson(material.store, "path", "kp", material.config))
    service = LearningService(material.store)
    service.register_question(
        "path", PendingQuestion(question_id="q", knowledge_point_id="kp", expected_answer="lipids")
    )
    if change == "objective":
        progress = material.store.load("path")
        progress.modules[0].knowledge_points[0].name = "Unrelated objective"
        material.store.save(progress)
    elif change == "source":
        pdf = pymupdf.open(material.path)
        pdf[70].insert_text((20, 185), "Changed after question registration")
        pdf.saveIncr()
        pdf.close()
    elif change == "index":
        catalog = json.loads((material.storage / "source_pages.json").read_text())
        catalog["pages"][0]["parser_signature"] = "replacement"
        (material.storage / "source_pages.json").write_text(json.dumps(catalog))
    else:
        material.store.put_topic(TopicMetadata(path_id="path"), [])
    before = material.store.load("path").model_dump()
    with pytest.raises(MasteryInteractionError):
        service.grade_interaction("path", question_id="q", answer="lipids")
    after = material.store.load("path").model_dump()
    assert after == before


def test_outline_reorder_keeps_evidence_identity(material):
    progress = material.store.load("path")
    first = lessons.objective_fingerprint(progress, "kp")
    progress.modules.reverse()
    progress.modules[0].order = 99
    assert lessons.objective_fingerprint(progress, "kp") == first


def test_missing_page_catalog_requires_explicit_reindex(material):
    (material.storage / "source_pages.json").unlink()
    with pytest.raises(lessons.LessonUnavailable, match="preparation"):
        lessons.scope_snapshot(material.store.get_topic("path"), material.store.load("path"), "kp")


@pytest.mark.parametrize("without_stemming_adapter", [False, True])
def test_legacy_sidecar_needs_no_ocr_no_embeddings_and_preserves_vector_index(
    material, monkeypatch, without_stemming_adapter
):
    from deeptutor.services.rag.pipelines.llamaindex.retrievers import retrieve_legacy_pages
    from deeptutor.services.rag.source_pages import legacy_page_index

    if without_stemming_adapter:
        monkeypatch.setattr(
            "deeptutor.services.rag.pipelines.llamaindex.retrievers._import_bm25_retriever",
            lambda: None,
        )
    (material.storage / "docstore.json").write_text("unchanged legacy vectors")
    sidecar = legacy_page_index(material.raw.parent, material.storage, ["lesson.pdf"], build=True)
    hits = retrieve_legacy_pages(sidecar, "membrane lipid bilayer")
    assert hits[0].node.metadata["page_index"] == 70
    assert (material.storage / "docstore.json").read_text() == "unchanged legacy vectors"
    assert legacy_page_index(material.raw.parent, material.storage, ["lesson.pdf"]) == sidecar


def test_preparation_instructions_travel_in_actual_messages(material, monkeypatch):
    async def complete(**kwargs):
        assert kwargs["messages"][0] == {"role": "system", "content": "Return only JSON"}
        assert kwargs["allow_image_fallback"] is False
        return '{"queries":["membrane"]}'

    monkeypatch.setattr("deeptutor.services.llm.factory.complete_with_config", complete)
    assert asyncio.run(
        lessons._ask(material.config, "Return only JSON", {"objective": "membrane"})
    ) == {"queries": ["membrane"]}
