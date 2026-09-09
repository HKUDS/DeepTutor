"""Asset provisioning: copy KB / skill / notebook into the partner workspace."""

from __future__ import annotations

import json

import pytest

from deeptutor.services.partners.workspace import (
    ensure_partner_workspace,
    list_assets,
    provision_assets,
    remove_asset,
    strip_frontmatter,
)


def _seed_admin_kb(admin_root, name="physics"):
    kb = admin_root / "knowledge_bases" / name
    (kb / "raw").mkdir(parents=True)
    (kb / "raw" / "doc.pdf").write_bytes(b"%PDF-fake")
    (kb / "version-1").mkdir()
    (kb / "version-1" / "docstore.json").write_text("{}", encoding="utf-8")
    (kb / "metadata.json").write_text(
        json.dumps({"name": name, "rag_provider": "llamaindex"}), encoding="utf-8"
    )
    config_path = admin_root / "knowledge_bases" / "kb_config.json"
    config_path.write_text(
        json.dumps(
            {
                "knowledge_bases": {
                    name: {
                        "path": name,
                        "description": f"Knowledge base: {name}",
                        "rag_provider": "llamaindex",
                        "status": "ready",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    return kb


def _seed_admin_skill(admin_root, name="research-mode"):
    skill = admin_root / "user" / "workspace" / "skills" / name
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: test skill\n---\n\nBody.", encoding="utf-8"
    )
    (skill / "references").mkdir()
    (skill / "references" / "ref.md").write_text("ref", encoding="utf-8")
    return skill


def _seed_admin_connected_kb(admin_root, name="wiki", kb_type="weknora", **fields):
    """Register a pointer KB with no folder on disk — the connected shape.

    Defaults to ``weknora`` rather than ``obsidian`` on purpose: obsidian,
    marginnote4 and subagent KBs are refused for partners (see
    ``test_exclusive_capability_kinds_are_refused``), so they cannot stand in
    for the ordinary connected case.
    """
    entry = {"type": kb_type, "server_url": "http://localhost:8080", "knowledge_base_id": "kb-1"}
    entry.update(fields)
    config_path = admin_root / "knowledge_bases" / "kb_config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps({"knowledge_bases": {name: entry}}),
        encoding="utf-8",
    )
    return entry


def _seed_admin_notebook(admin_root, notebook_id="nb1"):
    nb_dir = admin_root / "user" / "workspace" / "notebook"
    nb_dir.mkdir(parents=True)
    (nb_dir / f"{notebook_id}.json").write_text(
        json.dumps(
            {
                "id": notebook_id,
                "name": "My Notes",
                "records": [{"id": "r1", "type": "chat", "title": "t"}],
            }
        ),
        encoding="utf-8",
    )
    (nb_dir / "notebooks_index.json").write_text(
        json.dumps({"notebooks": [{"id": notebook_id, "name": "My Notes", "record_count": 1}]}),
        encoding="utf-8",
    )
    return nb_dir


class TestProvisioning:
    def test_copies_all_three_asset_classes(self, partners_root):
        admin_root = partners_root.parent
        _seed_admin_kb(admin_root)
        _seed_admin_skill(admin_root)
        _seed_admin_notebook(admin_root)

        report = provision_assets(
            "ada",
            knowledge_bases=["physics"],
            skills=["research-mode"],
            notebooks=["nb1"],
        )
        assert report["errors"] == []
        assert report["copied"] == {
            "knowledge_bases": ["physics"],
            "skills": ["research-mode"],
            "notebooks": ["nb1"],
        }

        ws = partners_root / "ada" / "workspace"
        assert (ws / "knowledge_bases" / "physics" / "raw" / "doc.pdf").exists()
        assert (ws / "knowledge_bases" / "physics" / "version-1" / "docstore.json").exists()
        assert (ws / "user" / "workspace" / "skills" / "research-mode" / "SKILL.md").exists()
        assert (
            ws / "user" / "workspace" / "skills" / "research-mode" / "references" / "ref.md"
        ).exists()
        assert (ws / "user" / "workspace" / "notebook" / "nb1.json").exists()
        index = json.loads(
            (ws / "user" / "workspace" / "notebook" / "notebooks_index.json").read_text()
        )
        assert index["notebooks"][0]["id"] == "nb1"

    def test_unknown_assets_reported_not_raised(self, partners_root):
        report = provision_assets(
            "ada",
            knowledge_bases=["ghost-kb"],
            skills=["ghost-skill"],
            notebooks=["ghost-nb"],
        )
        assert len(report["errors"]) == 3
        types = {e["type"] for e in report["errors"]}
        assert types == {"knowledge_base", "skill", "notebook"}

    def test_builtin_skill_copies_from_package(self, partners_root):
        # skill-creator ships inside the package (deeptutor/skills/builtin);
        # provisioning must fall back to it when the user workspace has no
        # skill of that name. Regression: builtin picks from the wizard's
        # default-all selection used to fail with "not accessible".
        from deeptutor.services.skill.service import BUILTIN_SKILLS_ROOT

        builtin_names = [
            entry.name for entry in BUILTIN_SKILLS_ROOT.iterdir() if (entry / "SKILL.md").exists()
        ]
        assert builtin_names, "expected packaged builtin skills"
        target = builtin_names[0]

        report = provision_assets("ada", skills=[target])
        assert report["errors"] == []
        ws = partners_root / "ada" / "workspace"
        assert (ws / "user" / "workspace" / "skills" / target / "SKILL.md").exists()

    def test_provisioning_is_idempotent(self, partners_root):
        admin_root = partners_root.parent
        _seed_admin_kb(admin_root)
        provision_assets("ada", knowledge_bases=["physics"])
        report = provision_assets("ada", knowledge_bases=["physics"])
        assert report["errors"] == []
        assert report["copied"]["knowledge_bases"] == ["physics"]

    def test_connected_kb_is_registered_not_copied(self, partners_root):
        # A connected/pointer KB (Obsidian vault, linked index, ...) has no
        # `<kb>/` folder on disk by design, so provisioning it must not
        # attempt a copytree. Regression for #1259.
        from deeptutor.knowledge.manager import KnowledgeBaseManager

        admin_root = partners_root.parent
        _seed_admin_connected_kb(admin_root)

        report = provision_assets("ada", knowledge_bases=["wiki"])
        assert report["errors"] == []
        assert report["copied"]["knowledge_bases"] == ["wiki"]

        partner_kb_dir = partners_root / "ada" / "workspace" / "knowledge_bases"
        assert not (partner_kb_dir / "wiki").exists()
        manager = KnowledgeBaseManager(base_dir=str(partner_kb_dir))
        assert manager.get_kb_entry("wiki") == {
            "type": "weknora",
            "server_url": "http://localhost:8080",
            "knowledge_base_id": "kb-1",
        }

    def test_connected_kb_provisioning_is_idempotent(self, partners_root):
        admin_root = partners_root.parent
        _seed_admin_connected_kb(admin_root)
        provision_assets("ada", knowledge_bases=["wiki"])
        report = provision_assets("ada", knowledge_bases=["wiki"])
        assert report["errors"] == []
        assert report["copied"]["knowledge_bases"] == ["wiki"]

    @pytest.mark.parametrize("kb_type", ["obsidian", "marginnote4", "subagent"])
    def test_exclusive_capability_kinds_are_refused(self, partners_root, kb_type):
        """These three take over the turn, so a partner must not hold one.

        Each is driven by an exclusive ``KnowledgeCapability`` whose
        ``is_active`` keys purely off the turn's KB selection — and a partner
        passes ALL of its knowledge bases as that selection, every turn. One
        assigned vault would seize every partner turn; a ``subagent`` entry
        would let a partner consult another partner, or itself.

        Unreachable while pointer KBs failed to provision at all; reachable the
        moment they started succeeding.
        """
        admin_root = partners_root.parent
        _seed_admin_connected_kb(admin_root, name="taken", kb_type=kb_type)

        report = provision_assets("ada", knowledge_bases=["taken"])

        assert report["copied"]["knowledge_bases"] == []
        assert len(report["errors"]) == 1
        assert "cannot be assigned to a partner" in report["errors"][0]["error"]

    def test_a_connected_kb_can_be_listed_and_removed(self, partners_root):
        """It has no folder, so both halves used to miss it entirely.

        ``list_assets`` scanned directories only, so an assigned pointer KB was
        invisible in the partner's library — and never excluded from the
        picker, so the user kept re-assigning it. ``remove_asset`` returned
        False for a missing folder, which the router turns into a 404.
        """
        admin_root = partners_root.parent
        _seed_admin_connected_kb(admin_root)
        provision_assets("ada", knowledge_bases=["wiki"])

        listed = list_assets("ada")["knowledge_bases"]
        assert [kb["name"] for kb in listed] == ["wiki"]
        assert listed[0]["type"] == "weknora"

        assert remove_asset("ada", "knowledge_base", "wiki") is True
        assert list_assets("ada")["knowledge_bases"] == []
        assert remove_asset("ada", "knowledge_base", "wiki") is False


class TestInventoryAndRemoval:
    def test_list_and_remove(self, partners_root):
        admin_root = partners_root.parent
        _seed_admin_kb(admin_root)
        _seed_admin_skill(admin_root)
        _seed_admin_notebook(admin_root)
        provision_assets(
            "ada",
            knowledge_bases=["physics"],
            skills=["research-mode"],
            notebooks=["nb1"],
        )

        assets = list_assets("ada")
        assert [kb["name"] for kb in assets["knowledge_bases"]] == ["physics"]
        assert [s["name"] for s in assets["skills"]] == ["research-mode"]
        assert [n["id"] for n in assets["notebooks"]] == ["nb1"]

        assert remove_asset("ada", "knowledge_base", "physics") is True
        assert remove_asset("ada", "skill", "research-mode") is True
        assert remove_asset("ada", "notebook", "nb1") is True

        assets = list_assets("ada")
        assert assets == {"knowledge_bases": [], "skills": [], "notebooks": []}

    def test_remove_rejects_path_traversal(self, partners_root):
        ensure_partner_workspace("ada")
        import pytest

        with pytest.raises(ValueError):
            remove_asset("ada", "skill", "../escape")


class TestStripFrontmatter:
    def test_strips_yaml_block(self):
        text = "---\nname: x\ndescription: y\n---\n\n# Body\ncontent"
        assert strip_frontmatter(text) == "# Body\ncontent"

    def test_passthrough_without_frontmatter(self):
        assert strip_frontmatter("# Plain") == "# Plain"
