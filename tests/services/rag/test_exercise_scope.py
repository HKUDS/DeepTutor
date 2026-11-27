"""Exact retrieval must retain scoped page evidence, or use scoped semantic retrieval."""

from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from llama_index.core import VectorStoreIndex
from llama_index.core.embeddings import MockEmbedding
from llama_index.core.schema import TextNode
import pymupdf

from deeptutor.services.parsing.cache import source_hash_from_path, write_manifest
from deeptutor.services.rag.pipelines.llamaindex import storage
from deeptutor.services.rag.pipelines.llamaindex.pipeline import LlamaIndexPipeline
from deeptutor.services.rag.source_pages import build_pdf_documents, persist_page_catalog


class ExerciseScopeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.kb = self.root / "knowledge_bases" / "books"
        self.raw = self.kb / "raw"
        self.raw.mkdir(parents=True)
        self.directory = self.kb / "version-1"
        self.embed = MockEmbedding(embed_dim=4)
        self.nodes = []
        self.documents = []
        self.parses = {}
        self.add_pdf("selected.pdf", "SELECTED")
        self.add_pdf("unselected.pdf", "UNSELECTED")
        self.persist()
        self.pipeline = LlamaIndexPipeline(
            kb_base_dir=str(self.kb.parent), signature_provider=lambda: None
        )
        for p in [
            patch.object(self.pipeline, "_configure_settings", return_value=None),
            patch(
                "deeptutor.services.rag.pipelines.llamaindex.embedding_adapter.current_embedding",
                return_value=self.embed,
            ),
            patch(
                "deeptutor.services.rag.pipelines.llamaindex.pipeline.resolve_storage_dir_for_read",
                return_value=self.directory,
            ),
        ]:
            p.start()
            self.addCleanup(p.stop)
        self.retriever = patch.object(storage, "retrieve_nodes", wraps=storage.retrieve_nodes)
        self.semantic = self.retriever.start()
        self.addCleanup(self.retriever.stop)
        self.addCleanup(storage.clear_index_cache)

    def add_pdf(self, name, marker):
        source = self.raw / name
        source.parent.mkdir(parents=True, exist_ok=True)
        with pymupdf.open() as pdf:
            for n in range(2):
                page = pdf.new_page()
                page.insert_text((72, 72), f"{marker} PAGE {n + 1}")
            pdf.save(source)
        blocks = [
            {"type": "text", "text": "第二章 教材", "page_idx": 0},
            {"type": "text", "text": "习题", "page_idx": 0},
            {"type": "text", "text": f"2-13 {marker} FIRST", "page_idx": 0},
            {"type": "text", "text": f"{marker} SECOND", "page_idx": 1},
        ]
        digest = source_hash_from_path(source)
        folder = self.root / "parse_cache" / digest[:2] / digest / "fixture"
        folder.mkdir(parents=True)
        (folder / "full_content_list.json").write_text(json.dumps(blocks), encoding="utf-8")
        write_manifest(folder, {"source_hash": digest, "signature": "fixture"})
        self.parses[name] = folder / "full_content_list.json"
        docs = build_pdf_documents(
            source,
            SimpleNamespace(
                blocks=blocks, parser_signature="fixture", engine="fixture", markdown=""
            ),
            self.kb,
        )
        self.documents.extend(docs)
        for doc in docs:
            self.nodes.append(
                TextNode(text=doc.text, metadata=doc.metadata, embedding=[1.0, 1.0, 1.0, 1.0])
            )

    def persist(self):
        VectorStoreIndex(nodes=self.nodes, embed_model=self.embed).storage_context.persist(
            str(self.directory)
        )
        persist_page_catalog(self.documents, self.directory)
        storage.clear_index_cache()

    async def search(self, keys):
        return await self.pipeline.search("习题2-13", "books", document_keys=keys)

    async def test_selected_documents_only(self):
        result = await self.search(["selected.pdf"])
        self.assertNotIn("UNSELECTED", result["content"])
        self.assertEqual(result["exercise_status"][0]["matches"], 1)
        self.assertEqual(result["retrieval_method"], "exercise_exact")
        self.assertEqual(self.semantic.call_count, 0)

    async def test_empty_scope_does_not_search(self):
        result = await self.search([])
        self.assertEqual(result["sources"], [])
        self.assertEqual(result["content"], "")
        self.assertEqual(self.semantic.call_count, 0)

    async def test_page_specific_evidence(self):
        result = await self.search(["selected.pdf"])
        self.assertEqual([s.get("page_index") for s in result["sources"]], [0, 1])
        for source in result["sources"]:
            self.assertEqual(source["document_key"], "selected.pdf")
            self.assertEqual(source["source_schema_version"], 1)
            self.assertEqual(source["parser_signature"], "fixture")
            self.assertEqual(len(source["source_digest"]), 64)
        self.assertIn("FIRST", result["sources"][0]["evidence_text"])
        self.assertNotIn("SECOND", result["sources"][0]["evidence_text"])
        self.assertIn("SECOND", result["sources"][1]["evidence_text"])
        self.assertNotIn("FIRST", result["sources"][1]["evidence_text"])

    async def test_exact_sources_are_consumed_as_verified_physical_pages(self):
        from deeptutor.learning.lesson_evidence import _enrich_pages
        from deeptutor.services.rag.source_pages import SourceRef

        result = await self.search(["selected.pdf"])
        candidates = []
        for source in result["sources"]:
            self.assertEqual(source.get("source_schema_version"), 1)
            self.assertIn(source.get("document_key"), ["selected.pdf"])
            ref = SourceRef(
                kb_ref="books",
                document_key=source["document_key"],
                source_digest=source["source_digest"],
                page_index=source["page_index"],
                page_label=source.get("page_label", ""),
                parser_signature=source["parser_signature"],
                node_id=source["chunk_id"],
            )
            candidates.append({"ref": ref.model_dump(), "text": source["evidence_text"]})
        with patch(
            "deeptutor.multi_user.knowledge_access.resolve_kb_document_path",
            side_effect=lambda kb, key: self.raw / key,
        ):
            pages = _enrich_pages(candidates)
        self.assertEqual(len(pages), 2)
        self.assertIn("SELECTED PAGE 1", pages[0]["text"])
        self.assertNotIn("SECOND", pages[0]["text"])
        self.assertIn("SELECTED PAGE 2", pages[1]["text"])
        self.assertNotIn("FIRST", pages[1]["text"])

    async def test_no_catalog_falls_back(self):
        (self.directory / "source_pages.json").unlink()
        result = await self.search(["selected.pdf"])
        self.assertEqual(self.semantic.call_count, 1)
        self.assertTrue(result["sources"])
        self.assertTrue(all(s["document_key"] == "selected.pdf" for s in result["sources"]))

    async def test_missing_selected_parse_falls_back(self):
        self.parses["selected.pdf"].unlink()
        result = await self.search(["selected.pdf"])
        self.assertEqual(self.semantic.call_count, 1)
        self.assertNotIn("UNSELECTED", result["content"])

    async def test_mismatched_catalog_digest_falls_back(self):
        path = self.directory / "source_pages.json"
        data = json.loads(path.read_text())
        for page in data["pages"]:
            page["source_digest"] = "0" * 64
        path.write_text(json.dumps(data))
        await self.search(["selected.pdf"])
        self.assertEqual(self.semantic.call_count, 1)

    async def test_mismatched_parser_falls_back(self):
        path = self.directory / "source_pages.json"
        data = json.loads(path.read_text())
        for page in data["pages"]:
            page["parser_signature"] = "other-parser"
        path.write_text(json.dumps(data))
        await self.search(["selected.pdf"])
        self.assertEqual(self.semantic.call_count, 1)

    async def test_missing_page_locator_falls_back(self):
        path = self.parses["selected.pdf"]
        blocks = json.loads(path.read_text())
        del blocks[-1]["page_idx"]
        path.write_text(json.dumps(blocks))
        result = await self.search(["selected.pdf"])
        self.assertEqual(self.semantic.call_count, 1)
        self.assertTrue(result["sources"])
        self.assertNotIn("UNSELECTED", result["content"])
        self.assertTrue(all(s["document_key"] == "selected.pdf" for s in result["sources"]))

    async def test_missing_image_page_locator_falls_back(self):
        path = self.parses["selected.pdf"]
        blocks = json.loads(path.read_text())
        blocks.append({"type": "image", "image_caption": ["Exercise diagram"]})
        path.write_text(json.dumps(blocks))
        result = await self.search(["selected.pdf"])
        self.assertEqual(self.semantic.call_count, 1)
        self.assertTrue(result["sources"])
        self.assertNotIn("UNSELECTED", result["content"])
        self.assertTrue(all(s["document_key"] == "selected.pdf" for s in result["sources"]))

    async def test_out_of_bounds_page_falls_back(self):
        path = self.parses["selected.pdf"]
        blocks = json.loads(path.read_text())
        blocks[-1]["page_idx"] = 99
        path.write_text(json.dumps(blocks))
        await self.search(["selected.pdf"])
        self.assertEqual(self.semantic.call_count, 1)

    async def test_nested_document_keys(self):
        self.add_pdf("nested/selected.pdf", "NESTED")
        self.persist()
        result = await self.search(["nested/selected.pdf"])
        self.assertIn("NESTED", result["content"])
        self.assertNotIn("SELECTED", result["content"])
        self.assertEqual({s["document_key"] for s in result["sources"]}, {"nested/selected.pdf"})

    async def test_scope_cannot_read_outside_raw(self):
        outside = self.root / "outside.pdf"
        outside.write_bytes((self.raw / "selected.pdf").read_bytes())
        (self.raw / "linked.pdf").symlink_to(outside)
        with patch(
            "deeptutor.services.rag.source_pages.source_digest",
            side_effect=AssertionError("must not hash outside source"),
        ):
            for key in ["../../outside.pdf", "linked.pdf", str(outside)]:
                result = await self.search([key])
                self.assertEqual(result["sources"], [])

    async def test_changed_source_digest_falls_back(self):
        source = self.raw / "selected.pdf"
        with pymupdf.open(source) as pdf:
            pdf[0].insert_text((72, 120), "CHANGED")
            pdf.saveIncr()
        await self.search(["selected.pdf"])
        self.assertEqual(self.semantic.call_count, 1)

    async def test_mixed_selected_sources_require_all_parses(self):
        self.parses["unselected.pdf"].unlink()
        await self.search(["selected.pdf", "unselected.pdf"])
        self.assertEqual(self.semantic.call_count, 1)

    async def test_wrong_catalog_schema_falls_back(self):
        path = self.directory / "source_pages.json"
        data = json.loads(path.read_text())
        data["schema_version"] = 999
        path.write_text(json.dumps(data))
        await self.search(["selected.pdf"])
        self.assertEqual(self.semantic.call_count, 1)

    async def test_unscoped_parse_only_behavior(self):
        (self.directory / "source_pages.json").unlink()
        result = await self.search(None)
        self.assertIn("SELECTED", result["content"])
        self.assertIn("UNSELECTED", result["content"])
        self.assertEqual(result["exercise_status"][0]["matches"], 2)
        self.assertEqual(self.semantic.call_count, 0)

    async def _prepare_selected_lesson(self, query, expected_method):
        """Exercise real scope, retrieval, page checks/rendering and persistence.

        Only model replies, embedding/config and temporary-resource routing are
        fixtures. In particular, candidate filtering and repair are not mocked.
        """
        from deeptutor.learning import lesson_evidence as lessons
        from deeptutor.learning.models import (
            KnowledgePoint,
            LearningModule,
            LearningProgress,
            TopicMetadata,
            TopicSource,
            TopicSourceKind,
        )
        from deeptutor.learning.storage import LearningStore

        store = LearningStore(self.root / "learning")
        store.save(
            LearningProgress(
                book_id="path",
                modules=[
                    LearningModule(
                        id="m",
                        name="Exercises",
                        order=0,
                        knowledge_points=[
                            KnowledgePoint(
                                id="kp",
                                name="Understand exercise 2-13",
                                type="memory",
                                module_id="m",
                                topic_source_ids=["selected-source"],
                            )
                        ],
                    )
                ],
            )
        )
        store.put_topic(
            TopicMetadata(path_id="path"),
            [
                TopicSource(
                    id="selected-source",
                    kind=TopicSourceKind.FILE,
                    label="Selected textbook",
                    source_id="selected.pdf",
                    metadata={"kb_name": "books", "path": "selected.pdf"},
                )
            ],
        )
        stages, methods = [], []
        original_search = LlamaIndexPipeline.search

        async def search(pipeline, q, kb, **kwargs):
            self.assertEqual(kwargs["document_keys"], ["selected.pdf"])
            result = await original_search(pipeline, q, kb, **kwargs)
            methods.append(result.get("retrieval_method", "semantic"))
            return result

        async def ask(config, instruction, payload, images=None):
            if instruction.startswith('Return JSON {"queries"'):
                stages.append("queries")
                return {"queries": [query]}
            if "Choose sources useful" in instruction:
                stages.append("select")
                return {
                    "sufficient": True,
                    "selected": [{"id": "c0", "reason": "Exercise", "neighbor": 0}],
                }
            if "Inspect the supplied original PDF pixels" in instruction:
                stages.append("inspect")
                self.assertTrue(images)
                self.assertTrue(any(p.get("type") == "image_url" for p in images))
                return {
                    "usable": True,
                    "observations": "Readable",
                    "limitations": "Model simulated",
                }
            self.fail(f"Unexpected model boundary: {instruction[:80]}")

        def resolve_document(kb, key):
            source = (self.raw / key).resolve()
            if kb == "books" and source.is_relative_to(self.raw.resolve()) and source.is_file():
                return source
            return None

        with ExitStack() as stack:
            for p in [
                patch(
                    "deeptutor.multi_user.knowledge_access.resolve_for_rag",
                    side_effect=lambda kb: (
                        SimpleNamespace(base_dir=self.kb.parent, name="books")
                        if kb == "books"
                        else None
                    ),
                ),
                patch(
                    "deeptutor.multi_user.knowledge_access.resolve_kb_document_path",
                    side_effect=resolve_document,
                ),
                patch(
                    "deeptutor.services.rag.embedding_signature.signature_from_embedding_config",
                    return_value=None,
                ),
                patch(
                    "deeptutor.services.rag.index_versioning.resolve_storage_dir_for_read",
                    return_value=self.directory,
                ),
                patch.object(LlamaIndexPipeline, "_configure_settings", return_value=None),
                patch.object(LlamaIndexPipeline, "_current_signature", return_value=None),
                patch.object(LlamaIndexPipeline, "search", search),
                patch("deeptutor.services.llm.capabilities.supports_vision", return_value=True),
                patch.object(lessons, "_ask", ask),
            ]:
                stack.enter_context(p)
            result = await lessons.prepare_lesson(
                store, "path", "kp", SimpleNamespace(model="vision-fixture", binding="openai")
            )

        self.assertEqual(result["status"], "ready")
        self.assertEqual(stages, ["queries", "select", "inspect"])
        self.assertEqual(methods, [expected_method])
        self.assertTrue(result["sources"])
        self.assertEqual({s["ref"]["document_key"] for s in result["sources"]}, {"selected.pdf"})
        persisted = store.load("path").lesson_evidence["kp"]
        self.assertEqual(persisted["status"], "ready")
        self.assertEqual(persisted["sources"], result["sources"])
        self.assertEqual(self.semantic.call_count, 0 if expected_method == "exercise_exact" else 1)

    async def test_prepare_lesson_numbered_query_persists_selected_evidence(self):
        await self._prepare_selected_lesson("习题2-13", "exercise_exact")

    async def test_prepare_lesson_single_document_numbered_query(self):
        # Missing page provenance used to fail even without another raw PDF.
        (self.raw / "unselected.pdf").unlink()
        await self._prepare_selected_lesson("习题2-13", "exercise_exact")

    async def test_prepare_lesson_conceptual_query_control(self):
        await self._prepare_selected_lesson("Explain the material", "semantic")
