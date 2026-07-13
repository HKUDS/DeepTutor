"""Asset provisioning: copy KB / skill / notebook into the partner workspace."""

from __future__ import annotations

import json

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
