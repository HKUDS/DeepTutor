"""AI judge WebSocket — grades a learner's quiz answer.

Mounted on its own (without router-level HTTP auth dependencies) because
WebSocket upgrades cannot use FastAPI's HTTP dependency injection, so we
rely on ``ws_require_auth`` inside the handler — mirroring the pattern
used by ``unified_ws``.
"""

from __future__ import annotations

import base64 as _b64
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from deeptutor.services.config import PROJECT_ROOT, load_config_with_main
from deeptutor.services.llm import stream as llm_stream
from deeptutor.services.settings.interface_settings import get_ui_language
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
}


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
            parts.append(f"{count_text}，请结合图片中的文字/公式/草图一并判定。")
        parts.append("请针对该学习者的具体作答给出 AI 评判。")
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
        if has_image:
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
    locally-hosted ``/api/attachments/...`` is only reachable from the
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
                # Expected shape: api/attachments/{sid}/{aid}/{name}
                if len(parts) >= 5 and parts[0] == "api" and parts[1] == "attachments":
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


@router.websocket("/question/judge")
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
            "language": "zh" | "en",
        }

    Server → Client (streaming):
        {"type": "started"}
        {"type": "text", "content": "..."}        # zero or more
        {"type": "done"}
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
    if requested_language not in ("zh", "en"):
        requested_language = get_ui_language(
            default=_config.get("system", {}).get("language", "en")
        )
        if requested_language not in ("zh", "en"):
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
            if isinstance(b64, str) and b64.startswith("data:"):
                try:
                    b64 = b64.split(",", 1)[1]
                except IndexError:
                    b64 = ""
            if not b64 and not url:
                continue
            filename = entry.get("filename") or "answer.png"
            mime_type = entry.get("mime_type") or _guess_image_mime(filename)
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
        if isinstance(legacy_b64, str) and legacy_b64.startswith("data:"):
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
                    "mime_type": _guess_image_mime(legacy_filename),
                }
            )

    has_image = bool(image_records)

    options_value = data.get("options") if isinstance(data.get("options"), dict) else None
    system_prompt = _JUDGE_SYSTEM_PROMPTS.get(requested_language, _JUDGE_SYSTEM_PROMPTS["en"])
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
    if has_image:
        from deeptutor.services.llm import config as _llm_config_mod
        from deeptutor.services.llm.capabilities import supports_vision

        llm_cfg = _llm_config_mod.get_llm_config()
        binding = getattr(llm_cfg, "binding", "openai") or "openai"
        model = getattr(llm_cfg, "model", "") or ""
        if supports_vision(binding, model):
            user_content = await _build_multimodal_user_content(
                text=user_prompt,
                image_records=image_records,
            )
            stream_kwargs["messages"] = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ]
        else:
            # Vision-incapable model — fall back to text-only judge so the
            # learner still gets feedback on their typed answer.
            logger.info(
                "Judge: %s/%s does not support vision; dropping %d image(s)",
                binding,
                model,
                len(image_records),
            )

    try:
        async for chunk in llm_stream(
            prompt=user_prompt,
            system_prompt=system_prompt,
            **stream_kwargs,
        ):
            if not chunk:
                continue
            if not await safe_send({"type": "text", "content": chunk}):
                break
        await safe_send({"type": "done"})
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
