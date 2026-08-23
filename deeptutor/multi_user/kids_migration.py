"""Copy the legacy Kids workspace into ordinary restricted user accounts."""

from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import time
from typing import Any
import unicodedata
import uuid

from deeptutor.multi_user.activation import issue_activation
from deeptutor.multi_user.grants import save_grant
from deeptutor.multi_user.identity import get_user, load_users, save_user
from deeptutor.multi_user.paths import SYSTEM_ROOT, USERS_ROOT, get_admin_path_service
from deeptutor.reading import ReadingPosition, ReadingStore
from deeptutor.services.auth import hash_password

JOURNAL_PATH = SYSTEM_ROOT / "migrations" / "kids-to-learning.json"


def _read(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return default


def _atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    stage = path.parent / f".{path.name}.{uuid.uuid4().hex[:8]}.staging"
    try:
        stage.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(stage, path)
    finally:
        stage.unlink(missing_ok=True)


def _slug(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    value = re.sub(r"[^a-z0-9]+", "-", ascii_name).strip("-")
    return value or "learner"


def _unique_username(name: str, occupied: set[str]) -> str:
    base = f"learner-{_slug(name)}"
    candidate = base
    suffix = 2
    while candidate in occupied:
        candidate = f"{base}-{suffix}"
        suffix += 1
    occupied.add(candidate)
    return candidate


def _age_band(profile: dict[str, Any]) -> str:
    try:
        from deeptutor.immersive_reading.models import KidsProfile

        value = KidsProfile.model_validate(profile).age_band
    except Exception:
        value = "9-12"
    return value if value in {"6-8", "9-12", "13-15"} else "6-8"


class KidsToLearningMigration:
    def __init__(
        self,
        *,
        kids_root: Path | None = None,
        immersive_root: Path | None = None,
        users_root: Path | None = None,
        journal_path: Path | None = None,
    ) -> None:
        admin = get_admin_path_service()
        self.immersive_root = immersive_root or admin.get_workspace_feature_dir(
            "immersive_reading"
        )
        self.kids_root = kids_root or self.immersive_root / "kids"
        self.users_root = users_root or USERS_ROOT
        self.journal_path = journal_path or JOURNAL_PATH

    def plan(self) -> dict[str, Any]:
        profiles = _read(self.kids_root / "profiles.json", [])
        assignments = _read(self.kids_root / "assignments.json", [])
        progress_dir = self.kids_root / "progress"
        occupied = set(load_users())
        journal = _read(self.journal_path, {})
        completed = journal.get("profiles") if isinstance(journal, dict) else {}
        rows = []
        for profile in profiles if isinstance(profiles, list) else []:
            if not isinstance(profile, dict) or not profile.get("id"):
                continue
            profile_id = str(profile["id"])
            prior = completed.get(profile_id) if isinstance(completed, dict) else None
            username = (
                str(prior.get("username"))
                if isinstance(prior, dict) and prior.get("username")
                else _unique_username(str(profile.get("name") or "learner"), occupied)
            )
            assigned = [
                row
                for row in assignments
                if isinstance(row, dict)
                and row.get("profile_id") == profile_id
                and row.get("status", "active") == "active"
            ]
            missing = []
            for row in assigned:
                if row.get("content_type") == "interactive_book":
                    source = get_admin_path_service().get_workspace_feature_dir("book") / f"book_{row.get('book_id')}"
                else:
                    source = self.immersive_root / f"document_{row.get('document_id')}"
                if not source.exists():
                    missing.append(str(row.get("book_id") or row.get("document_id") or ""))
            rows.append(
                {
                    "profile_id": profile_id,
                    "profile_name": str(profile.get("name") or ""),
                    "username": username,
                    "age_band": _age_band(profile),
                    "assignments": len(assigned),
                    "progress_files": len(list(progress_dir.glob(f"*{profile_id}*.json")))
                    if progress_dir.is_dir()
                    else 0,
                    "missing_content": missing,
                    "already_migrated": isinstance(prior, dict) and prior.get("status") == "complete",
                }
            )
        return {
            "mode": "dry-run",
            "source": str(self.kids_root),
            "profiles": rows,
            "writes": 0,
        }

    def apply(self, *, activation_report: Path) -> dict[str, Any]:
        if not any(str(row.get("role") or "") == "admin" for row in load_users().values()):
            raise ValueError("Create an administrator account before migrating Kids profiles.")
        plan = self.plan()
        profiles = _read(self.kids_root / "profiles.json", [])
        assignments = _read(self.kids_root / "assignments.json", [])
        journal = _read(self.journal_path, {"version": 1, "profiles": {}})
        journal.setdefault("version", 1)
        journal.setdefault("profiles", {})
        codes: list[dict[str, str]] = []
        results: list[dict[str, Any]] = []
        for profile in profiles if isinstance(profiles, list) else []:
            if not isinstance(profile, dict) or not profile.get("id"):
                continue
            profile_id = str(profile["id"])
            existing_entry = journal["profiles"].get(profile_id)
            if isinstance(existing_entry, dict) and existing_entry.get("status") == "complete":
                results.append(existing_entry)
                continue
            plan_row = next(row for row in plan["profiles"] if row["profile_id"] == profile_id)
            username = plan_row["username"]
            account = get_user(username)
            if account is None:
                account = save_user(username, hash_password(secrets.token_urlsafe(32)), role="user")
            user_id = str(account["id"])
            user_workspace = self.users_root / user_id / "user" / "workspace"
            reading_store = ReadingStore(user_workspace / "reading")
            material_ids: list[str] = []
            migrated_documents: dict[str, str] = {}
            errors: list[str] = []
            interactive_ids: list[str] = []
            for assignment in assignments if isinstance(assignments, list) else []:
                if (
                    not isinstance(assignment, dict)
                    or assignment.get("profile_id") != profile_id
                    or assignment.get("status", "active") != "active"
                ):
                    continue
                if assignment.get("content_type") == "interactive_book":
                    book_id = str(assignment.get("book_id") or "")
                    source = get_admin_path_service().get_workspace_feature_dir("book") / f"book_{book_id}"
                    target = user_workspace / "reading_extensions" / "interactive_books" / "content" / f"book_{book_id}"
                    if source.is_dir() and not target.exists():
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copytree(source, target)
                    if source.is_dir():
                        interactive_ids.append(book_id)
                    else:
                        errors.append(f"Missing interactive book: {book_id}")
                    continue
                document_id = str(assignment.get("document_id") or "")
                source_root = self.immersive_root / f"document_{document_id}"
                originals = sorted(source_root.glob("original.*"))
                if not originals:
                    errors.append(f"Missing source file: {document_id}")
                    continue
                try:
                    manifest = reading_store.ingest(
                        originals[0],
                        filename=str(
                            _read(source_root / "manifest.json", {}).get("source_filename")
                            or originals[0].name
                        ),
                    )
                except Exception as exc:
                    errors.append(f"Could not import {document_id}: {exc}")
                    continue
                material_ids.append(manifest.material_id)
                migrated_documents[document_id] = manifest.material_id
                progress = _read(self.kids_root / "progress" / f"{profile_id}_{document_id}.json", {})
                if isinstance(progress, dict):
                    locator = max(1, min(manifest.unit_count, int(progress.get("current_section_index") or 0) + 1))
                    reading_store.save_position(
                        manifest.material_id,
                        ReadingPosition(
                            locator=locator,
                            source_anchor=str(progress.get("epub_cfi") or "")[:4096],
                            percentage=max(0.0, min(1.0, float(progress.get("scroll_percent") or 0) / 100)),
                            updated_at=float(progress.get("updated_at") or 0),
                        ),
                    )
                    self._migrate_learning_records(
                        user_workspace,
                        user_id=user_id,
                        material_id=manifest.material_id,
                        progress=progress,
                    )
            self._migrate_interactive_progress(
                user_workspace, profile_id=profile_id, user_id=user_id, book_ids=interactive_ids
            )
            try:
                from deeptutor.kids_rewards import get_kids_reward_providers

                for provider in get_kids_reward_providers():
                    migrate = getattr(provider, "migrate_profile", None)
                    if callable(migrate):
                        migrate(profile_id, user_id)
            except Exception as exc:
                errors.append(f"Reward provider migration failed: {exc}")
            raw_age = str(profile.get("age_band") or plan_row.get("age_band") or "9-12")
            age_band = raw_age if raw_age in {"6-8", "9-12", "13-15"} else "6-8"
            extensions = ["read_aloud", "guided_learn", "vocabulary", "quiz"]
            if interactive_ids:
                extensions.append("interactive_books")
            save_grant(
                user_id,
                {
                    "models": {"llm": []},
                    "enabled_tools": [],
                    "mcp_tools": [],
                    "cli_apps": [],
                    "exec_enabled": False,
                    "learning_policy": {
                        "age_band": age_band,
                        "locked_persona": "teacher",
                        "allowed_capabilities": ["chat", "immersive_reading"],
                        "default_capability": "immersive_reading",
                        "allowed_surfaces": ["chat", "reading"],
                        "reading": {
                            "allow_upload": False,
                            "material_ids": sorted(set(material_ids)),
                            "extensions": extensions,
                        },
                    },
                },
            )
            code = issue_activation(username)
            codes.append({"username": username, "activation_code": code})
            entry = {
                "status": "complete",
                "profile_id": profile_id,
                "username": username,
                "user_id": user_id,
                "materials": migrated_documents,
                "interactive_books": interactive_ids,
                "errors": errors,
                "completed_at": time.time(),
            }
            journal["profiles"][profile_id] = entry
            _atomic(self.journal_path, journal)
            results.append(entry)
        activation_report.parent.mkdir(parents=True, exist_ok=True)
        _atomic(activation_report, {"generated_at": time.time(), "accounts": codes})
        os.chmod(activation_report, 0o600)
        return {"mode": "apply", "profiles": results, "activation_report": str(activation_report)}

    def _migrate_learning_records(
        self,
        workspace: Path,
        *,
        user_id: str,
        material_id: str,
        progress: dict[str, Any],
    ) -> None:
        path = workspace / "learning" / "learning_records.json"
        rows = _read(path, [])
        facts = []
        for section_id in progress.get("completed_section_ids") or []:
            facts.append(("section_completed", str(section_id), None, None, True))
        for section_id, score in (progress.get("quiz_scores") or {}).items():
            facts.append(("quiz", str(section_id), int(score), 3, True))
        if progress.get("quiz_attempts") and not progress.get("quiz_scores"):
            facts.append(("quiz", "legacy-best", int(progress.get("quiz_best_score") or 0), 3, True))
        existing = {row.get("event_id") for row in rows if isinstance(row, dict)}
        for action, item, score, total, completed in facts:
            event_id = sha256(f"kids|{user_id}|{material_id}|{action}|{item}".encode()).hexdigest()
            if event_id in existing:
                continue
            rows.append(
                {
                    "event_id": event_id,
                    "user_id": user_id,
                    "material_id": material_id,
                    "locator": 1,
                    "extension": "quiz" if action == "quiz" else "migration",
                    "action": action,
                    "item_id": item,
                    "score": score,
                    "total": total,
                    "completed": completed,
                    "time_spent_seconds": float(progress.get("time_spent_seconds") or 0),
                    "occurred_at": float(progress.get("updated_at") or time.time()),
                }
            )
        _atomic(path, rows)

    def _migrate_interactive_progress(
        self, workspace: Path, *, profile_id: str, user_id: str, book_ids: list[str]
    ) -> None:
        target_root = workspace / "reading_extensions" / "interactive_books" / "progress"
        for book_id in book_ids:
            source = self.kids_root / "progress" / f"ib_{profile_id}_{book_id}.json"
            payload = _read(source, None)
            if not isinstance(payload, dict):
                continue
            payload["user_id"] = user_id
            payload.pop("profile_id", None)
            _atomic(target_root / f"{book_id}.json", payload)


__all__ = ["KidsToLearningMigration"]
