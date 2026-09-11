from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import sys

import yaml


def _load_module():
    module_path = Path(__file__).resolve().parents[2] / "scripts" / "docker_compose.py"
    spec = importlib.util.spec_from_file_location("docker_compose_under_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        return module
    finally:
        sys.modules.pop(spec.name, None)


def test_render_docker_env_reads_json_only(tmp_path: Path) -> None:
    module = _load_module()
    settings_dir = tmp_path / "settings"
    settings_dir.mkdir()
    (settings_dir / "system.json").write_text(
        json.dumps({"backend_port": 9001, "frontend_port": 4000}),
        encoding="utf-8",
    )
    (settings_dir / "integrations.json").write_text(
        json.dumps({"pocketbase_port": 19090}),
        encoding="utf-8",
    )
    output_path = tmp_path / "docker.env"

    values = module.render_docker_env(settings_dir, output_path)

    assert values == {
        "DEEPTUTOR_DOCKER_BACKEND_PORT": "9001",
        "DEEPTUTOR_DOCKER_FRONTEND_PORT": "4000",
        "DEEPTUTOR_DOCKER_POCKETBASE_PORT": "19090",
    }
    saved = output_path.read_text(encoding="utf-8")
    assert "\nBACKEND_PORT=" not in saved
    assert "DEEPTUTOR_DOCKER_BACKEND_PORT=9001" in saved


def test_render_docker_env_uses_defaults_for_missing_or_invalid_json(tmp_path: Path) -> None:
    module = _load_module()
    settings_dir = tmp_path / "settings"
    settings_dir.mkdir()
    (settings_dir / "system.json").write_text(
        json.dumps({"backend_port": "bad", "frontend_port": 70000}),
        encoding="utf-8",
    )
    output_path = tmp_path / "docker.env"

    values = module.render_docker_env(settings_dir, output_path)

    assert values["DEEPTUTOR_DOCKER_BACKEND_PORT"] == "8001"
    assert values["DEEPTUTOR_DOCKER_FRONTEND_PORT"] == "3782"
    assert values["DEEPTUTOR_DOCKER_POCKETBASE_PORT"] == "8090"


def test_workspace_host_prepares_nested_outputs(tmp_path: Path) -> None:
    module = _load_module()
    root = module.ensure_workspace_host(str(tmp_path / "chosen"))

    assert root == (tmp_path / "chosen").resolve()
    assert (root / "outputs").is_dir()


def test_compose_maps_one_stable_content_workspace() -> None:
    root = Path(__file__).resolve().parents[2]
    source = (root / "docker-compose.yml").read_text(encoding="utf-8")

    assert "DEEPTUTOR_WORKSPACE_HOST:-./data/user/workspace" in source
    assert "DEEPTUTOR_WORKSPACE_ROOT=/workspace" in source
    assert ':/workspace:ro"' in source
    assert '/outputs:/workspace/outputs"' in source
    assert "DEEPTUTOR_RUNNER_ALLOWED_WORKDIRS=/workspace/outputs" in source


def test_compose_files_do_not_consume_legacy_env_names() -> None:
    root = Path(__file__).resolve().parents[2]
    for name in ("docker-compose.yml", "docker-compose.ghcr.yml"):
        content = (root / name).read_text(encoding="utf-8")
        assert "${BACKEND_PORT" not in content
        assert "${FRONTEND_PORT" not in content
        assert "\n      - BACKEND_PORT" not in content
        assert "\n      - AUTH_ENABLED" not in content
        assert "DEEPTUTOR_DOCKER_BACKEND_PORT" in content


def _compose_service(root: Path, name: str) -> dict:
    content = yaml.safe_load((root / name).read_text(encoding="utf-8"))
    return content["services"]["deeptutor"]


def _volume_targets(root: Path, name: str) -> set[str | None]:
    volumes = _compose_service(root, name).get("volumes", [])
    return {
        (volume.get("target") if isinstance(volume, dict) else str(volume).split(":")[1])
        for volume in volumes
    }


def test_default_compose_files_do_not_reserve_codex_callback_ports() -> None:
    """The fixed Codex callback ports are opt-in because other clients use them."""
    root = Path(__file__).resolve().parents[2]
    for name in ("docker-compose.yml", "docker-compose.ghcr.yml", "compose.yaml"):
        ports = _compose_service(root, name).get("ports", [])
        assert not any(re.search(r"(^|:)145[57]:", str(port)) for port in ports), name


def test_codex_oauth_overlay_forwards_loopback_callbacks_to_frontend() -> None:
    """The temporary overlay routes browser callbacks through the Web broker."""
    root = Path(__file__).resolve().parents[2]
    ports = _compose_service(root, "compose.codex-oauth.yaml")["ports"]

    assert set(ports) == {
        "127.0.0.1:1455:${DEEPTUTOR_DOCKER_FRONTEND_PORT:-3782}",
        "127.0.0.1:1457:${DEEPTUTOR_DOCKER_FRONTEND_PORT:-3782}",
    }


def test_official_container_manifests_persist_codex_credentials() -> None:
    """Container recreation must retain data/system, where Codex tokens live."""
    root = Path(__file__).resolve().parents[2]
    for name in ("docker-compose.yml", "docker-compose.ghcr.yml", "compose.yaml"):
        targets = _volume_targets(root, name)
        assert "/app/data" in targets or "/app/data/system" in targets, name


def test_ghcr_compose_persists_complete_data_tree() -> None:
    """Forced recreation must retain every workspace as well as OAuth tokens."""
    root = Path(__file__).resolve().parents[2]
    volumes = _compose_service(root, "docker-compose.ghcr.yml")["volumes"]

    assert "./data:/app/data" in volumes


def test_container_docs_use_temporary_codex_oauth_bridge() -> None:
    """README links to the canonical guide, which owns the exact commands."""
    root = Path(__file__).resolve().parents[2]
    readme = (root / "README.md").read_text(encoding="utf-8")
    guide = (root / "CONTAINERIZATION.md").read_text(encoding="utf-8")
    heading = "### Temporary local Codex OAuth bridge"
    assert heading in guide, f"{heading} was renamed; update this test with it"
    section = guide.split(heading, 1)[1].split("\n### ", 1)[0]
    normalized_section = " ".join(section.replace("\\\n", " ").split())

    assert "CONTAINERIZATION.md#temporary-local-codex-oauth-bridge" in readme
    assert "127.0.0.1:1455:3782" in section
    assert "127.0.0.1:1457:3782" in section
    for base_file in ("docker-compose.yml", "docker-compose.ghcr.yml"):
        assert (
            f"-f {base_file} -f compose.codex-oauth.yaml up -d --force-recreate deeptutor"
        ) in normalized_section
    assert (
        "podman compose -f compose.yaml -f compose.codex-oauth.yaml "
        "up -d --force-recreate deeptutor"
    ) in normalized_section


def test_dockerfile_is_json_driven_without_bundle_sed() -> None:
    """The image no longer rewrites the built bundle at startup (the runtime
    ``sed -i`` broke under a read-only rootfs). URL/auth knowledge is JSON-driven:
    the entrypoint re-exports runtime settings from data/user/settings/*.json
    (including DEEPTUTOR_API_BASE_URL / DEEPTUTOR_AUTH_ENABLED) and web/proxy.ts
    forwards /api/* and /ws/* to the backend at request time."""
    root = Path(__file__).resolve().parents[2]
    content = (root / "Dockerfile").read_text(encoding="utf-8")
    # The build-time placeholder + runtime bundle sed mechanism is gone.
    assert "__NEXT_PUBLIC_API_BASE_PLACEHOLDER__" not in content
    assert "__NEXT_PUBLIC_AUTH_ENABLED_PLACEHOLDER__" not in content
    # Still JSON-driven: stale runtime env names are ignored and re-exported
    # from the settings JSON on every start.
    assert "DEEPTUTOR_IGNORE_PROCESS_ENV_OVERRIDES=1" in content
    assert 'unset "$key"' in content
    assert "export_runtime_settings_to_env" in content


def test_supervisord_runs_as_root_with_unprivileged_children() -> None:
    """supervisord itself must run as root so it can open the container's
    stdout/stderr (``/dev/fd/1,2`` — root-owned pipes under a rootful daemon
    such as Docker Desktop) and write its pidfile under ``/var/run``. Dropping
    supervisord to the unprivileged ``deeptutor`` user via ``gosu`` made child
    spawning fail with ``EACCES`` ("making dispatchers ... EACCES"), so neither
    the backend nor the frontend started under rootful Docker (it only worked
    under rootless podman). The app processes stay non-root via the per-program
    ``user=deeptutor`` directive instead, which keeps them unprivileged in both
    runtimes. This guards against reintroducing the ``gosu`` privilege drop.
    """
    root = Path(__file__).resolve().parents[2]
    content = (root / "Dockerfile").read_text(encoding="utf-8")
    # supervisord is launched directly (as root), not behind a gosu priv-drop.
    assert "exec /usr/bin/supervisord" in content
    assert "gosu deeptutor /usr/bin/supervisord" not in content
    # Every supervisord program drops to the unprivileged deeptutor user, so the
    # backend/frontend processes never run as root. Each config heredoc closes
    # with ``EOF``; slice to it so a program's section is bounded correctly.
    program_blocks = content.split("[program:")[1:]
    assert program_blocks, "expected supervisord [program:*] sections in the Dockerfile"
    for block in program_blocks:
        name = block.splitlines()[0].rstrip("]")
        section = block.split("EOF")[0]
        assert "user=deeptutor" in section, (
            f"supervisord program '{name}' must run as deeptutor (user=deeptutor)"
        )


def test_frontend_api_is_url_agnostic_passthrough() -> None:
    """web/lib/api.ts no longer carries a build-time API base or a placeholder
    token; apiUrl/wsUrl are pass-throughs and the Next.js middleware
    (web/proxy.ts) performs the forwarding at request time."""
    root = Path(__file__).resolve().parents[2]
    api_ts = (root / "web" / "lib" / "api.ts").read_text(encoding="utf-8")
    assert "NEXT_PUBLIC_API_BASE_PLACEHOLDER" not in api_ts
    assert "process.env.NEXT_PUBLIC_API_BASE" not in api_ts
    proxy_ts = (root / "web" / "proxy.ts").read_text(encoding="utf-8")
    assert "DEEPTUTOR_API_BASE_URL" in proxy_ts
    assert "NextResponse.rewrite" in proxy_ts
