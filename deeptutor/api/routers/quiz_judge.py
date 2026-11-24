"""AI judge WebSocket — grades a learner's quiz answer.

Mounted on its own (without router-level HTTP auth dependencies) because
WebSocket upgrades cannot use FastAPI's HTTP dependency injection, so we
rely on ``ws_require_auth`` inside the handler — mirroring the pattern
used by ``unified_ws``.
"""

from __future__ import annotations

import asyncio
import base64 as _b64
import json
import logging
import re
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from deeptutor.learning.semantic_assessment import FINAL_CONFIDENCE, Verdict
from deeptutor.services.config import PROJECT_ROOT, load_config_with_main
from deeptutor.services.llm import stream as llm_stream
from deeptutor.services.settings.interface_settings import get_response_language
from deeptutor.utils.error_utils import format_exception_message

logger = logging.getLogger(__name__)
_config = load_config_with_main("main.yaml", PROJECT_ROOT)

router = APIRouter()


_JUDGE_SYSTEM_PROMPTS = {
    "zh": (
        "你是一名严谨且鼓励学习者的助教，正在批改一道测验题。"
        "请基于题目、参考答案与解析，对学习者的作答给出针对性的判定与反馈。\n\n"
        "回答要求：\n"
        "- 先用一行明确结论：✅ 正确 / ⚠️ 部分正确 / ❌ 不正确，并简短点明关键判定依据。\n"
        "- 然后分条列出：哪里做对了、哪里出错或缺漏、应该如何改正。\n"
        "- 若题目本身有多种合理答案，请承认学习者的合理之处。\n"
        "- 直接以学习者的作答为对象，不要泛泛而谈。\n"
        "- 全程使用中文。"
    ),
    "en": (
        "You are a rigorous yet encouraging teaching assistant grading a learner's quiz answer. "
        "Use the question, reference answer, and explanation to deliver a targeted assessment.\n\n"
        "Requirements:\n"
        "- Open with one line that states the verdict: ✅ Correct / ⚠️ Partially correct / ❌ Incorrect, "
        "and the key reason.\n"
        "- Then list: what the learner got right, what is wrong or missing, and how to fix it.\n"
        "- If multiple reasonable answers exist, acknowledge what the learner did well.\n"
        "- Speak directly to the learner's submission — do not give a generic lecture.\n"
        "- Reply in English."
    ),
    "de": (
        "Du bist eine gründliche, aber ermutigende Lehrkraft und bewertest die Antwort "
        "einer lernenden Person auf eine Quizfrage. Stütze dich auf Frage, Musterlösung "
        "und Erklärung.\n\n"
        "Anforderungen:\n"
        "- Beginne mit einer Zeile, die das Ergebnis nennt: ✅ Richtig / ⚠️ Teilweise richtig "
        "/ ❌ Falsch, und kurz den entscheidenden Grund.\n"
        "- Liste danach auf: was richtig ist, was falsch ist oder fehlt und wie es sich verbessern lässt.\n"
        "- Wenn mehrere sinnvolle Antworten möglich sind, erkenne an, was gut gelöst ist.\n"
        "- Sprich direkt über diese Antwort, ohne allgemeinen Vortrag.\n"
        "- Antworte auf Deutsch und duze die lernende Person."
    ),
    "uk": (
        "Ти вимогливий, але доброзичливий асистент учителя, який перевіряє відповідь учня "
        "на тестове завдання. Спирайся на умову, еталонну відповідь і пояснення.\n\n"
        "Вимоги до відповіді:\n"
        "- Почни одним рядком із вердиктом: ✅ Правильно / ⚠️ Частково правильно / ❌ Неправильно "
        "і коротко назви головну підставу.\n"
        "- Далі по пунктах: що учень зробив правильно, де помилка або чого бракує, як це виправити.\n"
        "- Якщо можливі кілька слушних відповідей, визнай те, що учень зробив добре.\n"
        "- Звертайся саме до цієї відповіді, без загальних лекцій.\n"
        "- Відповідай українською."
    ),
    "pt": (
        "Você é um assistente de ensino rigoroso e encorajador que avalia a resposta de um aluno a um teste. "
        "Use a pergunta, a resposta de referência e a explicação para fornecer uma avaliação direcionada.\n\n"
        "Requisitos:\n"
        "- Comece com uma linha informando o veredito: ✅ Correto / ⚠️ Parcialmente correto / ❌ Incorreto, "
        "e o motivo principal.\n"
        "- Em seguida, liste: o que o aluno acertou, o que está errado ou faltando e como corrigir.\n"
        "- Se houver várias respostas válidas, reconheça os acertos do aluno.\n"
        "- Comente diretamente a resposta enviada pelo aluno — não dê uma explicação genérica.\n"
        "- Responda em português."
    ),
    "vi": (
        "Bạn là trợ giảng nghiêm túc nhưng luôn khích lệ, đang chấm câu trả lời của người học "
        "cho một câu hỏi kiểm tra. Hãy dựa vào câu hỏi, đáp án tham khảo và phần giải thích "
        "để đưa ra nhận xét sát với bài làm.\n\n"
        "Yêu cầu:\n"
        "- Mở đầu bằng một dòng nêu kết luận: ✅ Đúng / ⚠️ Đúng một phần / ❌ Sai, "
        "kèm lý do chính.\n"
        "- Sau đó nêu: người học đã làm đúng gì, chỗ nào sai hoặc còn thiếu, và cách sửa.\n"
        "- Nếu có nhiều đáp án hợp lý, hãy ghi nhận những gì người học đã làm tốt.\n"
        "- Nhận xét trực tiếp vào bài làm này, không giảng lý thuyết chung chung.\n"
        "- Trả lời bằng tiếng Việt."
    ),
    "fr": (
        "Tu es un assistant pédagogique rigoureux et encourageant qui corrige la réponse "
        "d’un apprenant à un quiz. Appuie-toi sur la question, la réponse de référence et "
        "l’explication pour fournir une évaluation ciblée.\n\n"
        "Exigences :\n"
        "- Commence par une ligne indiquant le verdict : ✅ Correct / ⚠️ Partiellement correct / "
        "❌ Incorrect, avec la raison principale.\n"
        "- Liste ensuite : ce que l’apprenant a juste, ce qui est faux ou manquant, et comment corriger.\n"
        "- Si plusieurs réponses raisonnables existent, reconnais ce que l’apprenant a bien fait.\n"
        "- Adresse-toi directement à la réponse de l’apprenant, sans discours générique.\n"
        "- Réponds en français et tutoie l’apprenant."
    ),
    "tr": "Siz titiz ama cesaretlendirici bir öğretim asistanısınız ve bir öğrencinin test sorusuna "
    "verdiği yanıtı değerlendiriyorsunuz. Soruyu, örnek yanıtı ve açıklamayı temel alın.\n\n"
    "Yanıt gereksinimleri:\n"
    "- Sonucu belirten tek bir satırla başlayın: ✅ Doğru / ⚠️ Kısmen doğru / ❌ Yanlış "
    "ve temel gerekçeyi kısaca yazın.\n"
    "- Ardından madde madde yazın: öğrencinin neyi doğru yaptığı, neyin yanlış ya da eksik olduğu "
    "ve nasıl düzeltileceği.\n"
    "- Birden fazla makul yanıt mümkünse öğrencinin iyi yaptığı yönleri belirtin.\n"
    "- Doğrudan bu yanıta odaklanın, genel bir ders vermeyin.\n"
    '- Öğrenciye "siz" diye hitap edin.\n'
    "- Yanıtı ve geri bildirimi Türkçe yazın.",
    "it": (
        "Sei un assistente didattico rigoroso ma incoraggiante che corregge la risposta "
        "di uno studente a una domanda di un quiz. Basati sulla domanda, sulla risposta di riferimento "
        "e sulla spiegazione per fornire una valutazione mirata.\n\n"
        "Requisiti:\n"
        "- Inizia con una riga che esprime il verdetto: ✅ Corretto / ⚠️ Parzialmente corretto / ❌ Non corretto, "
        "e la motivazione principale.\n"
        "- Quindi elenca: cosa lo studente ha fatto bene, cosa è errato o mancante e come correggerlo.\n"
        "- Se esistono più risposte ragionevoli, riconosci i punti validi dello studente.\n"
        "- Rivolgiti direttamente alla risposta dello studente, senza lezioni generiche.\n"
        "- Rispondi in italiano."
    ),
    "hu": (
        "Ön szigorú, de bátorító tanársegéd, aki egy tanuló kvízkérdésre adott válaszát értékeli. "
        "A kérdés, a mintaválasz és a magyarázat alapján adjon célzott értékelést.\n\n"
        "Követelmények:\n"
        "- Egy sorral kezdje az ítélettel: ✅ Helyes / ⚠️ Részben helyes / ❌ Helytelen, "
        "és a döntő indokkal.\n"
        "- Ezután sorolja fel: mit tudott jól a tanuló, mi hibás vagy hiányzik, és hogyan javítható.\n"
        "- Ha több elfogadható válasz is létezik, ismerje el, amit a tanuló jól tett.\n"
        "- Közvetlenül a tanuló megoldására reagáljon — ne tartson általános előadást.\n"
        "- Magyarul válaszoljon."
    ),
}

# The set of languages the judge can speak IS the set of system prompts it has.
# Deriving it here means adding a language is one edit (add a prompt), not three
# — the previous ("zh", "en") literals were repeated in the whitelist, the
# fallback and the frontend, and a Ukrainian UI silently got English feedback.
SUPPORTED_JUDGE_LANGUAGES: frozenset[str] = frozenset(_JUDGE_SYSTEM_PROMPTS)


# Appended to every language's system prompt. The prose above stays the
# learner-facing judgment; this trailer is the machine-readable verdict the
# server strips from the stream and sends as a separate ``verdict`` frame.
_VERDICT_CONTRACT = (
    "After your feedback, end your reply with exactly one machine-readable verdict "
    "and nothing after it:\n"
    '<verdict>{"result": "correct|partial|incorrect|ungraded", "confidence": 0.0-1.0, '
    '"feedback": "one short sentence", "steps": [{"label": "...", "ok": true, '
    '"comment": "..."}]}</verdict>\n'
    "- result: correct = fully right; partial = right approach or some parts right; "
    "incorrect = wrong; ungraded = you cannot judge it (e.g. unreadable image, "
    "missing reference).\n"
    "- confidence: how sure you are of the result.\n"
    "- steps: for calculations or multi-part answers, one entry per solution step or "
    "subtask (at most 12); otherwise an empty list.\n"
    '- Add "awarded_points" and "max_points" only when the question or the reference '
    "answer states points; never invent a point scheme.\n"
    "- Write label, comment and feedback in the language of your reply. Valid JSON only."
)

_VERDICT_OPEN = "<verdict>"
_VERDICT_OPEN_RE = re.compile(re.escape(_VERDICT_OPEN), re.IGNORECASE)
_VERDICT_CLOSE_RE = re.compile(r"</verdict\s*>", re.IGNORECASE)
_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


class _VerdictTrailerSplitter:
    """Separate streamed prose from the trailing ``<verdict>`` block.

    Text is released as soon as it cannot be the start of the opening tag,
    so streaming stays incremental and the trailer never reaches the client.
    """

    def __init__(self) -> None:
        self._pending = ""
        self._trailer: str | None = None

    def feed(self, chunk: str) -> str:
        if self._trailer is not None:
            self._trailer += chunk
            return ""
        text = self._pending + chunk
        match = _VERDICT_OPEN_RE.search(text)
        if match:
            self._pending = ""
            self._trailer = text[match.end() :]
            return text[: match.start()]
        keep = next(
            (
                n
                for n in range(min(len(_VERDICT_OPEN) - 1, len(text)), 0, -1)
                if _VERDICT_OPEN.startswith(text[-n:].lower())
            ),
            0,
        )
        self._pending = text[len(text) - keep :] if keep else ""
        return text[: len(text) - keep]

    def finish(self) -> tuple[str, str | None]:
        """Return the held-back prose and the raw trailer (``None`` if absent)."""
        tail, self._pending = self._pending, ""
        return tail, self._trailer


class _JudgeStep(BaseModel):
    model_config = ConfigDict(extra="ignore")
    label: str = Field(min_length=1, max_length=200)
    ok: bool
    comment: str = Field(default="", max_length=600)


class _JudgeVerdict(Verdict):
    """The learning-path ``Verdict`` plus quiz-only points and step feedback."""

    model_config = ConfigDict(extra="ignore")
    # The prose above the trailer is the feedback; the summary is optional.
    feedback: str = Field(default="", max_length=2000)
    awarded_points: float | None = Field(default=None, ge=0)
    max_points: float | None = Field(default=None, gt=0)
    steps: list[_JudgeStep] = Field(default_factory=list, max_length=12)


def _ungraded(reason: str) -> dict[str, Any]:
    return {
        "result": "ungraded",
        "final": False,
        "is_correct": None,
        "confidence": 0.0,
        "steps": [],
        "reason": reason,
    }


def parse_judge_verdict(raw: str | None, *, vision_unavailable: bool = False) -> dict[str, Any]:
    """Turn the raw trailer body into the ``verdict`` frame payload.

    A missing or invalid trailer is ``ungraded`` — the judge never guesses
    ``correct``. The ``Verdict.receipt`` confidence gate applies unchanged.
    """
    if raw is None:
        return _ungraded("vision_unavailable" if vision_unavailable else "missing_verdict")
    body = _VERDICT_CLOSE_RE.split(raw, maxsplit=1)[0].strip()
    body = _JSON_FENCE_RE.sub("", body).strip()
    try:
        parsed = _JudgeVerdict.model_validate(json.loads(body))
    except (ValueError, ValidationError):
        return _ungraded("vision_unavailable" if vision_unavailable else "invalid_verdict")

    receipt = parsed.receipt()
    verdict: dict[str, Any] = {
        "result": receipt["result"],
        "final": receipt["final"],
        "is_correct": receipt["is_correct"],
        "confidence": receipt["confidence"],
        "feedback": receipt["feedback"],
        "steps": [step.model_dump() for step in parsed.steps],
    }
    if vision_unavailable:
        verdict.update(result="ungraded", final=False, is_correct=None)
        verdict["reason"] = "vision_unavailable"
    elif parsed.result != "ungraded" and parsed.confidence < FINAL_CONFIDENCE:
        verdict["reason"] = "low_confidence"
    points_valid = (
        parsed.awarded_points is not None
        and parsed.max_points is not None
        and parsed.awarded_points <= parsed.max_points
    )
    if verdict["final"] and points_valid:
        verdict["awarded_points"] = parsed.awarded_points
        verdict["max_points"] = parsed.max_points
    return verdict


def _build_judge_user_prompt(
    *,
    language: str,
    question: str,
    question_type: str,
    options: dict | None,
    correct_answer: str,
    explanation: str,
    user_answer: str,
    has_image: bool,
    image_count: int = 0,
    images_unreadable: bool = False,
) -> str:
    options_block = ""
    if options:
        try:
            options_block = "\n".join(f"  {k}. {v}" for k, v in options.items())
        except Exception:
            options_block = ""
    if language == "zh":
        parts = [
            f"题目类型：{question_type or 'unknown'}",
            f"题干：\n{question}",
        ]
        if options_block:
            parts.append(f"选项：\n{options_block}")
        if correct_answer:
            parts.append(f"参考答案：\n{correct_answer}")
        if explanation:
            parts.append(f"参考解析：\n{explanation}")
        parts.append(
            "学习者作答：\n"
            + (
                user_answer.strip()
                if user_answer and user_answer.strip()
                else "（仅提交了图片，无文字作答）"
            )
        )
        if has_image:
            count_text = (
                f"学习者另附了 {image_count} 张图片作为作答内容"
                if image_count > 1
                else "学习者另附了一张图片作为作答内容"
            )
            if images_unreadable:
                parts.append(
                    f"{count_text}，但当前模型无法读取图片。"
                    "请在回复中明确说明这一点，只评判文字作答，并将 result 设为 ungraded。"
                )
            else:
                parts.append(f"{count_text}，请结合图片中的文字/公式/草图一并判定。")
        parts.append("请针对该学习者的具体作答给出 AI 评判。")
    elif language == "fr":
        parts = [
            f"Type de question : {question_type or 'inconnu'}",
            f"Question :\n{question}",
        ]
        if options_block:
            parts.append(f"Options :\n{options_block}")
        if correct_answer:
            parts.append(f"Réponse de référence :\n{correct_answer}")
        if explanation:
            parts.append(f"Explication de référence :\n{explanation}")
        parts.append(
            "Réponse de l’apprenant :\n"
            + (
                user_answer.strip()
                if user_answer and user_answer.strip()
                else "(seule une image a été soumise, sans réponse écrite)"
            )
        )
        if has_image and images_unreadable:
            parts.append(
                "L’apprenant a joint des images à sa réponse, mais le modèle actif ne peut pas "
                "lire d’images. Dis-le explicitement, n’évalue que la "
                "réponse écrite et mets result à ungraded."
            )
        elif has_image:
            if image_count > 1:
                parts.append(
                    f"L’apprenant a joint {image_count} images à sa réponse. "
                    "Lis leur texte, leurs formules et leurs croquis, et prends-les en compte "
                    "dans l’évaluation."
                )
            else:
                parts.append(
                    "L’apprenant a joint une image à sa réponse. Lis son texte, ses formules "
                    "et ses croquis, et prends-la en compte dans l’évaluation."
                )
        parts.append("Produis une évaluation qui porte sur la réponse précise de cet apprenant.")
    else:
        parts = [
            f"Question type: {question_type or 'unknown'}",
            f"Question:\n{question}",
        ]
        if options_block:
            parts.append(f"Options:\n{options_block}")
        if correct_answer:
            parts.append(f"Reference answer:\n{correct_answer}")
        if explanation:
            parts.append(f"Reference explanation:\n{explanation}")
        parts.append(
            "Learner's answer:\n"
            + (
                user_answer.strip()
                if user_answer and user_answer.strip()
                else "(only an image was submitted, no typed answer)"
            )
        )
        if has_image and images_unreadable:
            parts.append(
                f"The learner attached {'images' if image_count > 1 else 'an image'} as part "
                "of the answer, but the active model cannot read images. Say so explicitly, "
                "judge only the typed answer, and set result to ungraded."
            )
        elif has_image:
            if image_count > 1:
                parts.append(
                    f"The learner attached {image_count} images as part of the answer. "
                    "Read their text/formulas/sketches and factor them into the judgment."
                )
            else:
                parts.append(
                    "The learner attached an image as part of the answer. "
                    "Read its text/formulas/sketches and factor it into the judgment."
                )
        parts.append("Produce an AI judgment that addresses this learner's specific answer.")
    return "\n\n".join(parts)


async def _build_multimodal_user_content(
    *,
    text: str,
    image_records: list[dict[str, str]],
) -> list[dict[str, Any]]:
    """Compose an OpenAI-style content-parts array with text + image blocks.

    For ``url``-only records we resolve local AttachmentStore paths to
    base64 here (most providers can fetch external URLs themselves, but
    locally-hosted ``/files/attachments/...`` is only reachable from the
    browser). Falls back to passing the URL through when resolution is
    not possible.
    """
    from urllib.parse import unquote, urlparse

    from deeptutor.services.storage import get_attachment_store

    content: list[dict[str, Any]] = [{"type": "text", "text": text}]
    attachment_store = get_attachment_store()
    resolve = getattr(attachment_store, "resolve_path", None)

    for record in image_records:
        b64 = record.get("base64") or ""
        url = record.get("url") or ""
        filename = record.get("filename") or "answer.png"
        mime_type = record.get("mime_type") or _guess_image_mime(filename)

        if not b64 and url and resolve is not None:
            try:
                parsed = urlparse(url)
                parts = (parsed.path or url).strip("/").split("/")
                # Current store URLs use files/attachments; keep older saved
                # api/attachments references readable as well.
                if len(parts) >= 5 and parts[:2] in (
                    ["files", "attachments"],
                    ["api", "attachments"],
                ):
                    sid = unquote(parts[2])
                    aid = unquote(parts[3])
                    name = unquote("/".join(parts[4:]))
                    target = resolve(session_id=sid, attachment_id=aid, filename=name)
                    if target is not None and target.exists():
                        b64 = _b64.b64encode(target.read_bytes()).decode("ascii")
            except Exception as exc:
                logger.debug("Could not resolve %s to bytes: %s", url, exc)

        if b64:
            data_url = f"data:{mime_type};base64,{b64}"
            content.append({"type": "image_url", "image_url": {"url": data_url}})
        elif url:
            content.append({"type": "image_url", "image_url": {"url": url}})

    return content


def _data_url_mime(value: str) -> str | None:
    """Return the media type declared in a ``data:`` URL, or ``None``.

    Args:
        value: A string beginning with ``data:``, e.g.
            ``data:image/jpeg;base64,...``.

    Returns:
        The declared media type (``image/jpeg``), or ``None`` when the URL
        declares no media type.
    """
    header = value[len("data:") : value.find(",")] if "," in value else ""
    mime = header.split(";", 1)[0].strip()
    return mime or None


def _guess_image_mime(filename: str | None) -> str:
    if not filename:
        return "image/png"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "gif": "image/gif",
        "webp": "image/webp",
    }.get(ext, "image/png")


@router.websocket("/questions/judge")
async def websocket_quiz_judge(websocket: WebSocket):
    """Stream an AI judgment for a single quiz answer.

    Auth is enforced via ``ws_require_auth`` rather than a router-level
    HTTP dependency — see module docstring.

    Client → Server (initial JSON):
        {
            "question": str,
            "question_type": str,
            "options": dict | null,
            "correct_answer": str,
            "explanation": str,
            "user_answer": str,
            # New: list of image entries. Each entry has either ``base64``
            # (no ``data:`` prefix) or ``url`` (already hosted via the
            # AttachmentStore). ``user_answer_image`` (single, base64) is
            # still accepted for backward compatibility.
            "user_answer_images": [
                {"base64": str, "url": str, "filename": str, "mime_type": str},
                ...
            ] | null,
            "user_answer_image": str | null,  # legacy single-image form
            "image_filename": str | null,     # legacy filename for the above
            "language": "zh" | "en" | "de" | "uk" | "vi",
        }

    Server → Client (streaming):
        {"type": "started"}
        {"type": "text", "content": "..."}        # zero or more
        {"type": "verdict", "verdict": {...}}     # once, before "done"
        {"type": "done"}

    The ``verdict`` frame carries ``result`` (correct|partial|incorrect|
    ungraded), ``is_correct``, ``final``, ``confidence``, ``feedback``,
    ``steps`` and, only when the question states points, ``awarded_points``
    / ``max_points``. ``reason`` explains a server-imposed ``ungraded``
    (missing_verdict, invalid_verdict, low_confidence, vision_unavailable).
    The ``<verdict>`` trailer itself is never sent as text, so clients that
    ignore unknown frames keep rendering the same prose.
        {"type": "error", "content": "..."}
    """
    from deeptutor.api.routers.auth import ws_auth_failed, ws_require_auth
    from deeptutor.multi_user.context import reset_current_user

    user_token = await ws_require_auth(websocket)
    if user_token is ws_auth_failed:
        return

    await websocket.accept()

    async def safe_send(payload: dict[str, Any]) -> bool:
        try:
            await websocket.send_json(payload)
            return True
        except (WebSocketDisconnect, RuntimeError, ConnectionError):
            return False

    try:
        data = await websocket.receive_json()
    except WebSocketDisconnect:
        return
    except Exception as exc:
        await safe_send({"type": "error", "content": f"Invalid request: {exc}"})
        try:
            await websocket.close()
        except Exception:
            pass
        if user_token is not None:
            try:
                reset_current_user(user_token)
            except Exception:
                pass
        return

    question_text = (data.get("question") or "").strip()
    if not question_text:
        await safe_send({"type": "error", "content": "Question is required"})
        try:
            await websocket.close()
        except Exception:
            pass
        if user_token is not None:
            try:
                reset_current_user(user_token)
            except Exception:
                pass
        return

    requested_language = (data.get("language") or "").strip().lower()
    if requested_language not in SUPPORTED_JUDGE_LANGUAGES:
        requested_language = get_response_language(
            default=_config.get("system", {}).get("language", "en")
        )
        if requested_language not in SUPPORTED_JUDGE_LANGUAGES:
            requested_language = "en"

    user_answer = data.get("user_answer") or ""

    # Resolve the image set. New clients send ``user_answer_images`` (list);
    # legacy clients send the single ``user_answer_image`` + ``image_filename``
    # pair. Build a uniform list of ``{base64, url, filename, mime_type}`` so
    # the downstream multimodal-message builder doesn't care which form
    # arrived.
    raw_images = data.get("user_answer_images")
    image_records: list[dict[str, str]] = []
    if isinstance(raw_images, list):
        for entry in raw_images:
            if not isinstance(entry, dict):
                continue
            b64 = entry.get("base64") or ""
            url = entry.get("url") or ""
            declared_mime: str | None = None
            if isinstance(b64, str) and b64.startswith("data:"):
                declared_mime = _data_url_mime(b64)
                try:
                    b64 = b64.split(",", 1)[1]
                except IndexError:
                    b64 = ""
            if not b64 and not url:
                continue
            filename = entry.get("filename") or "answer.png"
            mime_type = entry.get("mime_type") or declared_mime or _guess_image_mime(filename)
            image_records.append(
                {
                    "base64": b64,
                    "url": url,
                    "filename": filename,
                    "mime_type": mime_type,
                }
            )
    else:
        legacy_b64 = data.get("user_answer_image") or ""
        legacy_mime: str | None = None
        if isinstance(legacy_b64, str) and legacy_b64.startswith("data:"):
            legacy_mime = _data_url_mime(legacy_b64)
            try:
                legacy_b64 = legacy_b64.split(",", 1)[1]
            except IndexError:
                legacy_b64 = ""
        if legacy_b64:
            legacy_filename = data.get("image_filename") or "answer.png"
            image_records.append(
                {
                    "base64": legacy_b64,
                    "url": "",
                    "filename": legacy_filename,
                    "mime_type": legacy_mime or _guess_image_mime(legacy_filename),
                }
            )

    has_image = bool(image_records)
    can_read_images = False
    if has_image:
        from deeptutor.services.llm import config as _llm_config_mod
        from deeptutor.services.llm.capabilities import supports_vision

        llm_cfg = _llm_config_mod.get_llm_config()
        binding = getattr(llm_cfg, "binding", "openai") or "openai"
        model = getattr(llm_cfg, "model", "") or ""
        can_read_images = supports_vision(binding, model)
        if not can_read_images:
            # Vision-incapable model: judge the typed text, say the images
            # were not read, and never let the verdict count as graded.
            logger.info(
                "Judge: %s/%s does not support vision; dropping %d image(s)",
                binding,
                model,
                len(image_records),
            )
    vision_unavailable = has_image and not can_read_images

    options_value = data.get("options") if isinstance(data.get("options"), dict) else None
    system_prompt = (
        _JUDGE_SYSTEM_PROMPTS.get(requested_language, _JUDGE_SYSTEM_PROMPTS["en"])
        + "\n\n"
        + _VERDICT_CONTRACT
    )
    user_prompt = _build_judge_user_prompt(
        language=requested_language,
        question=question_text,
        question_type=data.get("question_type") or "",
        options=options_value,
        correct_answer=data.get("correct_answer") or "",
        explanation=data.get("explanation") or "",
        user_answer=user_answer,
        has_image=has_image,
        image_count=len(image_records),
        images_unreadable=vision_unavailable,
    )

    if not (user_answer.strip() or has_image):
        await safe_send(
            {
                "type": "error",
                "content": ("No answer to judge — submit a typed answer or attach an image."),
            }
        )
        try:
            await websocket.close()
        except Exception:
            pass
        if user_token is not None:
            try:
                reset_current_user(user_token)
            except Exception:
                pass
        return

    await safe_send({"type": "started"})

    # Build a multimodal user message when ≥1 image was attached. We pass
    # the full ``messages`` array to ``factory.stream`` so it forwards the
    # content-parts unchanged (the single-image ``image_data`` kwarg only
    # supports one image).
    stream_kwargs: dict[str, Any] = {}
    if can_read_images:
        user_content = await _build_multimodal_user_content(
            text=user_prompt,
            image_records=image_records,
        )
        stream_kwargs["messages"] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

    try:
        async with asyncio.timeout(2 * 60):
            splitter = _VerdictTrailerSplitter()
            connected = True
            async for chunk in llm_stream(
                prompt=user_prompt,
                system_prompt=system_prompt,
                **stream_kwargs,
            ):
                visible = splitter.feed(chunk) if chunk else ""
                if visible and not await safe_send({"type": "text", "content": visible}):
                    connected = False
                    break
        if connected:
            tail, raw_verdict = splitter.finish()
            if tail:
                await safe_send({"type": "text", "content": tail})
            await safe_send(
                {
                    "type": "verdict",
                    "verdict": parse_judge_verdict(
                        raw_verdict, vision_unavailable=vision_unavailable
                    ),
                }
            )
        await safe_send({"type": "done"})
    except TimeoutError:
        await safe_send({"type": "error", "content": "AI judge timed out. Please try again."})
    except WebSocketDisconnect:
        logger.debug("AI judge client disconnected mid-stream")
    except Exception as exc:
        logger.exception("AI judge stream failed")
        await safe_send({"type": "error", "content": format_exception_message(exc)})
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
        if user_token is not None:
            try:
                reset_current_user(user_token)
            except Exception:
                pass
