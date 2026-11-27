"""Workspace-scoped QTI item-bank import and export.

Unlike the multi-tenant server implementation, this adapter has no owner
column or object store: the practice SQLite database is already scoped to one
content workspace, and generated packages stream straight back to the caller.
The raw uploaded source is kept beside that database so a preview can be
re-opened without retaining the upload in process memory.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import time

from deeptutor.services.practice.storage import PracticeStore
from deeptutor.services.question_content import (
    project_legacy_question,
)
from deeptutor.services.question_content.exchange import build_package, load_package
from deeptutor.services.session.question_content_adapter import content_for_read

QTI_MAX_BYTES = 50 * 1024 * 1024
QTI_MAX_ITEMS = 500

_TOKEN = re.compile(r"^[a-f0-9]{32}$")

# Every preview report carries the QTI dialect the package declared, so the
# UI can explain why a 2.1 package lacks external-scoring metadata.
_PUBLIC_ITEM_FIELDS = (
    "memberPath",
    "resourceId",
    "content",
    "scoring",
    "bankAdmission",
    "diagnostics",
    "identifierMap",
)


def _reference_fill_answer(document: dict) -> str:
    blanks = ((document.get("author") or {}).get("fillSpec") or {}).get("blanks") or []
    values = []
    for blank in blanks:
        answers = blank.get("accepted_answers") or []
        if answers:
            values.append(str(answers[0].get("value") or ""))
    return "; ".join(value for value in values if value)


def ensure_qti_available() -> None:
    """Fail with an actionable message when the optional parser is absent.

    ``lxml`` is only pulled in by ``deeptutor[qti]``. Importing the module must
    stay dependency-free so the rest of the practice surface keeps working on
    a minimal install.
    """
    if importlib.util.find_spec("lxml") is None:
        raise RuntimeError(
            "QTI import/export requires the optional 'qti' extra (pip install 'deeptutor[qti]')"
        )


class QtiExchange:
    def __init__(self, store: PracticeStore) -> None:
        self.store = store

    def _source_dir(self) -> Path:
        return Path(self.store.db_path).parent / "practice_qti"

    def _source_path(self, token: str) -> Path:
        if not _TOKEN.fullmatch(token):
            raise ValueError("Invalid QTI preview token")
        return self._source_dir() / f"{token}.bin"

    async def preview(self, data: bytes, filename: str, *, target: str = "bank") -> dict:
        """Parse a package and stage the items that can enter the bank."""
        if not data or len(data) > QTI_MAX_BYTES:
            raise ValueError("Choose a non-empty QTI file up to 50 MiB")
        ensure_qti_available()

        parsed = await asyncio.to_thread(
            load_package, data, filename=filename, trusted_export=False
        )
        report = {
            key: parsed[key]
            for key in ("version", "packageValidation", "diagnostics", "counts", "sourceSha256")
        }
        report["items"] = []

        questions: list[dict] = []
        source_hash = parsed["sourceSha256"]
        for index, item in enumerate(parsed["items"]):
            public = {key: item.get(key) for key in _PUBLIC_ITEM_FIELDS}
            public["itemKey"] = f"item_{index + 1}"
            document = item.get("document")
            public["questionType"] = (
                document.get("questionType") if isinstance(document, dict) else None
            )
            if parsed["packageValidation"] != "valid":
                public["bankAdmission"] = "blocked"
                public["diagnostics"] = [
                    *public.get("diagnostics", []),
                    {
                        "code": "PACKAGE_VALIDATION_BLOCKED",
                        "severity": "error",
                        "message": "Package validation failed",
                        "location": public["memberPath"] or "package",
                    },
                ]
            elif document is not None and (
                item.get("bankAdmission") == "ready"
                or (
                    item.get("bankAdmission") == "review"
                    and document.get("questionType") == "fill_blank"
                    and {d["code"] for d in item.get("diagnostics", [])}
                    <= {"SOURCE_GUIDANCE_UNTRUSTED", "FILL_POLICY_UNPROVEN"}
                )
            ):
                try:
                    if document.get("assets"):
                        # DeepTutor has no asset store, so a package that carries
                        # prompt images cannot round-trip safely yet.
                        raise ValueError("Prompt images are not supported yet")
                    # Scope the imported identity to the package bytes. A
                    # vendor item identifier alone can collide with another
                    # import or with a chat-generated ``q_1``.
                    scoped = {
                        **document,
                        "itemId": "qti3:"
                        + hashlib.sha256(
                            f"{source_hash}\0{index}\0{document['itemId']}".encode("utf-8")
                        ).hexdigest(),
                    }
                    question = project_legacy_question(scoped, target_format="bank-v1")
                    if question["question_type"] == "fill_blank" and not question["correct_answer"]:
                        # The canonical fill spec is authoritative, but the
                        # notebook still shows and grades through the flat
                        # answer column. Keep a readable reference answer.
                        question["correct_answer"] = _reference_fill_answer(scoped)
                    public["importable"] = True
                    public["question"] = question["question"]
                    public["correctAnswer"] = question["correct_answer"]
                    questions.append(
                        {
                            **question,
                            "item_key": public["itemKey"],
                            "question_content": scoped,
                            "user_answer": "",
                        }
                    )
                except (ValueError, KeyError, TypeError) as exc:
                    public["bankAdmission"] = "blocked"
                    public["diagnostics"] = [
                        *public.get("diagnostics", []),
                        {
                            "code": "BANK_PROJECTION_BLOCKED",
                            "severity": "error",
                            "message": str(exc)[:200],
                            "location": public["memberPath"],
                        },
                    ]
            report["items"].append(public)

        if parsed["packageValidation"] == "valid":
            report["counts"] = {
                **report["counts"],
                "ready": sum(row["bankAdmission"] == "ready" for row in report["items"]),
                "review": sum(row["bankAdmission"] == "review" for row in report["items"]),
                "blocked": sum(row["bankAdmission"] == "blocked" for row in report["items"]),
            }

        token = await asyncio.to_thread(
            self.store.stage_import,
            filename,
            "qti-mistakes" if target == "mistakes" else "qti3",
            questions,
            report,
        )
        self._write_source(token, data)
        return {**report, "token": token}

    def _write_source(self, token: str, data: bytes) -> None:
        directory = self._source_dir()
        directory.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(directory, 0o700)
        except OSError:
            pass
        # Previews expire with the staged row after a day; sweep the bytes on
        # the same schedule so abandoned uploads cannot fill the workspace.
        cutoff = time.time() - 86_400
        for stale in directory.glob("*.bin"):
            try:
                if stale.stat().st_mtime < cutoff:
                    stale.unlink()
            except OSError:
                continue
        path = self._source_path(token)
        path.write_bytes(data)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    async def report(self, token: str) -> dict:
        """Return the stored preview report plus any commit receipt."""
        staged = await asyncio.to_thread(self.store.staged_import, token)
        if staged is None:
            raise LookupError("QTI preview unavailable")
        payload = staged["payload"]
        report = payload.get("report") or {}
        if report:
            # The preview source is the authoritative artifact; if it was
            # removed, treat the token as expired instead of serving a report
            # that can no longer be committed or inspected.
            if not self._source_path(token).is_file():
                raise LookupError("QTI preview unavailable")
        receipt = {"commitResult": staged["result"]} if staged["result"] else {}
        return {**report, "token": token, **receipt}

    async def source(self, token: str) -> tuple[bytes, str]:
        staged = await asyncio.to_thread(self.store.staged_import, token)
        if staged is None:
            raise LookupError("QTI preview unavailable")
        path = self._source_path(token)
        if not path.is_file():
            raise LookupError("QTI preview unavailable")
        name = str(staged["filename"]).lower()
        extension = "xml" if name.endswith(".xml") else "zip" if name.endswith(".zip") else "bin"
        return path.read_bytes(), f"qti-source-{token}.{extension}"

    async def commit(self, token: str, selected: list[str]) -> dict:
        if not _TOKEN.fullmatch(token):
            raise ValueError("Invalid QTI preview token")
        return await asyncio.to_thread(self.store.commit_import, token, selected)

    async def export(
        self,
        entry_ids: list[int],
        *,
        version: str = "3.0",
        fmt: str = "zip",
    ) -> tuple[bytes, str, str]:
        """Build an all-or-nothing package from notebook rows.

        The first release is text-only: a row whose canonical document owns an
        asset is rejected instead of producing a package with dangling media.
        """
        if not 1 <= len(entry_ids) <= QTI_MAX_ITEMS:
            raise ValueError("Select 1-500 questions")
        ensure_qti_available()
        entries = await asyncio.to_thread(self.store.entries_by_id, entry_ids)
        if len(entries) != len(entry_ids):
            raise LookupError("One or more questions no longer exist")

        documents = []
        for entry in entries:
            document = entry.get("question_content") or content_for_read(None, entry)
            if document is None:
                raise ValueError(
                    f"Question {entry.get('question_id')} cannot be represented in QTI"
                )
            if document.get("assets"):
                raise ValueError("QTI export supports text-only questions in this release")
            documents.append(document)

        if fmt == "xml":
            if len(documents) != 1:
                raise ValueError("XML export supports exactly one question")
            from deeptutor.services.question_content.qti3 import serialize_item

            serialized = await asyncio.to_thread(serialize_item, documents[0])
            if serialized.get("xml") is None:
                raise ValueError(
                    json.dumps(serialized.get("diagnostics") or [], ensure_ascii=False)
                )
            return serialized["xml"], "application/xml", "question.xml"

        built = await asyncio.to_thread(
            build_package,
            [{"document": document} for document in documents],
            asset_bytes={},
            version=version,
        )
        if built["packageValidation"] != "valid" or built.get("zip") is None:
            raise ValueError(json.dumps(built.get("diagnostics") or [], ensure_ascii=False))
        digest = hashlib.sha256(built["zip"]).hexdigest()[:12]
        return built["zip"], "application/zip", f"qti{version.replace('.', '')}-{digest}.zip"


__all__ = ["QTI_MAX_BYTES", "QTI_MAX_ITEMS", "QtiExchange", "ensure_qti_available"]
