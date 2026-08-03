"""PartnerManager config persistence, merge semantics, and legacy migration."""

from __future__ import annotations

import dataclasses

import yaml

from deeptutor.services.partners.manager import PartnerConfig, PartnerManager
from deeptutor.services.partners.workspace import DEFAULT_SOUL, read_soul


def _mgr() -> PartnerManager:
    return PartnerManager()


class TestConfigRoundTrip:
    def test_save_and_load(self, partners_root):
        mgr = _mgr()
        config = PartnerConfig(
            name="Ada",
            description="study partner",
            channels={"telegram": {"enabled": True, "token": "t"}},
            llm_selection={"profile_id": "p", "model_id": "m"},
            language="zh",
            emoji="🦊",
            color="#aabbcc",
            soul_origin={"type": "library", "id": "math-tutor"},
            enabled_tools=["web_search"],
            builtin_tools=["rag", "read_memory"],
            mcp_tools=[],
        )
        mgr.save_config("ada", config)
        loaded = mgr.load_config("ada")
        assert loaded is not None
        assert dataclasses.asdict(loaded) == dataclasses.asdict(config)

    def test_missing_returns_none(self, partners_root):
        assert _mgr().load_config("nope") is None

    def test_none_tool_fields_stay_none(self, partners_root):
        mgr = _mgr()
        mgr.save_config("p1", PartnerConfig(name="P1"))
        loaded = mgr.load_config("p1")
        assert loaded.enabled_tools is None
        assert loaded.builtin_tools is None
        # MCP is the exception — deny-by-default (see TestMcpToolsDefault).
        assert loaded.mcp_tools == []


class TestMcpToolsDefault:
    """MCP tools reach host-side capabilities configured deployment-wide, so no
    partner may inherit them without an explicit owner decision."""

    def test_new_config_denies_mcp(self):
        assert PartnerConfig(name="P1").mcp_tools == []

    def test_stored_config_without_mcp_key_denies(self, partners_root):
        # Configs written before the deny default carry no ``mcp_tools`` key;
        # reading absence as "unrestricted" would hand every configured MCP
        # tool to an existing partner, so it resolves to deny instead.
        partner_dir = partners_root / "legacy"
        partner_dir.mkdir(parents=True)
        (partner_dir / "config.yaml").write_text(
            yaml.dump({"name": "Legacy", "enabled_tools": ["web_search"]}),
            encoding="utf-8",
        )

        loaded = _mgr().load_config("legacy")
        assert loaded is not None
        assert loaded.mcp_tools == []
        assert loaded.enabled_tools == ["web_search"]

    def test_unrestricted_round_trips_through_its_own_spelling(self, partners_root):
        mgr = _mgr()
        mgr.save_config("p1", PartnerConfig(name="P1", mcp_tools=None))
        # The opt-in has to land on disk as something a typo cannot produce, or
        # the reload below would read it as deny.
        stored = yaml.safe_load((partners_root / "p1" / "config.yaml").read_text(encoding="utf-8"))
        assert stored["mcp_tools"] == ["*"]
        assert mgr.load_config("p1").mcp_tools is None

    def test_a_bare_yaml_key_denies_rather_than_granting_everything(self, partners_root):
        """``mcp_tools:`` with no value parses as null.

        A hand-edit that writes it almost certainly means "none", so null must
        not be the spelling that unlocks every configured MCP tool.
        """
        partner_dir = partners_root / "bare"
        partner_dir.mkdir(parents=True)
        (partner_dir / "config.yaml").write_text(
            "name: Bare\nmcp_tools:\n",
            encoding="utf-8",
        )

        assert _mgr().load_config("bare").mcp_tools == []

    def test_malformed_value_fails_closed(self, partners_root):
        partner_dir = partners_root / "broken"
        partner_dir.mkdir(parents=True)
        (partner_dir / "config.yaml").write_text(
            yaml.dump({"name": "Broken", "mcp_tools": "mcp_x_y"}),
            encoding="utf-8",
        )

        assert _mgr().load_config("broken").mcp_tools == []


class TestMergeSemantics:
    def test_none_values_preserve_existing(self, partners_root):
        mgr = _mgr()
        mgr.save_config(
            "p1",
            PartnerConfig(name="Keep", description="keep me", enabled_tools=["rag"]),
        )
        merged = mgr.merge_config("p1", {"name": None, "description": None})
        assert merged.name == "Keep"
        assert merged.description == "keep me"
        assert merged.enabled_tools == ["rag"]

    def test_empty_values_are_intentional_clears(self, partners_root):
        mgr = _mgr()
        mgr.save_config("p1", PartnerConfig(name="Keep", description="old"))
        merged = mgr.merge_config("p1", {"description": "", "channels": {}})
        assert merged.description == ""
        assert merged.channels == {}

    def test_unknown_keys_ignored(self, partners_root):
        merged = _mgr().merge_config("new", {"bogus": 1, "name": "X"})
        assert merged.name == "X"
        assert not hasattr(merged, "bogus")

    def test_mergeable_fields_match_partnerconfig_fields(self):
        """Every config field must be mergeable via the API (anti-drift pin)."""
        field_names = {f.name for f in dataclasses.fields(PartnerConfig)}
        assert set(PartnerManager._MERGEABLE_FIELDS) == field_names


class TestAutoStart:
    def test_new_partner_defaults_to_auto_start(self, partners_root):
        mgr = _mgr()
        mgr.save_config("p1", PartnerConfig(name="P1"))
        assert mgr._load_auto_start("p1", default=False) is True

    def test_routine_save_preserves_disabled_intent(self, partners_root):
        mgr = _mgr()
        mgr.save_config("p1", PartnerConfig(name="P1"), auto_start=False)
        # Routine save (auto_start omitted) must not silently flip it back on.
        mgr.save_config("p1", PartnerConfig(name="P1 renamed"))
        assert mgr._load_auto_start("p1", default=True) is False


class TestWorkspaceSeeding:
    def test_ensure_dirs_seeds_default_soul(self, partners_root):
        mgr = _mgr()
        mgr._ensure_partner_dirs("p1")
        assert read_soul("p1") == DEFAULT_SOUL
        ws = partners_root / "p1" / "workspace"
        assert (ws / "user" / "workspace").is_dir()
        assert (ws / "knowledge_bases").is_dir()

    def test_existing_soul_not_overwritten(self, partners_root):
        from deeptutor.services.partners.workspace import write_soul

        mgr = _mgr()
        mgr._ensure_partner_dirs("p1")
        write_soul("p1", "# Custom")
        mgr._ensure_partner_dirs("p1")
        assert read_soul("p1") == "# Custom"


class TestLegacyTutorBotMigration:
    def _seed_legacy_bot(self, admin_root, bot_id="old-bot", **overrides):
        legacy = admin_root / "tutorbot" / bot_id
        legacy.mkdir(parents=True)
        data = {
            "name": "Old Bot",
            "description": "from tutorbot",
            "persona": "# Soul\nLegacy persona text",
            "channels": {"telegram": {"enabled": True, "token": "tok"}},
            "llm_selection": {"profile_id": "p", "model_id": "m"},
            "auto_start": True,
            **overrides,
        }
        (legacy / "config.yaml").write_text(yaml.dump(data), encoding="utf-8")
        sessions = legacy / "workspace" / "sessions"
        sessions.mkdir(parents=True)
        (sessions / "telegram_1.jsonl").write_text(
            '{"role": "user", "content": "hi", "timestamp": "2026-01-01T00:00:00"}\n',
            encoding="utf-8",
        )
        return legacy

    def test_migrates_config_soul_and_sessions(self, partners_root):
        admin_root = partners_root.parent
        self._seed_legacy_bot(admin_root)

        mgr = _mgr()
        ids = mgr._discover_partner_ids()
        assert "old-bot" in ids

        cfg = mgr.load_config("old-bot")
        assert cfg.name == "Old Bot"
        assert cfg.channels["telegram"]["token"] == "tok"
        assert cfg.llm_selection == {"profile_id": "p", "model_id": "m"}
        assert cfg.soul_origin == {"type": "tutorbot", "id": "old-bot"}
        assert read_soul("old-bot") == "# Soul\nLegacy persona text"
        assert mgr._load_auto_start("old-bot", default=False) is True

        history = mgr.get_history("old-bot")
        assert history and history[0]["content"] == "hi"

    def test_migration_is_idempotent_and_non_destructive(self, partners_root):
        admin_root = partners_root.parent
        legacy = self._seed_legacy_bot(admin_root)

        mgr = _mgr()
        mgr._discover_partner_ids()
        # Tweak the migrated partner, then re-discover with a fresh manager.
        from deeptutor.services.partners.workspace import write_soul

        write_soul("old-bot", "# Edited after migration")
        mgr2 = _mgr()
        mgr2._discover_partner_ids()
        assert read_soul("old-bot") == "# Edited after migration"
        # Legacy tree untouched.
        assert (legacy / "config.yaml").exists()


class TestSoulLibraryRefresh:
    """Untouched old-seed library entries upgrade in place; user souls survive."""

    _TUTORBOT_ENTRY = {
        "id": "default-tutorbot",
        "name": "Default TutorBot",
        "content": "# Soul\n\nI am TutorBot, a personal learning companion.\n\n"
        "## Personality\n\n- Helpful and friendly\n- Clear, encouraging, and patient\n"
        "- Adapts explanations to the user's level\n\n"
        "## Values\n\n- Accuracy over speed\n- User privacy and safety\n- Transparency in actions",
    }

    def test_tutorbot_era_library_is_upgraded(self, partners_root):
        mgr = _mgr()
        mgr._save_souls([dict(self._TUTORBOT_ENTRY)])
        souls = mgr.list_souls()
        assert [s["id"] for s in souls] == ["companion"]
        assert "tutorbot" not in yaml.dump(souls).lower()

    def test_user_souls_pass_through_verbatim(self, partners_root):
        mgr = _mgr()
        mine = {"id": "my-bot", "name": "Mine", "content": "I miss TutorBot"}
        edited_seed = {"id": "math-tutor", "name": "Math Tutor", "content": "# My own text"}
        mgr._save_souls([dict(self._TUTORBOT_ENTRY), mine, edited_seed])
        souls = mgr.list_souls()
        assert souls == [
            {"id": "companion", "name": "Learning Companion", "content": souls[0]["content"]},
            mine,
            edited_seed,
        ]

    def test_refresh_is_idempotent(self, partners_root):
        mgr = _mgr()
        mgr._save_souls([dict(self._TUTORBOT_ENTRY)])
        first = mgr.list_souls()
        assert mgr.list_souls() == first
