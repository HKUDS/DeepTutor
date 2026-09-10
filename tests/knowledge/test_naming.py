from __future__ import annotations

import pytest

from deeptutor.knowledge.naming import validate_knowledge_base_name


def test_validate_knowledge_base_name_allows_unicode_and_spaces() -> None:
    assert validate_knowledge_base_name("  高等数学 KB  ") == "高等数学 KB"


@pytest.mark.parametrize("name", ["bad/name", "bad\\name", "bad?name", "bad#name", "bad%name"])
def test_validate_knowledge_base_name_rejects_path_and_url_separators(name: str) -> None:
    with pytest.raises(ValueError, match="reserved characters"):
        validate_knowledge_base_name(name)


@pytest.mark.parametrize(
    "register",
    [
        lambda m, name: m.register_obsidian_vault(name, "/tmp"),
        lambda m, name: m.register_linked_kb(name, "/tmp", "llamaindex"),
        lambda m, name: m.register_subagent_connection(name, agent_kind="claude_code"),
        lambda m, name: m.register_lightrag_server_kb(name, "http://localhost:9621"),
        lambda m, name: m.register_marginnote4_kb(name),
        lambda m, name: m.register_ima_kb(name, "", "", "lib-1"),
        lambda m, name: m.register_weknora_kb(name, "http://localhost:8080", "k", "kb-1"),
    ],
)
def test_every_register_path_rejects_a_url_separator(tmp_path, register) -> None:
    """The validator has to sit on the manager, not on one route.

    ``validate_knowledge_base_name`` used to be called by the create route
    alone, so the seven connect-* endpoints wrote whatever the user typed
    straight into ``kb_config.json``. A name holding a ``/`` is then
    unaddressable: uvicorn decodes the path before routing and ``{kb_name}``
    cannot span a separator, so every per-KB route 404s and the KB can be
    listed but never deleted.
    """
    from deeptutor.knowledge.manager import KnowledgeBaseManager

    manager = KnowledgeBaseManager(base_dir=str(tmp_path))
    with pytest.raises(ValueError, match="reserved characters"):
        register(manager, "数学/物理")
    assert manager.list_knowledge_bases() == []
