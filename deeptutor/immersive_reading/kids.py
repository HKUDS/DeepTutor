"""Child profiles, assignments, and learning progress."""

from __future__ import annotations

import hashlib
import hmac
from pathlib import Path
import time
from typing import Any
import uuid

from deeptutor.immersive_reading.models import (
    KidsBookAssignment,
    KidsLearningProgress,
    KidsProfile,
)
from deeptutor.immersive_reading.storage import read_json, write_json
from deeptutor.services.path_service import get_path_service


def _hash_pin(pin: str) -> str:
    """Hash a parent PIN using a salted comparison."""
    salt = "deeptutor-kids-pin-v1"
    return hashlib.sha256(f"{salt}:{pin}".encode()).hexdigest()


def _verify_pin(pin: str, pin_hash: str) -> bool:
    if not pin_hash:
        return False
    return hmac.compare_digest(_hash_pin(pin), pin_hash)


class KidsManager:
    """Manages child profiles, book assignments, and per-profile progress.

    All data is stored as JSON files under the immersive-reading root's
    ``kids/`` subdirectory, scoped to the current user's workspace.
    """

    def __init__(self) -> None:
        self._pin_failures: dict[str, list[float]] = {}

    def _kids_root(self) -> Path:
        root = get_path_service().get_immersive_reading_dir() / "kids"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _profiles_path(self) -> Path:
        return self._kids_root() / "profiles.json"

    def _assignments_path(self) -> Path:
        return self._kids_root() / "assignments.json"

    def _progress_dir(self) -> Path:
        d = self._kids_root() / "progress"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _progress_path(self, profile_id: str, document_id: str) -> Path:
        return self._progress_dir() / f"{profile_id}_{document_id}.json"

    # ── Profiles ───────────────────────────────────────────────────────

    def list_profiles(self) -> list[KidsProfile]:
        data = read_json(self._profiles_path(), [])
        return [KidsProfile(**p) for p in data]

    def get_profile(self, profile_id: str) -> KidsProfile | None:
        return next((p for p in self.list_profiles() if p.id == profile_id), None)

    def create_profile(
        self,
        name: str,
        *,
        avatar: str = "default",
        birth_date: str = "",
        help_language: str = "en",
        narration_rate: float = 0.8,
        daily_limit_minutes: int = 30,
        parent_pin: str = "",
    ) -> KidsProfile:
        profiles = self.list_profiles()
        profile = KidsProfile(
            id=uuid.uuid4().hex[:12],
            name=name.strip() or "Child",
            avatar=avatar,
            birth_date=birth_date,
            help_language=help_language,
            narration_rate=max(0.5, min(1.5, narration_rate)),
            daily_limit_minutes=max(5, min(120, daily_limit_minutes)),
            pin_hash=_hash_pin(parent_pin) if parent_pin else "",
        )
        profiles.append(profile)
        write_json(self._profiles_path(), [p.model_dump(mode="json") for p in profiles])
        return profile

    def update_profile(self, profile_id: str, **kwargs: Any) -> KidsProfile:
        profiles = self.list_profiles()
        idx = next((i for i, p in enumerate(profiles) if p.id == profile_id), None)
        if idx is None:
            raise ValueError("Profile not found")
        p = profiles[idx]
        for key in (
            "name",
            "avatar",
            "birth_date",
            "help_language",
            "narration_rate",
            "daily_limit_minutes",
        ):
            if key in kwargs and kwargs[key] is not None:
                setattr(p, key, kwargs[key])
        if "parent_pin" in kwargs and kwargs["parent_pin"]:
            p.pin_hash = _hash_pin(kwargs["parent_pin"])
        p.updated_at = time.time()
        profiles[idx] = p
        write_json(self._profiles_path(), [pp.model_dump(mode="json") for pp in profiles])
        return p

    def delete_profile(self, profile_id: str) -> None:
        profiles = [p for p in self.list_profiles() if p.id != profile_id]
        write_json(self._profiles_path(), [p.model_dump(mode="json") for p in profiles])
        # Remove assignments and progress for this profile
        assignments = self.list_assignments()
        assignments = [a for a in assignments if a.profile_id != profile_id]
        write_json(self._assignments_path(), [a.model_dump(mode="json") for a in assignments])
        # Clean progress files
        for f in self._progress_dir().glob(f"{profile_id}_*.json"):
            f.unlink(missing_ok=True)

    def verify_parent_pin(self, profile_id: str, pin: str) -> bool:
        """Verify parent PIN with rate limiting."""
        now = time.time()
        failures = [t for t in self._pin_failures.get(profile_id, []) if now - t < 300]
        if len(failures) >= 5:
            return False
        profile = self.get_profile(profile_id)
        if profile is None:
            return False
        ok = _verify_pin(pin, profile.pin_hash)
        if not ok:
            failures.append(now)
            self._pin_failures[profile_id] = failures
        else:
            self._pin_failures.pop(profile_id, None)
        return ok

    def has_pin(self, profile_id: str) -> bool:
        p = self.get_profile(profile_id)
        return bool(p and p.pin_hash)

    # ── Assignments ────────────────────────────────────────────────────

    def list_assignments(self, profile_id: str | None = None) -> list[KidsBookAssignment]:
        data = read_json(self._assignments_path(), [])
        items = [KidsBookAssignment(**a) for a in data]
        if profile_id:
            items = [a for a in items if a.profile_id == profile_id]
        return items

    def assign_book(
        self,
        profile_id: str,
        document_id: str,
        *,
        available_through_section_id: str = "",
        available_through_section_index: int = 999,
    ) -> KidsBookAssignment:
        from deeptutor.immersive_reading.service import get_immersive_reading_service

        existing = self.list_assignments(profile_id)
        match = next((a for a in existing if a.document_id == document_id), None)
        if match:
            match.status = "active"
            match.available_through_section_id = available_through_section_id
            match.available_through_section_index = available_through_section_index
            match.updated_at = time.time()
            self._save_assignments()
            return match

        ir_service = get_immersive_reading_service()
        doc = ir_service.load_document(document_id)
        title = doc.title if doc else document_id
        sort_order = len(existing)
        assignment = KidsBookAssignment(
            id=uuid.uuid4().hex[:12],
            profile_id=profile_id,
            document_id=document_id,
            document_title=title,
            available_through_section_id=available_through_section_id,
            available_through_section_index=available_through_section_index,
            sort_order=sort_order,
        )
        existing.append(assignment)
        write_json(self._assignments_path(), [a.model_dump(mode="json") for a in existing])
        return assignment

    def unassign_book(self, profile_id: str, document_id: str) -> None:
        assignments = [
            a
            for a in self.list_assignments()
            if not (a.profile_id == profile_id and a.document_id == document_id)
        ]
        write_json(self._assignments_path(), [a.model_dump(mode="json") for a in assignments])

    def update_assignment(
        self, profile_id: str, document_id: str, **kwargs: Any
    ) -> KidsBookAssignment:
        assignments = self.list_assignments()
        idx = next(
            (
                i
                for i, a in enumerate(assignments)
                if a.profile_id == profile_id and a.document_id == document_id
            ),
            None,
        )
        if idx is None:
            raise ValueError("Assignment not found")
        a = assignments[idx]
        for key in (
            "status",
            "sort_order",
            "is_next_read",
            "available_through_section_id",
            "available_through_section_index",
        ):
            if key in kwargs and kwargs[key] is not None:
                setattr(a, key, kwargs[key])
        a.updated_at = time.time()
        assignments[idx] = a
        write_json(self._assignments_path(), [aa.model_dump(mode="json") for aa in assignments])
        return a

    def _save_assignments(self) -> None:
        assignments = self.list_assignments()
        write_json(self._assignments_path(), [a.model_dump(mode="json") for a in assignments])

    def get_kids_library(self, profile_id: str) -> list[dict[str, Any]]:
        """Return assigned books with progress for a child profile."""
        from deeptutor.immersive_reading.service import get_immersive_reading_service

        assignments = [a for a in self.list_assignments(profile_id) if a.status == "active"]
        assignments.sort(key=lambda a: a.sort_order)
        ir_service = get_immersive_reading_service()
        library: list[dict[str, Any]] = []
        for a in assignments:
            doc = ir_service.load_document(a.document_id)
            if doc is None:
                continue
            progress = self.load_kids_progress(profile_id, a.document_id)
            library.append(
                {
                    "assignment": a.model_dump(mode="json"),
                    "document": ir_service._summary(doc),
                    "progress": progress.model_dump(mode="json"),
                }
            )
        return library

    # ── Progress ───────────────────────────────────────────────────────

    def load_kids_progress(self, profile_id: str, document_id: str) -> KidsLearningProgress:
        data = read_json(self._progress_path(profile_id, document_id))
        if data:
            return KidsLearningProgress(**data)
        return KidsLearningProgress(profile_id=profile_id, document_id=document_id)

    def update_kids_progress_record(
        self,
        profile_id: str,
        document_id: str,
        *,
        section_id: str = "",
        section_index: int = 0,
        scroll_percent: float = 0.0,
        epub_cfi: str = "",
        section_href: str = "",
        time_delta: float = 0.0,
    ) -> KidsLearningProgress:
        progress = self.load_kids_progress(profile_id, document_id)
        if section_id:
            progress.current_section_id = section_id
            progress.current_section_index = section_index
        progress.scroll_percent = max(0.0, min(100.0, scroll_percent))
        if epub_cfi:
            progress.epub_cfi = epub_cfi
        if section_href:
            progress.section_href = section_href
        progress.time_spent_seconds += time_delta
        progress.last_read_at = time.time()
        progress.updated_at = time.time()
        write_json(self._progress_path(profile_id, document_id), progress.model_dump(mode="json"))
        return progress

    def mark_section_completed(
        self, profile_id: str, document_id: str, section_id: str
    ) -> KidsLearningProgress:
        progress = self.load_kids_progress(profile_id, document_id)
        if section_id not in progress.completed_section_ids:
            progress.completed_section_ids.append(section_id)
            progress.updated_at = time.time()
            write_json(
                self._progress_path(profile_id, document_id), progress.model_dump(mode="json")
            )
        return progress

    def add_stars(self, profile_id: str, document_id: str, stars: int) -> KidsLearningProgress:
        progress = self.load_kids_progress(profile_id, document_id)
        progress.total_stars += max(0, stars)
        progress.updated_at = time.time()
        write_json(self._progress_path(profile_id, document_id), progress.model_dump(mode="json"))
        return progress

    def record_quiz(
        self, profile_id: str, document_id: str, score: int, total: int
    ) -> KidsLearningProgress:
        progress = self.load_kids_progress(profile_id, document_id)
        progress.quiz_attempts += 1
        progress.quiz_best_score = max(progress.quiz_best_score, score)
        progress.updated_at = time.time()
        write_json(self._progress_path(profile_id, document_id), progress.model_dump(mode="json"))
        return progress

    def get_report(self, profile_id: str) -> dict[str, Any]:
        """Aggregate learning report for a child profile."""
        profile = self.get_profile(profile_id)
        if profile is None:
            raise ValueError("Profile not found")
        library = self.get_kids_library(profile_id)
        total_stars = sum(item["progress"]["total_stars"] for item in library)
        total_time = sum(item["progress"]["time_spent_seconds"] for item in library)
        total_quizzes = sum(item["progress"]["quiz_attempts"] for item in library)
        return {
            "profile": profile.model_dump(mode="json"),
            "books": library,
            "total_stars": total_stars,
            "total_time_seconds": total_time,
            "total_quiz_attempts": total_quizzes,
            "total_books": len(library),
        }

    def is_section_allowed(self, profile_id: str, document_id: str, section_index: int) -> bool:
        """Check if a child is allowed to read a section based on assignment limits."""
        assignments = self.list_assignments(profile_id)
        assignment = next(
            (a for a in assignments if a.document_id == document_id and a.status == "active"), None
        )
        if assignment is None:
            return False
        return section_index <= assignment.available_through_section_index


_kids_manager: KidsManager | None = None


def get_kids_manager() -> KidsManager:
    global _kids_manager
    if _kids_manager is None:
        _kids_manager = KidsManager()
    return _kids_manager
