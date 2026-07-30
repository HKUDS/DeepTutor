"""Curated MCP catalog: data integrity, credential targeting, search/pagination."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from deeptutor.services.mcp.catalog import loader
from deeptutor.services.mcp.catalog.loader import (
    category_counts,
    get_entry,
    load_catalog,
    reset_catalog_cache,
    search_catalog,
)
from deeptutor.services.mcp.catalog.models import (
    CATALOG_CATEGORIES,
    CATALOG_TIERS,
    ENTRY_ID_RE,
    CredentialField,
    McpCatalogEntry,
    build_server_config,
    localized_text,
    normalize_transport,
)
from deeptutor.services.mcp.config import MCPServerConfig
from deeptutor.services.mcp.secrets import SECRET_REFERENCE_RE

#: The vendored catalog's size, asserted so an edit that guts it is visible in
#: a diff rather than silently shipping an empty store.
VENDORED_ENTRY_COUNT = 45
VENDORED_SELF_SERVICE_COUNT = 38


@pytest.fixture(autouse=True)
def _fresh_catalog_cache() -> Any:
    reset_catalog_cache()
    yield
    reset_catalog_cache()


# --------------------------------------------------------------------------- #
# Vendored data integrity
# --------------------------------------------------------------------------- #


def test_every_vendored_entry_parses() -> None:
    raw = json.loads(loader.CATALOG_PATH.read_text(encoding="utf-8"))
    assert len(load_catalog()) == len(raw["entries"]), "an entry failed validation and was skipped"


def test_vendored_entry_count_is_stable() -> None:
    entries = load_catalog()
    assert len(entries) == VENDORED_ENTRY_COUNT
    assert sum(1 for entry in entries if entry.self_service) == VENDORED_SELF_SERVICE_COUNT


def test_entry_ids_are_unique_and_well_formed() -> None:
    entries = load_catalog()
    ids = [entry.id for entry in entries]
    assert len(set(ids)) == len(ids)
    for entry_id in ids:
        # An id is reused verbatim as the server name and the secrets filename.
        assert ENTRY_ID_RE.match(entry_id), entry_id


def test_every_stdio_entry_is_admin_only() -> None:
    for entry in load_catalog():
        if entry.transport == "stdio":
            assert entry.self_service is False, entry.id


def test_remote_entries_carry_a_url_and_no_command() -> None:
    for entry in load_catalog():
        if entry.transport == "stdio":
            assert entry.server_template.command
            continue
        assert entry.server_template.url.startswith("https://"), entry.id
        assert not entry.server_template.command, entry.id


def test_every_credential_field_declares_a_reachable_target() -> None:
    for entry in load_catalog():
        for spec in entry.fields:
            kind, name = spec.target
            assert name, f"{entry.id}/{spec.key}"
            if entry.transport == "stdio":
                assert kind in {"env", "arg"}, f"{entry.id}/{spec.key}"
            else:
                assert kind in {"header", "url_param"}, f"{entry.id}/{spec.key}"


def test_required_credentials_are_secret_and_labelled() -> None:
    for entry in load_catalog():
        for spec in entry.fields:
            assert spec.label("en"), f"{entry.id}/{spec.key}"
            assert spec.label("zh"), f"{entry.id}/{spec.key}"
            if spec.required:
                assert spec.secret, f"{entry.id}/{spec.key} is required but not treated as secret"


def test_descriptions_are_bilingual() -> None:
    for entry in load_catalog():
        assert entry.description("en"), entry.id
        assert entry.description("zh"), entry.id


def test_no_third_party_logo_urls() -> None:
    # A remote logo would hand its host every user's installed-service list.
    for entry in load_catalog():
        assert not entry.logo_url.startswith("http"), entry.id


def test_categories_and_tiers_stay_inside_the_closed_enums() -> None:
    counts = category_counts()
    assert set(counts) == set(CATALOG_CATEGORIES)
    for entry in load_catalog():
        assert entry.category in CATALOG_CATEGORIES
        assert entry.tier in CATALOG_TIERS


# --------------------------------------------------------------------------- #
# normalize_transport
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "spelling",
    ["streamableHttp", "streamable-http", "streamable_http", "http", "  HTTP  "],
)
def test_normalize_transport_collapses_every_streamable_spelling(spelling: str) -> None:
    assert normalize_transport(spelling) == "streamableHttp"


def test_normalize_transport_passes_through_stdio_and_sse() -> None:
    assert normalize_transport("stdio") == "stdio"
    assert normalize_transport("SSE") == "sse"


@pytest.mark.parametrize("junk", ["", "websocket", "grpc", "streamable", "http2"])
def test_normalize_transport_rejects_junk(junk: str) -> None:
    with pytest.raises(ValueError):
        normalize_transport(junk)


def test_localized_text_degrades_to_english() -> None:
    texts = {"en": "hello", "zh": "你好"}
    assert localized_text(texts, "zh-CN") == "你好"
    assert localized_text(texts, "fr") == "hello"
    assert localized_text({"de": "hallo"}, "fr") == "hallo"


# --------------------------------------------------------------------------- #
# build_server_config
# --------------------------------------------------------------------------- #


def _entry(**overrides: Any) -> McpCatalogEntry:
    base: dict[str, Any] = {
        "id": "probe",
        "display_name": "Probe",
        "description_i18n": {"en": "probe"},
        "category": "utility",
        "tier": "curated",
        "transport": "streamableHttp",
        "server_template": MCPServerConfig(type="streamableHttp", url="https://probe.test/mcp"),
    }
    base.update(overrides)
    return McpCatalogEntry(**base)


def test_build_puts_a_header_credential_at_its_declared_header() -> None:
    entry = _entry(
        fields=(
            CredentialField(
                key="token",
                label_i18n={"en": "Token"},
                target=("header", "X-Probe-Key"),
            ),
        )
    )
    built = build_server_config(entry, {"token": "s3cret"})
    assert built.config.headers["X-Probe-Key"] == "${secret:probe/token}"
    assert built.secret_values == {"token": "s3cret"}


def test_build_puts_a_url_param_credential_in_the_query_string() -> None:
    entry = _entry(
        fields=(
            CredentialField(
                key="api_key",
                label_i18n={"en": "Key"},
                target=("url_param", "probeApiKey"),
            ),
        )
    )
    built = build_server_config(entry, {"api_key": "s3cret"})
    assert built.config.url == "https://probe.test/mcp?probeApiKey=${secret:probe/api_key}"


def test_build_replaces_an_existing_url_param_rather_than_duplicating_it() -> None:
    entry = _entry(
        server_template=MCPServerConfig(
            type="streamableHttp", url="https://probe.test/mcp?probeApiKey=stale&keep=1"
        ),
        fields=(
            CredentialField(
                key="api_key", label_i18n={"en": "Key"}, target=("url_param", "probeApiKey")
            ),
        ),
    )
    url = build_server_config(entry, {"api_key": "s3cret"}).config.url
    assert url.count("probeApiKey") == 1
    assert "keep=1" in url
    assert "stale" not in url


def test_build_puts_env_and_arg_credentials_on_a_stdio_entry() -> None:
    entry = _entry(
        transport="stdio",
        self_service=False,
        server_template=MCPServerConfig(type="stdio", command="npx", args=["-y", "probe-mcp"]),
        fields=(
            CredentialField(key="env_key", label_i18n={"en": "E"}, target=("env", "PROBE_KEY")),
            CredentialField(key="arg_key", label_i18n={"en": "A"}, target=("arg", "--api-key")),
        ),
    )
    built = build_server_config(entry, {"env_key": "one", "arg_key": "two"})
    assert built.config.env["PROBE_KEY"] == "${secret:probe/env_key}"
    assert built.config.args == ["-y", "probe-mcp", "--api-key", "${secret:probe/arg_key}"]
    assert built.secret_values == {"env_key": "one", "arg_key": "two"}


def test_build_never_leaks_a_raw_secret_into_the_config() -> None:
    entry = _entry(
        fields=(
            CredentialField(key="a", label_i18n={"en": "A"}, target=("header", "X-A")),
            CredentialField(key="b", label_i18n={"en": "B"}, target=("url_param", "b")),
        )
    )
    built = build_server_config(entry, {"a": "raw-alpha", "b": "raw-bravo"})
    serialized = json.dumps(built.config.model_dump(mode="json"))
    assert "raw-alpha" not in serialized
    assert "raw-bravo" not in serialized
    assert "${secret:probe/a}" in serialized
    assert "${secret:probe/b}" in serialized


def test_secret_reference_form_matches_the_resolver_the_manager_uses() -> None:
    # The reference is only useful if the connect-time resolver recognises it,
    # and that resolver matches a *whole* value.
    entry = _entry(
        fields=(CredentialField(key="token", label_i18n={"en": "T"}, target=("header", "X-T")),)
    )
    built = build_server_config(entry, {"token": "s3cret"})
    assert SECRET_REFERENCE_RE.match(built.config.headers["X-T"])


def test_value_template_is_a_store_time_rule_not_a_config_time_one() -> None:
    # "Bearer ${secret:...}" would not match the whole-value resolver, so the
    # prefix has to be baked into the stored value instead.
    spec = CredentialField(
        key="token",
        label_i18n={"en": "T"},
        target=("header", "Authorization"),
        value_template="Bearer {value}",
    )
    assert spec.render("ghp_x") == "Bearer ghp_x"
    built = build_server_config(_entry(fields=(spec,)), {"token": "ghp_x"})
    assert built.config.headers["Authorization"] == "${secret:probe/token}"
    # …and the decoration rides on the value the caller is told to store.
    assert built.secret_values == {"token": "Bearer ghp_x"}


def test_build_inlines_a_non_secret_value_with_its_template() -> None:
    entry = _entry(
        fields=(
            CredentialField(
                key="project",
                label_i18n={"en": "P"},
                target=("url_param", "project_ref"),
                secret=False,
            ),
        )
    )
    built = build_server_config(entry, {"project": "abc123"})
    assert built.config.url.endswith("?project_ref=abc123")
    assert built.secret_values == {}


def test_build_skips_an_empty_optional_field_and_refuses_an_empty_required_one() -> None:
    optional = CredentialField(
        key="api_key", label_i18n={"en": "K"}, target=("header", "X-K"), required=False
    )
    assert build_server_config(_entry(fields=(optional,)), {}).config.headers == {}

    required = CredentialField(key="api_key", label_i18n={"en": "K"}, target=("header", "X-K"))
    with pytest.raises(ValueError, match="Missing required credential"):
        build_server_config(_entry(fields=(required,)), {"api_key": "   "})


def test_build_does_not_mutate_the_shared_template() -> None:
    entry = _entry(
        fields=(CredentialField(key="token", label_i18n={"en": "T"}, target=("header", "X-T")),)
    )
    build_server_config(entry, {"token": "s3cret"})
    assert entry.server_template.headers == {}


def test_a_real_bearer_entry_builds_a_resolvable_config() -> None:
    built = build_server_config(get_entry("github"), {"token": "ghp_x"})  # type: ignore[arg-type]
    assert built.config.headers == {"Authorization": "${secret:github/token}"}
    # Decorated on the way to the store, because the config side holds only a
    # bare reference — the vendor must still receive the scheme.
    assert built.secret_values == {"token": "Bearer ghp_x"}


# --------------------------------------------------------------------------- #
# Entry invariants
# --------------------------------------------------------------------------- #


def test_a_stdio_entry_cannot_be_self_service() -> None:
    with pytest.raises(ValueError, match="cannot be self-service"):
        _entry(
            transport="stdio",
            self_service=True,
            server_template=MCPServerConfig(type="stdio", command="npx"),
        )


def test_a_declared_transport_must_match_its_server_template() -> None:
    with pytest.raises(ValueError, match="resolves to"):
        _entry(server_template=MCPServerConfig(type="stdio", command="npx"), self_service=False)


def test_an_env_credential_is_refused_on_a_remote_entry() -> None:
    with pytest.raises(ValueError, match="cannot carry"):
        _entry(fields=(CredentialField(key="k", label_i18n={"en": "K"}, target=("env", "PROBE")),))


@pytest.mark.parametrize("bad_id", ["Probe", "-probe", "pro be", "pro.be", "x" * 65, ""])
def test_entry_id_pattern_is_enforced(bad_id: str) -> None:
    with pytest.raises(ValueError, match="Invalid catalog entry id"):
        _entry(id=bad_id)


def test_duplicate_credential_keys_are_refused() -> None:
    spec = CredentialField(key="dup", label_i18n={"en": "D"}, target=("header", "X-A"))
    other = CredentialField(key="dup", label_i18n={"en": "D"}, target=("header", "X-B"))
    with pytest.raises(ValueError, match="repeats credential field"):
        _entry(fields=(spec, other))


def test_a_value_template_without_a_placeholder_is_refused() -> None:
    with pytest.raises(ValueError, match="must contain"):
        CredentialField(
            key="k", label_i18n={"en": "K"}, target=("header", "X-K"), value_template="Bearer"
        )


# --------------------------------------------------------------------------- #
# Search, filter, pagination
# --------------------------------------------------------------------------- #


def test_search_matches_display_name_and_description() -> None:
    assert "wolfram" in {entry.id for entry in search_catalog(q="Wolfram").entries}
    hits = {entry.id for entry in search_catalog(q="knowledge graph").entries}
    assert "memory" in hits


def test_search_is_case_insensitive_and_can_miss() -> None:
    assert {entry.id for entry in search_catalog(q="STRIPE").entries} == {"stripe"}
    assert search_catalog(q="zzz-no-such-service").entries == ()


def test_category_filter_returns_only_that_category() -> None:
    page = search_catalog(category="maps", limit=100)
    assert page.entries
    assert {entry.category for entry in page.entries} == {"maps"}
    assert page.total == category_counts()["maps"]


def test_tier_filter_separates_curated_from_registry() -> None:
    registry = search_catalog(tier="registry", limit=100)
    assert registry.entries
    assert {entry.tier for entry in registry.entries} == {"registry"}
    curated = search_catalog(tier="curated", limit=100)
    assert curated.total + registry.total == len(load_catalog())


def test_self_service_filter_hides_every_stdio_entry() -> None:
    page = search_catalog(limit=100, self_service_only=True)
    assert page.entries
    assert all(entry.transport != "stdio" for entry in page.entries)
    assert page.total == VENDORED_SELF_SERVICE_COUNT


def test_cursor_pagination_walks_the_whole_catalog_exactly_once() -> None:
    seen: list[str] = []
    cursor = ""
    for _ in range(20):
        page = search_catalog(cursor=cursor, limit=7)
        seen.extend(entry.id for entry in page.entries)
        cursor = page.next_cursor
        if not cursor:
            break
    assert cursor == ""
    assert seen == [entry.id for entry in load_catalog()]
    assert len(set(seen)) == len(seen)


def test_cursor_pagination_respects_an_active_filter() -> None:
    first = search_catalog(category="docs", limit=3)
    assert len(first.entries) == 3
    assert first.next_cursor == "3"
    second = search_catalog(category="docs", cursor=first.next_cursor, limit=3)
    assert {entry.category for entry in second.entries} == {"docs"}
    assert not set(entry.id for entry in second.entries) & set(e.id for e in first.entries)


def test_a_junk_cursor_serves_the_first_page_instead_of_failing() -> None:
    assert search_catalog(cursor="not-a-number", limit=3).entries == search_catalog(limit=3).entries


def test_limit_is_clamped() -> None:
    assert len(search_catalog(limit=0).entries) == 1
    assert len(search_catalog(limit=10_000).entries) == min(
        loader.MAX_PAGE_SIZE, len(load_catalog())
    )


def test_get_entry_is_exact_match_only() -> None:
    assert get_entry("exa") is not None
    assert get_entry("Exa") is None
    assert get_entry("nope") is None


# --------------------------------------------------------------------------- #
# Loader resilience
# --------------------------------------------------------------------------- #


def _write_catalog(tmp_path: Path, entries: list[dict[str, Any]]) -> Path:
    path = tmp_path / "curated.json"
    path.write_text(json.dumps({"version": 1, "entries": entries}), encoding="utf-8")
    return path


_GOOD_ENTRY: dict[str, Any] = {
    "id": "good",
    "display_name": "Good",
    "category": "utility",
    "tier": "curated",
    "transport": "streamable-http",
    "description": {"en": "fine"},
    "server": {"url": "https://good.test/mcp"},
}


def test_a_malformed_entry_is_skipped_not_fatal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broken = [
        {"id": "BAD CASE", **{k: v for k, v in _GOOD_ENTRY.items() if k != "id"}},
        {"id": "no-server", "display_name": "X", "category": "utility", "transport": "http"},
        {"id": "bad-transport", **{**_GOOD_ENTRY, "transport": "carrier-pigeon", "id": "bad-tp"}},
        {"id": "bad-category", **{**_GOOD_ENTRY, "category": "fishing", "id": "bad-cat"}},
        {
            "id": "stdio-self-service",
            "display_name": "X",
            "category": "utility",
            "transport": "stdio",
            "description": {"en": "x"},
            "self_service": True,
            "server": {"command": "npx"},
        },
        "not-even-an-object",
        _GOOD_ENTRY,
    ]
    monkeypatch.setattr(loader, "CATALOG_PATH", _write_catalog(tmp_path, broken))  # type: ignore[arg-type]
    reset_catalog_cache()
    entries = load_catalog()
    assert [entry.id for entry in entries] == ["good"]
    # ...and the surviving entry still normalised its registry-spelled transport.
    assert entries[0].transport == "streamableHttp"


def test_a_duplicate_id_keeps_the_first_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    twin = {**_GOOD_ENTRY, "display_name": "Impostor"}
    monkeypatch.setattr(loader, "CATALOG_PATH", _write_catalog(tmp_path, [_GOOD_ENTRY, twin]))
    reset_catalog_cache()
    entries = load_catalog()
    assert len(entries) == 1
    assert entries[0].display_name == "Good"


def test_an_unreadable_catalog_yields_an_empty_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "curated.json"
    path.write_text("{ not json", encoding="utf-8")
    monkeypatch.setattr(loader, "CATALOG_PATH", path)
    reset_catalog_cache()
    assert load_catalog() == ()

    monkeypatch.setattr(loader, "CATALOG_PATH", tmp_path / "missing.json")
    reset_catalog_cache()
    assert load_catalog() == ()


def test_the_catalog_is_parsed_once(monkeypatch: pytest.MonkeyPatch) -> None:
    load_catalog()
    calls = 0
    real_read = Path.read_text

    def counting_read(self: Path, *args: Any, **kwargs: Any) -> str:
        nonlocal calls
        if self == loader.CATALOG_PATH:
            calls += 1
        return real_read(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counting_read)
    load_catalog()
    load_catalog()
    assert calls == 0, "the vendored catalog must be cached, not re-read per request"


# --------------------------------------------------------------------------- #
# Install → connect round trip
# --------------------------------------------------------------------------- #


@pytest.fixture
def system_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from deeptutor.multi_user import paths

    root = (tmp_path / "data" / "system").resolve()
    monkeypatch.setattr(paths, "SYSTEM_ROOT", root)
    monkeypatch.setattr(paths, "ADMIN_WORKSPACE_ROOT", (tmp_path / "data").resolve())
    monkeypatch.setattr(paths, "USERS_ROOT", (tmp_path / "data" / "users").resolve())
    return root


@pytest.mark.parametrize(
    "entry_id",
    [entry.id for entry in load_catalog() if any(f.target[0] == "url_param" for f in entry.fields)],
)
def test_a_query_parameter_entry_resolves_end_to_end(entry_id: str, system_root: Path) -> None:
    """Install → store → connect must leave no ``${secret:...}`` on the wire.

    A query-parameter credential is not a whole-value reference, so this is the
    path that would silently transmit the literal placeholder to the vendor and
    fail with an opaque 401 at tool-call time.
    """
    from deeptutor.services.mcp.manager import MCPConnectionManager
    from deeptutor.services.mcp.secrets import store_secrets

    entry = get_entry(entry_id)
    assert entry is not None
    built = build_server_config(entry, dict.fromkeys((f.key for f in entry.fields), "tok-1"))
    store_secrets("u_ada", entry.id, built.secret_values)

    materialized = MCPConnectionManager._materialize(built.config, "u_ada")

    assert "${secret:" not in materialized.url, entry_id
    assert "tok-1" in materialized.url, entry_id


def test_every_vendored_secret_resolves_wherever_it_was_targeted(system_root: Path) -> None:
    """Sweep the whole catalog: no entry may keep a reference after resolution."""
    from deeptutor.services.mcp.manager import MCPConnectionManager
    from deeptutor.services.mcp.secrets import store_secrets

    for entry in load_catalog():
        if not entry.fields:
            continue
        built = build_server_config(entry, dict.fromkeys((f.key for f in entry.fields), "tok-1"))
        store_secrets("u_ada", entry.id, built.secret_values)
        materialized = MCPConnectionManager._materialize(built.config, "u_ada")
        serialized = json.dumps(materialized.model_dump(mode="json"))
        assert "${secret:" not in serialized, entry.id


def test_category_counts_can_exclude_admin_only_entries() -> None:
    """A chip that opens to an empty grid is the failure the enum exists to stop."""
    everything = category_counts()
    self_service = category_counts(self_service_only=True)

    assert sum(self_service.values()) == VENDORED_SELF_SERVICE_COUNT
    assert sum(everything.values()) == VENDORED_ENTRY_COUNT
    for category, count in self_service.items():
        # Every category the per-user store offers must have something in it.
        page = search_catalog(category=category, self_service_only=True, limit=100)
        assert page.total == count


def test_a_remote_entry_carrying_a_command_is_refused() -> None:
    """The loader stamps ``type`` from ``transport``, so the shape is the real check."""
    with pytest.raises(ValueError, match="needs a url and no command"):
        McpCatalogEntry(
            id="ghost",
            display_name="Ghost",
            description_i18n={"en": "d"},
            category=CATALOG_CATEGORIES[0],
            tier="curated",
            transport="streamableHttp",
            server_template=MCPServerConfig(type="streamableHttp", command="npx"),
        )


def test_a_stdio_entry_without_a_command_is_refused() -> None:
    with pytest.raises(ValueError, match="needs a command and no url"):
        McpCatalogEntry(
            id="ghost",
            display_name="Ghost",
            description_i18n={"en": "d"},
            category=CATALOG_CATEGORIES[0],
            tier="curated",
            transport="stdio",
            self_service=False,
            server_template=MCPServerConfig(type="stdio", url="https://ghost.test/mcp"),
        )
