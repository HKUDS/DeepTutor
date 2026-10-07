"""Synthetic numbered-exercise parsing, source scope and retrieval regressions."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from deeptutor.services.rag.pipelines.llamaindex.exercise_lookup import (
    _source_hash,
    collect_exercises,
    lookup_exercises,
    requested_exercises,
)


def text(s, page=1, **kwargs):
    return {"type": "text", "text": s, "original_page": page, **kwargs}


class ExerciseLookupTests(unittest.TestCase):
    def test_number_intent_and_exclusions(self):
        self.assertEqual(requested_exercises("2-13 2－14")[0], [(2, 13), (2, 14)])
        self.assertEqual(requested_exercises("帮我找第二章第13题")[0], [(2, 13)])
        self.assertEqual(requested_exercises("习题 9.1")[0], [(9, 1)])
        self.assertEqual(requested_exercises("帮我找2-13")[0], [(2, 13)])
        self.assertEqual(requested_exercises("习题2-13至2-15")[0], [(2, 13), (2, 14), (2, 15)])
        for query in [
            "解释公式2-13",
            "图2-13是什么意思",
            "第2.13节讲什么",
            "计算 2-3",
            "重力加速度9.8",
            "解释随机误差",
        ]:
            self.assertEqual(requested_exercises(query)[0], [], query)

    def test_join_cross_page_table_and_stop_at_next_problem(self):
        blocks = [
            text("第二章 测量"),
            text("习题"),
            text("2-14 测得值如下："),
            {"type": "equation", "text": "甲 = 20", "original_page": 1},
            text("56", type="page_number"),
            {"type": "header", "text": "第二章 测量", "original_page": 2},
            {"type": "table", "table_body": "<table>乙 = 25</table>", "original_page": 2},
            text("试求测量结果。", 2),
            text("2-15 下一题", 2),
        ]
        found = collect_exercises(blocks)
        self.assertEqual(len(found), 2)
        self.assertEqual(found[0].pages, {1, 2})
        self.assertEqual(len(found[0].parts), 4)
        self.assertNotIn("56", "\n".join(found[0].parts))

    def test_chapter_only_numbers_multiple_questions_and_footer(self):
        found = collect_exercises(
            [
                text("目录\n第二章 解析函数……13"),
                text("第二章 解析函数"),
                text("习题"),
                text("13. 第一题\n14. 第二题"),
                {"type": "header", "text": "习题"},
                text("续文"),
                text("第三章 复变积分"),
                text("13. 不属于习题"),
            ]
        )
        self.assertEqual([(x.chapter, x.number) for x in found], [(2, 13), (2, 14)])
        self.assertIn("续文", found[1].parts)

    def test_figure_equation_and_section_numbers_are_not_questions(self):
        found = collect_exercises(
            [
                text("第二章 测量"),
                text("2.13 正文小节", text_level=2),
                text("图2-13"),
                text("习题"),
                text("2-13 求数值"),
                text("图2-14"),
                {"type": "equation", "text": "公式2-16"},
                text("50.82, 50.83;"),
                text("2-14 下一题"),
            ]
        )
        self.assertEqual([(x.chapter, x.number) for x in found], [(2, 13), (2, 14)])
        self.assertIn("公式2-16", found[0].parts)
        self.assertIn("50.82, 50.83;", found[0].parts)

    def test_problem_types_and_images_are_preserved(self):
        found = collect_exercises(
            [
                text("第二章 磁场"),
                text("思 考 题"),
                text("2-13 电子"),
                {"type": "image", "image_caption": ["思考题2-13"], "original_page": 2},
                text("续文"),
                text("习 题"),
                text("2-13 球面"),
            ]
        )
        self.assertEqual([x.kind for x in found], ["思考题", "习题"])
        self.assertTrue(found[0].images)
        self.assertFalse(found[1].images)

    def test_missing_chapter_title_and_body_cross_reference(self):
        found = collect_exercises(
            [
                text("第一章 绪论"),
                text("习题"),
                text("1.1 第一题"),
                text("第二章 磁场", text_level=2),
                text("第一章4.6节已证明，当条件满足时成立。"),
                text("习题"),
                text("2-13 球面"),
                text("9.1 线性化", text_level=2),
                text("习题"),
                text("9.1 扰动"),
            ]
        )
        self.assertEqual([(x.chapter, x.number) for x in found], [(1, 1), (2, 13), (9, 1)])

    def test_missing_next_label_does_not_merge_distinct_question(self):
        found = collect_exercises(
            [
                text("第二章 磁场"),
                text("习题"),
                text("2-18 本题内容"),
                text("习题2-19"),
                text("另一道题的残缺后半段"),
                text("2-20 下一题"),
            ]
        )
        self.assertEqual(found[0].parts, ["2-18 本题内容"])

    def test_cache_scope_incomplete_parse_and_missing_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            kb = root / "knowledge_bases" / "one"
            raw = kb / "raw"
            raw.mkdir(parents=True)
            source = raw / "book.pdf"
            source.write_bytes(b"fake pdf for hash")
            st = source.stat()
            digest = _source_hash(str(source), st.st_mtime_ns, st.st_size)
            cache = root / "parse_cache"
            folder = cache / digest[:2] / digest / "sig"
            folder.mkdir(parents=True)
            (folder / "full_content_list.json").write_text(
                json.dumps(
                    [
                        text("第二章 磁场"),
                        text("思考题"),
                        text("2-13 电子"),
                        text("习题"),
                        text("2-13 球面"),
                    ]
                )
            )
            self.assertIsNone(lookup_exercises("习题2-13", kb, cache))
            (folder / "manifest.json").write_text(json.dumps({"source_hash": digest}))
            result = lookup_exercises("2-13", kb, cache)
            self.assertEqual(result["exercise_status"][0]["status"], "ambiguous")
            self.assertEqual(len(result["sources"]), 2)
            result = lookup_exercises("习题2-13 2-14", kb, cache)
            self.assertEqual(
                [x["status"] for x in result["exercise_status"]], ["found", "not_found"]
            )
            self.assertIn("球面", result["content"])
            self.assertNotIn("电子", result["content"])
            other = root / "knowledge_bases" / "two"
            (other / "raw").mkdir(parents=True)
            self.assertIsNone(lookup_exercises("习题2-13", other, cache))
            self.assertIsNone(lookup_exercises("图2-13", kb, cache))


class PipelineRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_parse_keeps_existing_retrieval(self) -> None:
        from deeptutor.services.rag.pipelines.llamaindex.pipeline import LlamaIndexPipeline

        with tempfile.TemporaryDirectory() as tmp:
            pipeline = LlamaIndexPipeline(kb_base_dir=tmp)
            with patch.object(
                pipeline, "_configure_settings", side_effect=RuntimeError("normal retrieval")
            ):
                with self.assertRaisesRegex(RuntimeError, "normal retrieval"):
                    await pipeline.search("习题2-13", "no-parsed-source")

    async def test_lookup_error_keeps_existing_retrieval(self) -> None:
        from deeptutor.services.rag.pipelines.llamaindex.pipeline import LlamaIndexPipeline

        with tempfile.TemporaryDirectory() as tmp:
            pipeline = LlamaIndexPipeline(kb_base_dir=tmp)
            with (
                patch.object(
                    pipeline, "_configure_settings", side_effect=RuntimeError("normal retrieval")
                ),
                patch(
                    "deeptutor.services.rag.pipelines.llamaindex.exercise_lookup.lookup_exercises",
                    side_effect=OSError("unreadable cache"),
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "normal retrieval"):
                    await pipeline.search("习题2-13", "kb")

    async def test_exact_lookup_precedes_embedding_and_topk(self):
        from deeptutor.services.rag.pipelines.llamaindex.pipeline import LlamaIndexPipeline

        expected = {
            "content": "all eight questions",
            "sources": list(range(8)),
            "retrieval_method": "exercise_exact",
        }
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "kb").mkdir()
            p = LlamaIndexPipeline(kb_base_dir=tmp)
            with patch.object(
                p, "_configure_settings", side_effect=AssertionError("No embedding allowed")
            ):
                with patch(
                    "deeptutor.services.rag.pipelines.llamaindex.exercise_lookup.lookup_exercises",
                    return_value=expected,
                ):
                    result = await p.search("习题2-13", "kb", top_k=1)
            self.assertEqual(result, expected)

    async def test_concept_queries_keep_existing_retrieval(self):
        from deeptutor.services.rag.pipelines.llamaindex.pipeline import LlamaIndexPipeline

        p = LlamaIndexPipeline(kb_base_dir="/tmp")
        with patch.object(p, "_configure_settings", side_effect=RuntimeError("original path")):
            with self.assertRaisesRegex(RuntimeError, "original path"):
                await p.search("解释高斯定理", "kb")


if __name__ == "__main__":
    unittest.main(verbosity=2)
