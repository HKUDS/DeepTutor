"""KB document inventory — the facts retrieval cannot answer.

"How many files are in this knowledge base?" is a question about the
collection, not about passage similarity, so it is answered from disk. These
tests pin the counting rules (what is and isn't a document), the degradations
(remote / agent / unreadable KBs), and the wording contract both consumers —
the chat system prompt and the ``kb_files`` tool — render from.
"""

from __future__ import annotations

from pathlib import Path

from deeptutor.knowledge.manifest import (
    UNAVAILABLE_AGENT,
    UNAVAILABLE_MISSING,
    UNAVAILABLE_REMOTE,
    build_manifest,
    document_root,
    iter_kb_documents,
    render_manifest_note,
    render_manifest_report,
)

_READY = {"rag_provider": "llamaindex", "status": "ready"}


def _kb(tmp_path: Path, *files: str, name: str = "Course") -> Path:
    kb_dir = tmp_path / name
    raw = kb_dir / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    for rel in files:
        target = raw / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"x" * 2048)
    return kb_dir


class TestDocumentCounting:
    def test_counts_documents_in_subfolders(self, tmp_path: Path) -> None:
        kb_dir = _kb(tmp_path, "a.pdf", "notes/week3.md", "notes/deep/week4.md")

        manifest = build_manifest(name="Course", kb_dir=kb_dir, entry=_READY)

        assert manifest.total == 3
        # Folders are organizational only, so a document is identified by its
        # path relative to raw/ — not by basename. Order is a depth-first walk
        # with each level sorted: a folder's own files before its subfolders.
        assert [doc.name for doc in manifest.documents] == [
            "a.pdf",
            "notes/week3.md",
            "notes/deep/week4.md",
        ]

    def test_hidden_bookkeeping_is_not_a_document(self, tmp_path: Path) -> None:
        """``.DS_Store`` is not something the user uploaded."""
        kb_dir = _kb(tmp_path, "a.pdf", ".DS_Store", ".obsidian/workspace.json")

        manifest = build_manifest(name="Course", kb_dir=kb_dir, entry=_READY)

        assert manifest.total == 1
        assert [doc.name for doc in manifest.documents] == ["a.pdf"]

    def test_empty_kb_reports_zero_rather_than_unavailable(self, tmp_path: Path) -> None:
        kb_dir = _kb(tmp_path)

        manifest = build_manifest(name="Course", kb_dir=kb_dir, entry=_READY)

        assert manifest.enumerable
        assert manifest.total == 0

    def test_documents_are_truncated_but_total_is_not(self, tmp_path: Path) -> None:
        kb_dir = _kb(tmp_path, *(f"doc{index:02d}.pdf" for index in range(10)))

        manifest = build_manifest(name="Course", kb_dir=kb_dir, entry=_READY, limit=3)

        assert manifest.total == 10
        assert len(manifest.documents) == 3
        assert manifest.omitted == 7

    def test_sizes_are_read_for_listed_documents(self, tmp_path: Path) -> None:
        kb_dir = _kb(tmp_path, "a.pdf")

        manifest = build_manifest(name="Course", kb_dir=kb_dir, entry=_READY)

        assert manifest.documents[0].size == 2048

    def test_iter_skips_directories_and_sorts(self, tmp_path: Path) -> None:
        kb_dir = _kb(tmp_path, "b.pdf", "a.pdf", "sub/c.pdf")

        names = [path.name for path in iter_kb_documents(kb_dir / "raw")]

        assert names == ["a.pdf", "b.pdf", "c.pdf"]

    def test_iter_of_missing_root_is_empty(self, tmp_path: Path) -> None:
        assert list(iter_kb_documents(tmp_path / "nope")) == []


class TestPatternFilter:
    def test_glob_matches_full_path_or_basename(self, tmp_path: Path) -> None:
        kb_dir = _kb(tmp_path, "a.pdf", "b.md", "notes/week3.md")

        manifest = build_manifest(name="Course", kb_dir=kb_dir, entry=_READY, pattern="*.md")

        assert manifest.matched == 2
        assert [doc.name for doc in manifest.documents] == ["b.md", "notes/week3.md"]

    def test_plain_text_is_a_case_insensitive_substring(self, tmp_path: Path) -> None:
        kb_dir = _kb(tmp_path, "Lecture01.pdf", "lab.pdf")

        manifest = build_manifest(name="Course", kb_dir=kb_dir, entry=_READY, pattern="LECTURE")

        assert [doc.name for doc in manifest.documents] == ["Lecture01.pdf"]

    def test_total_stays_the_whole_kb_when_filtering(self, tmp_path: Path) -> None:
        """A filtered view must not misreport how large the KB is."""
        kb_dir = _kb(tmp_path, "a.pdf", "b.pdf", "c.md")

        manifest = build_manifest(name="Course", kb_dir=kb_dir, entry=_READY, pattern="*.md")

        assert (manifest.total, manifest.matched) == (3, 1)


class TestConnectedKbs:
    def test_linked_kb_enumerates_the_external_folder(self, tmp_path: Path) -> None:
        external = tmp_path / "elsewhere"
        (external / "sub").mkdir(parents=True)
        (external / "paper.pdf").write_text("x")
        (external / "sub" / "notes.md").write_text("x")
        entry = {"type": "linked", "external_path": str(external), "rag_provider": "llamaindex"}

        manifest = build_manifest(name="Linked", kb_dir=tmp_path / "Linked", entry=entry)

        assert manifest.total == 2
        assert document_root(tmp_path / "Linked", entry) == external

    def test_remote_server_kb_is_not_reported_as_empty(self, tmp_path: Path) -> None:
        """A hosted KB has documents we simply cannot see — "0" would be a lie."""
        entry = {"type": "lightrag_server", "server_url": "https://example.invalid"}

        manifest = build_manifest(name="Remote", kb_dir=tmp_path / "Remote", entry=entry)

        assert not manifest.enumerable
        assert manifest.unavailable == UNAVAILABLE_REMOTE
        assert manifest.total == 0
        assert document_root(tmp_path / "Remote", entry) is None

    def test_connected_agent_is_not_a_document_collection(self, tmp_path: Path) -> None:
        entry = {"type": "subagent", "agent_kind": "claude_code"}

        manifest = build_manifest(name="Agent", kb_dir=tmp_path / "Agent", entry=entry)

        assert manifest.unavailable == UNAVAILABLE_AGENT

    def test_missing_root_is_unavailable_not_empty(self, tmp_path: Path) -> None:
        manifest = build_manifest(name="Fresh", kb_dir=tmp_path / "Fresh", entry=_READY)

        assert manifest.unavailable == UNAVAILABLE_MISSING


class TestManifestNote:
    def test_note_carries_count_names_and_the_authority_rule(self, tmp_path: Path) -> None:
        kb_dir = _kb(tmp_path, "a.pdf", "notes/week3.md")
        manifest = build_manifest(name="Course", kb_dir=kb_dir, entry=_READY)

        note = render_manifest_note([manifest], language="en")

        assert "2 documents" in note
        assert "notes/week3.md" in note
        # C: retrieval must never be the basis for a count.
        assert "must never be used to infer how many documents" in note
        assert "kb_files" in note

    def test_note_is_localised(self, tmp_path: Path) -> None:
        kb_dir = _kb(tmp_path, "a.pdf")
        manifest = build_manifest(name="Course", kb_dir=kb_dir, entry=_READY)

        note = render_manifest_note([manifest], language="zh")

        assert "共 1 个文档" in note
        assert "以本清单为准" in note

    def test_note_warns_when_the_index_is_not_ready(self, tmp_path: Path) -> None:
        kb_dir = _kb(tmp_path, "a.pdf")
        entry = {"rag_provider": "llamaindex", "status": "needs_reindex"}

        note = render_manifest_note(
            [build_manifest(name="Course", kb_dir=kb_dir, entry=entry)], language="en"
        )

        assert "needs reindexing" in note

    def test_note_mentions_the_omitted_tail(self, tmp_path: Path) -> None:
        kb_dir = _kb(tmp_path, *(f"doc{index:02d}.pdf" for index in range(5)))
        manifest = build_manifest(name="Course", kb_dir=kb_dir, entry=_READY, limit=2)

        note = render_manifest_note([manifest], language="en")

        assert "3 more" in note

    def test_no_manifests_yields_no_block(self) -> None:
        assert render_manifest_note([], language="en") == ""


class TestManifestReport:
    def test_report_lists_documents_with_sizes(self, tmp_path: Path) -> None:
        kb_dir = _kb(tmp_path, "a.pdf")
        manifest = build_manifest(name="Course", kb_dir=kb_dir, entry=_READY)

        report = render_manifest_report(manifest, language="en")

        assert "1 document." in report
        assert "1. a.pdf (2.0 KB)" in report

    def test_report_states_a_pattern_matched_nothing(self, tmp_path: Path) -> None:
        kb_dir = _kb(tmp_path, "a.pdf")
        manifest = build_manifest(name="Course", kb_dir=kb_dir, entry=_READY, pattern="zzz")

        report = render_manifest_report(manifest, language="en")

        assert 'No document name matches "zzz"' in report

    def test_report_declares_a_remote_kb_unlistable(self, tmp_path: Path) -> None:
        entry = {"type": "lightrag_server"}
        manifest = build_manifest(name="Remote", kb_dir=tmp_path / "Remote", entry=entry)

        report = render_manifest_report(manifest, language="en")

        assert "remote server" in report
        assert "0" not in report

    def test_report_of_an_empty_kb_says_so(self, tmp_path: Path) -> None:
        kb_dir = _kb(tmp_path)
        manifest = build_manifest(name="Course", kb_dir=kb_dir, entry=_READY)

        assert "no documents" in render_manifest_report(manifest, language="en")
