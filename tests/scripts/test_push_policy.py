from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


def _load_push_policy_module():
    module_path = Path(__file__).resolve().parents[2] / "scripts" / "check_push_policy.py"
    module_name = "push_policy_under_test"
    sys.path.insert(0, str(module_path.parent))
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_parses_pre_push_input() -> None:
    module = _load_push_policy_module()

    specs = module.parse_push_specs(
        [
            "refs/heads/dev abc123 refs/heads/dev def456",
            "refs/heads/topic 012345 refs/heads/topic 6789ab",
        ]
    )

    assert [
        (spec.local_ref, spec.local_sha, spec.remote_ref, spec.remote_sha) for spec in specs
    ] == [
        ("refs/heads/dev", "abc123", "refs/heads/dev", "def456"),
        ("refs/heads/topic", "012345", "refs/heads/topic", "6789ab"),
    ]


def test_rejects_malformed_input() -> None:
    module = _load_push_policy_module()

    try:
        module.parse_push_specs(["malformed"])
    except ValueError as error:
        assert "Malformed pre-push input" in str(error)
    else:
        raise AssertionError("Expected malformed input to be rejected")


def test_recognizes_upstream_by_name_or_url() -> None:
    module = _load_push_policy_module()

    assert module.is_upstream_remote("origin", "https://github.com/example/example.git")
    assert module.is_upstream_remote("upstream", "https://github.com/HKUDS/DeepTutor.git")
    assert not module.is_upstream_remote(
        "myfork", "https://github.com/evan188199-tech/DeepTutor.git"
    )


def test_allows_fork_main_and_normal_upstream_push(monkeypatch) -> None:
    module = _load_push_policy_module()
    spec = module.PushSpec("refs/heads/main", "abc", "refs/heads/main", "def")
    monkeypatch.setattr(module, "pushed_paths", lambda _revision: [])

    assert not module.policy_errors([spec], upstream_remote=False, allow_upstream_main=False)
    assert not module.policy_errors([spec], upstream_remote=True, allow_upstream_main=True)


def test_rejects_upstream_main_and_generated_paths(monkeypatch) -> None:
    module = _load_push_policy_module()
    main_spec = module.PushSpec("refs/heads/main", "abc", "refs/heads/main", "def")
    dev_spec = module.PushSpec("refs/heads/dev", "abc", "refs/heads/dev", "def")
    monkeypatch.setattr(module, "pushed_paths", lambda _revision: ["web/.next-deeptutor/BUILD_ID"])

    main_errors = module.policy_errors([main_spec], upstream_remote=True, allow_upstream_main=False)
    dev_errors = module.policy_errors([dev_spec], upstream_remote=True, allow_upstream_main=False)

    assert "Direct pushes to upstream main are forbidden; use a pull request." in main_errors
    assert any("web/.next-deeptutor/BUILD_ID" in error for error in main_errors)
    assert any("web/.next-deeptutor/BUILD_ID" in error for error in dev_errors)
