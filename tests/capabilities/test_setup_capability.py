"""Tests for the setup capability: what it may change, and what it must refuse.

Four properties are pinned here because each one fails silently if it breaks:

* **Probe before commit.** The chat model is one of the rows this capability
  writes. If a value were stored before being verified, a bad selection would
  leave the user in a conversation that can no longer answer — including the
  turn that would undo it. The test asserts the stored value is untouched after
  a failing probe, not merely that an error was returned.
* **Scope is enforced, not advertised.** Personal rows are per-user files;
  global rows are the shared deployment settings. A non-administrator writing a
  global row, or a partner writing anything, must be refused at the apply
  boundary rather than by prompt instruction.
* **Activation is objective.** An implicitly-mounted capability that fires on
  the model's sense of relevance shows up in unrelated conversations. The
  activation tests are the guard on that.
* **Coupled settings are reported.** ``interface.json`` inherits the reply
  language from the interface one, so changing the UI language moves a second
  setting. The apply result has to say so.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from deeptutor.agents._shared.tool_composition import ToolMountFlags, compose_enabled_tools
from deeptutor.capabilities import active_loop_capabilities, any_exclusive_capability_active
from deeptutor.capabilities.setup import SETUP_TOOL_NAMES, SetupCapability
from deeptutor.capabilities.setup.apply import apply_setting
from deeptutor.capabilities.setup.binding import message_signals_setup, setup_gaps
from deeptutor.capabilities.setup.jobs import run_job
from deeptutor.capabilities.setup.tools import (
    ApplySettingTool,
    InspectSetupTool,
    RequestCredentialTool,
    RunSetupJobTool,
)
from deeptutor.core.context import UnifiedContext
from deeptutor.runtime.registry.tool_registry import get_tool_registry
from deeptutor.services.config import settings_spec as spec_module
from deeptutor.services.config.settings_spec import ProbeResult, setting_specs


@pytest.fixture
def isolated_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Route every settings read/write for this test into ``tmp_path``.

    Both roots are redirected because the two scopes genuinely live in
    different places: personal rows resolve through the path service, global
    rows through the runtime settings directory. A test that redirected only
    one would write the developer's real configuration.
    """
    from deeptutor.services.config import model_catalog, runtime_settings
    from deeptutor.services.path_service import PathService
    from deeptutor.services.settings import interface_settings

    user_root = tmp_path / "user"
    global_settings = tmp_path / "global" / "settings"
    global_settings.mkdir(parents=True, exist_ok=True)
    service = PathService(workspace_root=user_root)

    monkeypatch.setattr(interface_settings, "get_path_service", lambda: service)
    monkeypatch.setattr(model_catalog, "get_path_service", lambda: service)
    monkeypatch.setattr(runtime_settings, "_global_settings_dir", lambda: global_settings)
    return tmp_path


def _seed_catalog(tmp_path: Path, *, service: str, profile: str, model: str) -> None:
    """Write a catalog with one selectable model for ``service``."""
    from deeptutor.services.config.model_catalog import get_model_catalog_service

    catalog_service = get_model_catalog_service()
    catalog = catalog_service.load()
    catalog["services"][service] = {
        "active_profile_id": profile,
        "active_model_id": model,
        "profiles": [
            {
                "id": profile,
                "name": "Test profile",
                "binding": "openai",
                "base_url": "https://example.invalid/v1",
                "api_key": "sk-test",
                "models": [{"id": model, "name": model, "model": model}],
            }
        ],
    }
    catalog_service.save(catalog)


# ---------------------------------------------------------------------------
# Spec table
# ---------------------------------------------------------------------------


def test_every_spec_row_is_readable_and_offers_choices(isolated_settings: Path) -> None:
    specs = setting_specs()
    assert specs, "the spec table must not be empty"
    for key, spec in specs.items():
        assert spec.key == key
        assert spec.scope in {"personal", "global"}
        assert spec.effect in {"instant", "restart", "reindex"}
        assert spec.label and spec.summary
        spec.read()
        spec.choices()


@pytest.mark.asyncio
async def test_no_row_accepts_a_free_form_value(isolated_settings: Path) -> None:
    """Every row is an enumeration, which is what keeps secrets off this surface.

    ``request_credential`` exists because a key must never enter the model's
    context. That guarantee rests on the apply path refusing anything that is
    not one of the row's offered choices — if any row accepted arbitrary text,
    the model could be talked into writing a credential into it. Asserted per
    row rather than by naming suspicious keys, so a row added later is covered
    automatically.
    """
    for key in setting_specs():
        outcome = await apply_setting(key, "sk-arbitrary-free-form-value")
        assert not outcome.ok, f"{key} accepted a value it never offered"


# ---------------------------------------------------------------------------
# Apply: validation, scope, probe, rollback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_personal_setting_persists(isolated_settings: Path) -> None:
    from deeptutor.services.settings.interface_settings import get_ui_settings

    outcome = await apply_setting("interface.theme", "dark")

    assert outcome.ok
    assert outcome.value == "dark"
    assert outcome.previous == "snow"
    assert get_ui_settings()["theme"] == "dark"


@pytest.mark.asyncio
async def test_apply_reports_a_coupled_setting(isolated_settings: Path) -> None:
    outcome = await apply_setting("interface.language", "zh")

    assert outcome.ok
    coupled = {effect.key for effect in outcome.side_effects}
    assert "interface.response_language" in coupled, (
        "changing the interface language also switches replies on a file that "
        "predates the split; the user has to be told"
    )


@pytest.mark.asyncio
async def test_apply_can_be_reverted_with_the_returned_previous(
    isolated_settings: Path,
) -> None:
    from deeptutor.services.settings.interface_settings import get_ui_settings

    forward = await apply_setting("interface.theme", "glass")
    back = await apply_setting("interface.theme", forward.previous)

    assert back.ok
    assert get_ui_settings()["theme"] == "snow"


@pytest.mark.asyncio
async def test_apply_rejects_a_value_outside_the_offered_choices(
    isolated_settings: Path,
) -> None:
    from deeptutor.services.settings.interface_settings import get_ui_settings

    outcome = await apply_setting("interface.language", "klingon")

    assert not outcome.ok
    assert "not one of the available options" in outcome.error
    assert get_ui_settings()["language"] == "en"


@pytest.mark.asyncio
async def test_apply_rejects_an_unknown_key(isolated_settings: Path) -> None:
    outcome = await apply_setting("nope.nope", "x")

    assert not outcome.ok
    assert "Unknown setting" in outcome.error


@pytest.mark.asyncio
async def test_apply_rejects_an_engine_that_is_not_installed(
    isolated_settings: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A selectable-but-missing engine must not be committed.

    ``list_engines`` deliberately reports engines that are not installed so the
    agent can offer to install them; committing one anyway would leave document
    parsing pointed at an engine that raises on first use.
    """
    from deeptutor.services.config.runtime_settings import get_runtime_settings_service
    from deeptutor.services.parsing.engines import factory

    monkeypatch.setattr(factory, "is_engine_available", lambda name: name == "text_only")

    outcome = await apply_setting("document_parsing.engine", "docling")

    assert not outcome.ok
    stored = get_runtime_settings_service().load_document_parsing()
    assert stored["engine"] == "text_only"


@pytest.mark.asyncio
async def test_a_failing_probe_leaves_the_stored_value_untouched(
    isolated_settings: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The self-lockout guard: an unreachable model is never committed."""
    _seed_catalog(isolated_settings, service="llm", profile="p1", model="m1")

    from deeptutor.services.config.model_catalog import get_model_catalog_service

    catalog_service = get_model_catalog_service()
    catalog = catalog_service.load()
    catalog["services"]["llm"]["profiles"][0]["models"].append(
        {"id": "m2", "name": "m2", "model": "m2"}
    )
    catalog_service.save(catalog)

    async def _always_fails(value: str) -> ProbeResult:
        return ProbeResult(ok=False, detail="connection refused")

    monkeypatch.setattr(spec_module, "_probe_llm", _always_fails)

    outcome = await apply_setting("catalog.llm", "p1::m2")

    assert not outcome.ok
    assert outcome.probe is not None and not outcome.probe.ok
    assert "connection refused" in outcome.error
    stored = get_model_catalog_service().load()["services"]["llm"]
    assert stored["active_model_id"] == "m1", "a failed probe must not move the selection"


@pytest.mark.asyncio
async def test_a_passing_probe_commits(
    isolated_settings: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_catalog(isolated_settings, service="llm", profile="p1", model="m1")

    from deeptutor.services.config.model_catalog import get_model_catalog_service

    catalog_service = get_model_catalog_service()
    catalog = catalog_service.load()
    catalog["services"]["llm"]["profiles"][0]["models"].append(
        {"id": "m2", "name": "m2", "model": "m2"}
    )
    catalog_service.save(catalog)

    probed: list[str] = []

    async def _passes(value: str) -> ProbeResult:
        probed.append(value)
        return ProbeResult(ok=True, elapsed_ms=12)

    monkeypatch.setattr(spec_module, "_probe_llm", _passes)

    outcome = await apply_setting("catalog.llm", "p1::m2")

    assert outcome.ok, outcome.error
    assert probed == ["p1::m2"], "the candidate must be probed before it is stored"
    stored = get_model_catalog_service().load()["services"]["llm"]
    assert stored["active_model_id"] == "m2"


# ---------------------------------------------------------------------------
# Scope enforcement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_non_admin_cannot_write_a_global_row(
    isolated_settings: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from deeptutor.capabilities.setup import access

    monkeypatch.setattr(access, "_is_admin", lambda: False)
    monkeypatch.setattr(access, "_is_partner_turn", lambda: False)

    outcome = await apply_setting("document_parsing.engine", "markitdown")

    assert not outcome.ok
    assert "administrator" in outcome.error


@pytest.mark.asyncio
async def test_a_non_admin_can_still_write_a_personal_row(
    isolated_settings: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from deeptutor.capabilities.setup import access

    monkeypatch.setattr(access, "_is_admin", lambda: False)
    monkeypatch.setattr(access, "_is_partner_turn", lambda: False)

    outcome = await apply_setting("interface.theme", "dark")

    assert outcome.ok


@pytest.mark.asyncio
async def test_a_partner_turn_is_refused_for_every_scope(
    isolated_settings: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A partner acts under its owner's identity — it must not reconfigure them."""
    from deeptutor.capabilities.setup import access

    monkeypatch.setattr(access, "_is_partner_turn", lambda: True)

    personal = await apply_setting("interface.theme", "dark")
    global_row = await apply_setting("document_parsing.engine", "markitdown")

    assert not personal.ok
    assert not global_row.ok
    assert "partner" in personal.error.lower()


@pytest.mark.asyncio
async def test_run_setup_job_is_refused_for_a_non_admin(
    isolated_settings: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Installing software changes the machine for every account on it."""
    from deeptutor.capabilities.setup import access

    monkeypatch.setattr(access, "_is_admin", lambda: False)
    monkeypatch.setattr(access, "_is_partner_turn", lambda: False)

    result = await RunSetupJobTool().execute(action="install_engine", engine="docling")

    assert not result.success
    assert "administrator" in result.content


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_job_refuses_an_unknown_action(isolated_settings: Path) -> None:
    outcome = await run_job("rm_rf", "docling")

    assert not outcome.ok
    assert "Unknown setup job" in outcome.message


@pytest.mark.asyncio
async def test_run_job_refuses_an_engine_outside_the_install_allow_list(
    isolated_settings: Path,
) -> None:
    """The model names an engine id, never a package — the allow-list decides."""
    outcome = await run_job("install_engine", "requests")

    assert not outcome.ok
    assert "no one-step install" in outcome.message


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_inspect_reports_rows_gaps_and_jobs(isolated_settings: Path) -> None:
    result = await InspectSetupTool().execute()

    payload = json.loads(result.content)
    assert result.success
    assert {"settings", "gaps", "jobs_available"} <= set(payload)
    keys = {row["key"] for row in payload["settings"]}
    assert "interface.language" in keys
    assert "document_parsing.engine" in keys
    for row in payload["settings"]:
        assert "effect" in row and "scope" in row and "options" in row


@pytest.mark.asyncio
async def test_inspect_filters_by_area(isolated_settings: Path) -> None:
    result = await InspectSetupTool().execute(area="interface")

    payload = json.loads(result.content)
    assert {row["area"] for row in payload["settings"]} == {"interface"}


@pytest.mark.asyncio
async def test_apply_tool_marks_the_ui_slice_stale(isolated_settings: Path) -> None:
    """The frontend caches UI preferences; the result has to invalidate them."""
    result = await ApplySettingTool().execute(key="interface.theme", value="dark")

    assert result.success
    assert result.metadata.get("setup_applied") == {"key": "interface.theme"}


@pytest.mark.asyncio
async def test_credential_tool_hands_off_without_touching_the_secret(
    isolated_settings: Path,
) -> None:
    result = await RequestCredentialTool().execute(service="llm", reason="需要密钥")

    payload: dict[str, Any] = result.metadata["setup_credential"]
    assert result.success
    assert payload["settings_path"] == "/settings/llm"
    assert "api_key" not in result.content
    assert payload["reason"] == "需要密钥"


@pytest.mark.asyncio
async def test_credential_tool_rejects_an_unknown_service(isolated_settings: Path) -> None:
    result = await RequestCredentialTool().execute(service="mainframe")

    assert not result.success


# ---------------------------------------------------------------------------
# Activation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "message",
    [
        "把界面语言切成中文",
        "界面换成英文吧",
        "帮我配置一下 DeepTutor",
        "能不能换个解析引擎",
        "我想改用别的嵌入模型",
        "switch the chat model to something faster",
        "install a better pdf parser",
        "set up web search for me",
    ],
)
def test_activates_on_a_configuration_request(message: str) -> None:
    assert message_signals_setup(message)


@pytest.mark.parametrize(
    "message",
    [
        "这个配置文件太大了打不开",
        "change the subject please",
        "帮我总结这篇论文",
        "用中文回答我",
        "模型是怎么训练的？",
        "下载这篇论文的 PDF",
        "这个引擎的原理是什么",
        "search for papers about transformers",
        "解释一下 embedding 的原理",
        "",
    ],
)
def test_stays_out_of_unrelated_turns(message: str) -> None:
    assert not message_signals_setup(message)


def test_explicit_selection_activates_without_an_intent_match(
    isolated_settings: Path,
) -> None:
    context = UnifiedContext(
        user_message="hello",
        active_capability="setup",
        conversation_history=[{"role": "user", "content": "hi"}],
    )

    assert SetupCapability().is_active(context)


def test_capability_is_additive_not_exclusive() -> None:
    """A configuration request often arrives mid-task; the turn keeps its tools."""
    assert not getattr(SetupCapability(), "exclusive_tools", False)


def test_setup_tools_reach_the_turns_tool_surface(isolated_settings: Path) -> None:
    """The wiring test: registry → active capability → composed tool list.

    Registering the capability and registering its tools are two separate
    steps, and getting either wrong leaves the model with a prompt telling it
    to call tools it cannot see.
    """
    context = UnifiedContext(
        user_message="把界面语言切成中文",
        conversation_history=[{"role": "user", "content": "hi"}],
    )
    active = active_loop_capabilities(context)
    assert any(cap.name == "setup" for cap in active)

    composed = compose_enabled_tools(
        registry=get_tool_registry(),
        requested_tools=["web_search"],
        optional_whitelist=["web_search"],
        mount_flags=ToolMountFlags(),
        capability_owned=tuple(name for cap in active for name in cap.owned_tools),
        exclusive=any_exclusive_capability_active(context),
    )

    assert set(SETUP_TOOL_NAMES).issubset(composed)
    assert "web_search" in composed, "additive: the turn keeps its normal surface"


def test_setup_tools_stay_off_an_unrelated_turn(isolated_settings: Path) -> None:
    context = UnifiedContext(
        user_message="帮我总结这篇论文",
        conversation_history=[{"role": "user", "content": "hi"}],
    )
    active = active_loop_capabilities(context)

    assert not any(cap.name == "setup" for cap in active)
    composed = compose_enabled_tools(
        registry=get_tool_registry(),
        requested_tools=["web_search"],
        optional_whitelist=["web_search"],
        mount_flags=ToolMountFlags(),
        capability_owned=tuple(name for cap in active for name in cap.owned_tools),
        exclusive=any_exclusive_capability_active(context),
    )
    assert not set(SETUP_TOOL_NAMES) & set(composed)


def test_owned_tools_match_the_registered_names() -> None:
    assert SetupCapability().owned_tools == SETUP_TOOL_NAMES


# ---------------------------------------------------------------------------
# Robustness regressions — each of these was a real defect
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_hung_endpoint_cannot_hang_the_turn(
    isolated_settings: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A probe is bounded by its own deadline, not the runtime's retry policy.

    The LLM runtime defaults to 8 retries with a 120s transport timeout each, so
    an endpoint that accepts the connection and then goes quiet would have kept
    a live chat turn waiting roughly a quarter of an hour before reporting a
    failure. The probe therefore sets its own deadline and disables retries.
    """
    import asyncio

    from deeptutor.services.config.settings_spec import _PROBE_TIMEOUT_SECONDS, _probe_llm

    _seed_catalog(isolated_settings, service="llm", profile="p1", model="m1")
    seen: dict[str, Any] = {}

    async def _never_answers(*args: Any, **kwargs: Any) -> str:
        seen.update(kwargs)
        await asyncio.sleep(3600)
        return "unreachable"

    import deeptutor.services.llm as llm_module

    monkeypatch.setattr(llm_module, "complete", _never_answers)
    monkeypatch.setattr(spec_module, "_PROBE_TIMEOUT_SECONDS", 0.2)

    result = await asyncio.wait_for(_probe_llm("p1::m1"), timeout=10)

    assert not result.ok
    assert "No response within" in result.detail
    assert seen.get("max_retries") == 0, "a probe must not inherit the runtime's 8 retries"
    assert _PROBE_TIMEOUT_SECONDS <= 60, "the shipped deadline must stay inside a turn's patience"


def test_the_first_run_offer_is_not_spent_by_an_ordinary_request(
    isolated_settings: Path,
) -> None:
    """Only an ``intro`` activation may consume the once-ever proactive offer.

    Marking it from every setup turn meant the first time a user asked for
    anything at all ("change the theme") the offer was silently used up, and an
    install that genuinely needed help was never offered any.
    """
    from deeptutor.capabilities.setup.binding import setup_activation

    capability = SetupCapability()
    asked = UnifiedContext(
        user_message="把界面主题换成暗色",
        conversation_history=[{"role": "user", "content": "hi"}],
    )
    assert setup_activation(asked) == "intent"
    capability.system_block(asked, language="zh", prompts={})

    fresh = UnifiedContext(user_message="你好", conversation_history=[])
    assert setup_activation(fresh) == "intro", "the first-run offer must still be available"


def test_the_first_run_offer_is_spent_once(isolated_settings: Path) -> None:
    from deeptutor.capabilities.setup.binding import setup_activation

    capability = SetupCapability()
    first = UnifiedContext(user_message="你好", conversation_history=[])
    assert setup_activation(first) == "intro"
    block = capability.system_block(first, language="en", prompts={})
    assert block is not None
    assert "first conversation" in block.content

    second = UnifiedContext(user_message="你好", conversation_history=[])
    assert setup_activation(second) == "", "the offer must not repeat every new chat"


def test_concurrent_preference_writes_do_not_lose_updates(isolated_settings: Path) -> None:
    """``interface.json`` is a read-modify-write on a shared document.

    Unlocked, twelve concurrent writers left two of their fields on disk — the
    rest were overwritten by whichever writer had read an older snapshot.
    """
    import json as json_module
    import threading

    from deeptutor.services.settings.interface_settings import (
        _interface_settings_file,
        set_ui_setting,
    )

    def writer(index: int) -> None:
        for _ in range(20):
            set_ui_setting(f"probe_{index}", index)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    stored = json_module.loads(_interface_settings_file().read_text(encoding="utf-8"))
    assert {f"probe_{i}" for i in range(12)} <= set(stored)


def test_unresolvable_identity_refuses_global_writes(
    isolated_settings: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Failing to resolve who is asking must not grant administrator rights."""
    from deeptutor.capabilities.setup import access

    def _explode() -> Any:
        raise RuntimeError("identity backend down")

    monkeypatch.setattr(access, "_is_partner_turn", lambda: False)
    monkeypatch.setattr("deeptutor.multi_user.context.get_current_user", _explode)

    assert access.can_write("global").allowed is False
    assert access.can_write("personal").allowed is True, "personal rows stay reachable"


@pytest.mark.asyncio
async def test_a_silent_job_still_emits_progress(
    isolated_settings: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A quiet install must not look dead to the chat client.

    The client times out on time since the last event, and pip can download a
    large wheel for minutes without printing anything — so a job that only
    relays real output would have its turn declared dead while healthy.
    """
    from deeptutor.capabilities.setup import jobs

    class _SilentManager:
        def __init__(self) -> None:
            self.polls = 0

        def status(self, cursor: int = 0) -> dict[str, Any]:
            self.polls += 1
            state = "running" if self.polls < 8 else "done"
            return {"state": state, "lines": [], "next_cursor": 0, "message": "Finished."}

    manager = _SilentManager()
    monkeypatch.setattr(jobs, "_start_install", lambda engine: (True, "", manager))
    monkeypatch.setattr(jobs, "_POLL_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(jobs, "_HEARTBEAT_SECONDS", 0.02)

    beats: list[str] = []

    async def _on_line(line: str) -> None:
        beats.append(line)

    outcome = await jobs.run_job("install_engine", "docling", on_line=_on_line)

    assert outcome.ok
    assert beats, "a silent job must still emit keep-alives"
    assert all("still working" in beat for beat in beats)


def test_setup_jobs_are_never_listed_twice(isolated_settings: Path) -> None:
    from deeptutor.capabilities.setup.jobs import available_jobs

    jobs = [(job["action"], job["engine"]) for job in available_jobs()]
    assert len(jobs) == len(set(jobs))


def test_system_block_names_the_installs_gaps(isolated_settings: Path) -> None:
    context = UnifiedContext(user_message="帮我配置一下 DeepTutor")

    block = SetupCapability().system_block(context, language="zh", prompts={})

    assert block is not None
    assert "missing" in block.content
    assert setup_gaps(), "a fresh install has gaps, so the block should list them"
