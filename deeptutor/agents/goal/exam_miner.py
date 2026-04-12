"""Exam material analyzer for goal mode."""

from __future__ import annotations

import base64
from collections import Counter
import json
import re
from typing import Any

from deeptutor.services.llm import complete as llm_complete
from deeptutor.utils.json_parser import parse_json_response


class ExamMiner:
    """Extract high-frequency exam patterns from mixed materials."""

    async def analyze(
        self,
        *,
        pasted_text: str,
        file_texts: list[dict[str, str]],
        image_files: list[dict[str, Any]],
        language: str = "en",
    ) -> dict[str, Any]:
        text_chunks = []
        if pasted_text.strip():
            text_chunks.append({"source": "pasted_text", "text": pasted_text.strip()})
        text_chunks.extend(file_texts)

        image_texts = await self._extract_image_texts(image_files)
        text_chunks.extend(image_texts)

        corpus = "\n\n".join(
            f"[SOURCE: {item.get('source', 'unknown')}]\n{item.get('text', '').strip()}"
            for item in text_chunks
            if item.get("text", "").strip()
        ).strip()
        if not corpus:
            return {
                "question_count": 0,
                "knowledge_points": [],
                "question_types": [],
                "difficulty_distribution": {},
                "insights": ["No valid question text was extracted. Upload clearer materials or paste the original questions."],
                "samples": [],
                "source_breakdown": {"text_sources": len(file_texts), "image_sources": len(image_files)},
            }

        extracted = await self._extract_structured_questions(corpus, language)
        questions = self._normalize_questions(extracted.get("questions", []))
        if not questions:
            questions = self._fallback_questions(corpus)

        knowledge_counter = Counter()
        type_counter = Counter()
        diff_counter = Counter()
        for question in questions:
            q_type = str(question.get("question_type", "")).strip() or "Unclassified"
            difficulty = str(question.get("difficulty", "")).strip() or "unknown"
            type_counter[q_type] += 1
            diff_counter[difficulty] += 1
            for point in question.get("knowledge_points", []):
                normalized = str(point).strip()
                if normalized:
                    knowledge_counter[normalized] += 1

        total = max(1, len(questions))
        top_knowledge = [
            {
                "name": name,
                "count": count,
                "ratio": round(count / total, 4),
            }
            for name, count in knowledge_counter.most_common(12)
        ]
        top_types = [
            {
                "name": name,
                "count": count,
                "ratio": round(count / total, 4),
            }
            for name, count in type_counter.most_common(8)
        ]

        insights = []
        if top_knowledge:
            insights.append(f"Top 3 high-yield knowledge points: {', '.join(item['name'] for item in top_knowledge[:3])}")
        if top_types:
            insights.append(f"Top 3 high-yield question types: {', '.join(item['name'] for item in top_types[:3])}")
        if len(questions) < 8:
            insights.append("Sample size is small (<8). Add more past papers from the last 3-5 years for better stability.")
        else:
            insights.append("Sample size passed the basic statistical threshold and can support exam-prep prioritization.")

        return {
            "question_count": len(questions),
            "knowledge_points": top_knowledge,
            "question_types": top_types,
            "difficulty_distribution": dict(diff_counter),
            "insights": insights,
            "samples": [q.get("stem", "") for q in questions[:5]],
            "source_breakdown": {
                "text_sources": len(file_texts) + (1 if pasted_text.strip() else 0),
                "image_sources": len(image_files),
            },
        }

    async def _extract_image_texts(self, image_files: list[dict[str, Any]]) -> list[dict[str, str]]:
        outputs: list[dict[str, str]] = []
        for image in image_files[:10]:
            data = image.get("data")
            if not isinstance(data, (bytes, bytearray)):
                continue
            mime = str(image.get("content_type", "image/png") or "image/png")
            base64_data = base64.b64encode(bytes(data)).decode("utf-8")
            data_url = f"data:{mime};base64,{base64_data}"
            try:
                response = await llm_complete(
                    prompt="",
                    system_prompt="",
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": (
                                        "You are an OCR and question-structure assistant. Read question text from the image and output plain text only."
                                        "Do not explain, do not add content, and do not use markdown. If unclear, output only the readable part."
                                    ),
                                },
                                {"type": "image_url", "image_url": {"url": data_url}},
                            ],
                        }
                    ],
                    temperature=0.0,
                    max_tokens=1400,
                )
                text = str(response or "").strip()
                if text:
                    outputs.append({"source": image.get("name", "image"), "text": text})
            except Exception:
                continue
        return outputs

    async def _extract_structured_questions(self, corpus: str, language: str) -> dict[str, Any]:
        bounded = corpus[:36000]
        system_prompt = (
            "You are an exam data annotator. Extract questions from materials and return structured JSON only."
        )
        user_prompt = (
            f"[Material]\n{bounded}\n\n"
            "Return JSON with key `questions`, where each item has stem, question_type, knowledge_points, difficulty."
        )
        raw = await llm_complete(
            prompt=user_prompt,
            system_prompt=system_prompt,
            temperature=0.1,
            max_tokens=2000,
            response_format={"type": "json_object"},
        )
        parsed = parse_json_response(raw, fallback={"questions": []})
        return parsed if isinstance(parsed, dict) else {"questions": []}

    def _normalize_questions(self, questions: list[Any]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for item in questions:
            if not isinstance(item, dict):
                continue
            stem = re.sub(r"\s+", " ", str(item.get("stem", "")).strip())
            if len(stem) < 6:
                continue
            q_type = str(item.get("question_type", "")).strip() or "Unclassified"
            difficulty = str(item.get("difficulty", "")).strip().lower()
            if difficulty not in {"easy", "medium", "hard"}:
                difficulty = "medium"
            points_raw = item.get("knowledge_points", [])
            if isinstance(points_raw, list):
                points = [str(value).strip() for value in points_raw if str(value).strip()]
            else:
                points = [str(points_raw).strip()] if str(points_raw).strip() else []
            normalized.append(
                {
                    "stem": stem,
                    "question_type": q_type,
                    "knowledge_points": points[:5],
                    "difficulty": difficulty,
                }
            )
        return normalized

    def _fallback_questions(self, corpus: str) -> list[dict[str, Any]]:
        blocks = [
            block.strip()
            for block in re.split(r"(?:\n\s*\n|(?=\n?\d+[\.、\)])|(?=\n?第?\d+题))", corpus)
            if block.strip()
        ]
        questions: list[dict[str, Any]] = []
        for block in blocks[:30]:
            text = re.sub(r"\s+", " ", block)
            if len(text) < 10:
                continue
            questions.append(
                {
                    "stem": text[:220],
                    "question_type": self._infer_question_type(text),
                    "knowledge_points": self._guess_points(text),
                    "difficulty": "medium",
                }
            )
        return questions

    def _infer_question_type(self, text: str) -> str:
        lowered = text.lower()
        if re.search(r"证明|prove", lowered):
            return "Proof"
        if re.search(r"选择|单选|多选|option|a\.|b\.", lowered):
            return "Multiple Choice"
        if re.search(r"编程|代码|program|java|python|c\+\+", lowered):
            return "Programming"
        if re.search(r"计算|求|解|evaluate|compute", lowered):
            return "Computation"
        return "Short Answer"

    def _guess_points(self, text: str) -> list[str]:
        candidates = re.findall(r"[\u4e00-\u9fffA-Za-z]{2,12}", text)
        stopwords = {"以下", "关于", "已知", "其中", "并且", "的是", "进行", "给出", "题目", "请问"}
        points: list[str] = []
        for token in candidates:
            if token in stopwords or token.isdigit():
                continue
            if token not in points:
                points.append(token)
            if len(points) >= 4:
                break
        return points


__all__ = ["ExamMiner"]
