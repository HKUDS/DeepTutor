"""
Two-file public memory system: SUMMARY.md and PROFILE.md.

- SUMMARY: Running summary of the user's learning journey (auto-updated).
- PROFILE: User identity, preferences, knowledge levels (auto-updated).

Per-bot files (SOUL.md, TOOLS.md, USER.md, etc.) live in each bot's
workspace directory, not in the shared memory dir.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
import logging
from pathlib import Path
import re
from typing import Literal

from deeptutor.services.llm import clean_thinking_tags
from deeptutor.services.llm import stream as llm_stream
from deeptutor.services.path_service import PathService, get_path_service
from deeptutor.services.session.protocol import SessionStoreProtocol

MemoryFile = Literal["summary", "profile"]
MEMORY_FILES: list[MemoryFile] = ["summary", "profile"]

_NO_CHANGE = "NO_CHANGE"

logger = logging.getLogger(__name__)

_FILENAMES: dict[MemoryFile, str] = {
    "summary": "SUMMARY.md",
    "profile": "PROFILE.md",
}


@dataclass
class MemorySnapshot:
    summary: str
    profile: str
    summary_updated_at: str | None
    profile_updated_at: str | None


@dataclass
class MemoryUpdateResult:
    content: str
    changed: bool
    updated_at: str | None


class MemoryService:
    """Two-file public memory: SUMMARY + PROFILE."""

    def __init__(
        self,
        path_service: PathService | None = None,
        store: SessionStoreProtocol | None = None,
    ) -> None:
        from deeptutor.services.session import get_session_store

        self._path_service = path_service or get_path_service()
        self._store = store or get_session_store()
        self._refresh_lock = asyncio.Lock()
        self._migrate_legacy()

    @property
    def _memory_dir(self) -> Path:
        return self._path_service.get_memory_dir()

    def _path(self, which: MemoryFile) -> Path:
        return self._memory_dir / _FILENAMES[which]

    def _migrate_legacy(self) -> None:
        """One-time migration from old memory.md to the two-file system."""
        legacy = self._memory_dir / "memory.md"
        if not legacy.exists():
            return
        if self._path("profile").exists() or self._path("summary").exists():
            return

        content = legacy.read_text(encoding="utf-8").strip()
        if not content:
            legacy.rename(legacy.with_suffix(".md.bak"))
            return

        preferences, context = self._extract_legacy_sections(content)
        self._memory_dir.mkdir(parents=True, exist_ok=True)
        if preferences:
            self._path("profile").write_text(
                f"## Preferences\n{preferences}",
                encoding="utf-8",
            )
        if context:
            self._path("summary").write_text(
                f"## Learning Journey\n{context}",
                encoding="utf-8",
            )
        legacy.rename(legacy.with_suffix(".md.bak"))

    # ── Read ──────────────────────────────────────────────────────────

    def read_file(self, which: MemoryFile) -> str:
        path = self._path(which)
        if not path.exists():
            return ""
        try:
            raw = path.read_text(encoding="utf-8").strip()
            cleaned = _clean_memory_content(raw)
            if cleaned != raw:
                try:
                    if cleaned:
                        path.write_text(cleaned, encoding="utf-8")
                    else:
                        path.unlink()
                except Exception:
                    pass
            return cleaned
        except Exception:
            return ""

    def read_summary(self) -> str:
        return self.read_file("summary")

    def read_profile(self) -> str:
        return self.read_file("profile")

    def _file_updated_at(self, which: MemoryFile) -> str | None:
        path = self._path(which)
        if not path.exists():
            return None
        try:
            return datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat()
        except Exception:
            return None

    def read_snapshot(self) -> MemorySnapshot:
        return MemorySnapshot(
            summary=self.read_summary(),
            profile=self.read_profile(),
            summary_updated_at=self._file_updated_at("summary"),
            profile_updated_at=self._file_updated_at("profile"),
        )

    # ── Write ─────────────────────────────────────────────────────────

    def write_file(self, which: MemoryFile, content: str) -> MemorySnapshot:
        normalized = _clean_memory_content(str(content or ""))
        path = self._path(which)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not normalized:
            if path.exists():
                path.unlink()
        else:
            path.write_text(normalized, encoding="utf-8")
        return self.read_snapshot()

    def write_memory(self, content: str) -> MemorySnapshot:
        """Legacy compat: write to profile (primary editable file)."""
        return self.write_file("profile", content)

    def clear_file(self, which: MemoryFile) -> MemorySnapshot:
        return self.write_file(which, "")

    def clear_memory(self) -> MemorySnapshot:
        for f in MEMORY_FILES:
            path = self._path(f)
            if path.exists():
                path.unlink()
        return self.read_snapshot()

    # ── Context building (injected into LLM prompts) ─────────────────

    def build_memory_context(
        self,
        files: list[MemoryFile] | None = None,
        max_chars: int = 4000,
    ) -> str:
        requested = {item for item in files or [] if item in MEMORY_FILES}
        if not requested:
            return ""

        parts: list[str] = []

        profile = self.read_profile() if "profile" in requested else ""
        if profile:
            parts.append(f"### User Profile\n{profile}")

        summary = self.read_summary() if "summary" in requested else ""
        if summary:
            parts.append(f"### Learning Context\n{summary}")

        if not parts:
            return ""

        combined = "\n\n".join(parts)
        if len(combined) > max_chars:
            combined = combined[:max_chars].rstrip() + "\n...[truncated]"

        return (
            "## Background Memory\n"
            "Use this memory sparingly — only when directly relevant.\n\n"
            f"{combined}"
        )

    def get_preferences_text(self) -> str:
        profile = self.read_profile()
        return f"## User Profile\n{profile}" if profile else ""

    # ── Auto-refresh from conversation ────────────────────────────────

    async def refresh_from_turn(
        self,
        *,
        user_message: str,
        assistant_message: str,
        session_id: str = "",
        capability: str = "",
        language: str = "en",
        timestamp: str = "",
    ) -> MemoryUpdateResult:
        if not user_message.strip() or not assistant_message.strip():
            return MemoryUpdateResult(content="", changed=False, updated_at=None)

        source = (
            f"[Session] {session_id or '(unknown)'}\n"
            f"[Capability] {capability or 'chat'}\n"
            f"[Timestamp] {timestamp or datetime.now().isoformat()}\n\n"
            f"[User]\n{user_message.strip()}\n\n"
            f"[Assistant]\n{assistant_message.strip()}"
        )

        async with self._refresh_lock:
            p_changed = await self._rewrite_one("profile", source, language)
            s_changed = await self._rewrite_one("summary", source, language)

            snap = self.read_snapshot()
        return MemoryUpdateResult(
            content=snap.profile,
            changed=p_changed or s_changed,
            updated_at=snap.profile_updated_at,
        )

    async def refresh_from_session(
        self,
        session_id: str | None = None,
        *,
        language: str = "en",
        max_messages: int = 10,
    ) -> MemoryUpdateResult:
        target = (session_id or "").strip()
        if not target:
            sessions = await self._store.list_sessions(limit=1)
            if sessions:
                target = str(sessions[0].get("session_id", "") or "")

        if not target:
            return MemoryUpdateResult(content="", changed=False, updated_at=None)

        messages = await self._store.get_messages_for_context(target)
        relevant = [
            m
            for m in messages
            if str(m.get("role", "")) in {"user", "assistant"}
            and str(m.get("content", "") or "").strip()
        ][-max_messages:]

        if not relevant:
            return MemoryUpdateResult(content="", changed=False, updated_at=None)

        transcript = "\n\n".join(
            f"{'User' if m.get('role') == 'user' else 'Assistant'}: "
            f"{str(m.get('content', '') or '').strip()}"
            for m in relevant
        )

        cap = ""
        sess = await self._store.get_session(target)
        if sess:
            cap = str(sess.get("capability", "") or "")

        source = (
            f"[Session] {target}\n[Capability] {cap or 'chat'}\n\n[Recent Transcript]\n{transcript}"
        )

        async with self._refresh_lock:
            p_changed = await self._rewrite_one("profile", source, language)
            s_changed = await self._rewrite_one("summary", source, language)

            snap = self.read_snapshot()
        return MemoryUpdateResult(
            content=snap.profile,
            changed=p_changed or s_changed,
            updated_at=snap.profile_updated_at,
        )

    # ── LLM rewrite for individual files ──────────────────────────────

    async def _rewrite_one(self, which: MemoryFile, source: str, language: str) -> bool:
        """Rewrite a single memory file. Returns True if changed."""
        current = self.read_file(which)
        zh = str(language).lower().startswith("zh")

        if which == "profile":
            sys_prompt, user_prompt = self._profile_prompts(current, source, zh)
        else:
            sys_prompt, user_prompt = self._summary_prompts(current, source, zh)

        chunks: list[str] = []
        async for c in llm_stream(
            prompt=user_prompt,
            system_prompt=sys_prompt,
            temperature=0.2,
            max_tokens=900,
        ):
            chunks.append(c)

        raw = _clean_memory_content("".join(chunks))
        if not raw or raw == _NO_CHANGE:
            return False

        if raw == current:
            return False

        if not _is_valid_memory_rewrite(which, raw):
            logger.warning(
                "Skipping invalid %s memory rewrite: missing expected section heading",
                which,
            )
            return False

        self.write_file(which, raw)
        return True

    @staticmethod
    def _profile_prompts(current: str, source: str, zh: bool) -> tuple[str, str]:
        if zh:
            return (
                "你负责维护一份用户画像文档。只保留稳定的用户身份、偏好、知识水平。"
                f"如果无需修改，请只返回 {_NO_CHANGE}。",
                "如果需要更新，请重写用户画像，可使用以下标题：\n"
                "## Identity\n## Learning Style\n## Knowledge Level\n## Preferences\n\n"
                "规则：保持简短，删除过时内容，不要记录临时对话。\n\n"
                f"[当前画像]\n{current or '(empty)'}\n\n"
                f"[新增材料]\n{source}",
            )
        return (
            "You maintain a user profile document. Only keep stable identity, "
            "preferences, and knowledge levels. "
            f"If nothing should change, return exactly {_NO_CHANGE}.",
            "Rewrite the user profile if needed. Suggested sections:\n"
            "## Identity\n## Learning Style\n## Knowledge Level\n## Preferences\n\n"
            "Rules: keep it short, remove stale items, no transient chatter.\n\n"
            f"[Current profile]\n{current or '(empty)'}\n\n"
            f"[New material]\n{source}",
        )

    @staticmethod
    def _summary_prompts(current: str, source: str, zh: bool) -> tuple[str, str]:
        if zh:
            return (
                "你负责维护一份学习旅程摘要。记录用户正在学什么、完成了什么、有哪些待解决的问题。"
                f"如果无需修改，请只返回 {_NO_CHANGE}。",
                "如果需要更新，请重写学习旅程摘要，可使用以下标题：\n"
                "## Current Focus\n## Accomplishments\n## Open Questions\n\n"
                "规则：保持简短，删除已完成或过时的条目。\n\n"
                f"[当前摘要]\n{current or '(empty)'}\n\n"
                f"[新增材料]\n{source}",
            )
        return (
            "You maintain a learning journey summary. Track what the user is studying, "
            "what they've accomplished, and what open questions remain. "
            f"If nothing should change, return exactly {_NO_CHANGE}.",
            "Rewrite the learning summary if needed. Suggested sections:\n"
            "## Current Focus\n## Accomplishments\n## Open Questions\n\n"
            "Rules: keep it short, remove completed/stale items.\n\n"
            f"[Current summary]\n{current or '(empty)'}\n\n"
            f"[New material]\n{source}",
        )

    # ── Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _extract_legacy_sections(content: str) -> tuple[str, str]:
        text = content.replace("\r\n", "\n").strip()
        preferences = ""
        context = ""
        pref_match = re.search(
            r"##\s*Preferences\s*(.*?)(?=\n##\s*Context\b|\Z)",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        ctx_match = re.search(
            r"##\s*Context\s*(.*)$",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if pref_match:
            preferences = pref_match.group(1).strip()
        if ctx_match:
            context = ctx_match.group(1).strip()
        return preferences, context


def _strip_code_fence(content: str) -> str:
    cleaned = str(content or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z0-9_-]*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```$", "", cleaned)
    return cleaned.strip()


_EXPECTED_MEMORY_HEADINGS: dict[MemoryFile, set[str]] = {
    "profile": {
        "identity",
        "user identity",
        "learning style",
        "knowledge level",
        "preferences",
        "preference",
        "身份",
        "用户身份",
        "学习风格",
        "学习方式",
        "知识水平",
        "偏好",
        "用户偏好",
    },
    "summary": {
        "current focus",
        "accomplishments",
        "open questions",
        "learning journey",
        "context",
        "当前关注",
        "当前学习",
        "学习重点",
        "已完成",
        "学习成果",
        "成就",
        "开放问题",
        "待解决问题",
        "学习旅程",
        "上下文",
    },
}


def _normalize_heading(value: str) -> str:
    heading = re.sub(r"[*_`]+", "", str(value or "")).strip()
    heading = re.sub(r"[:：#\s]+$", "", heading).strip()
    return heading.lower()


def _is_valid_memory_rewrite(which: MemoryFile, content: str) -> bool:
    """Accept only target-shaped LLM rewrites, not arbitrary model answers."""
    allowed = _EXPECTED_MEMORY_HEADINGS[which]
    headings = re.findall(r"^##(?!#)\s*(.+?)\s*$", content, flags=re.MULTILINE)
    return any(_normalize_heading(heading) in allowed for heading in headings)


def _clean_memory_content(content: str) -> str:
    """Remove code fences and model scratchpad tags before durable memory writes."""
    return clean_thinking_tags(_strip_code_fence(content)).strip()


_memory_services: dict[str, MemoryService] = {}


def get_memory_service() -> MemoryService:
    path_service = get_path_service()
    key = str(path_service.get_memory_dir().resolve())
    if key not in _memory_services:
        _memory_services[key] = MemoryService(path_service=path_service)
    return _memory_services[key]


__all__ = [
    "MemoryFile",
    "MemoryService",
    "MemorySnapshot",
    "MemoryUpdateResult",
    "get_memory_service",
]
