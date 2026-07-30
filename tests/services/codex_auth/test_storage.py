from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import stat

import pytest

from deeptutor.services.codex_auth.contracts import CodexAuthError, CodexCredentials
from deeptutor.services.codex_auth.storage import CodexCredentialStore


def _credentials(token: str) -> CodexCredentials:
    return CodexCredentials(
        schema_version=1,
        access_token=f"access-{token}",
        refresh_token=f"refresh-{token}",
        id_token=f"id-{token}",
        account_id="account-123",
        expires_at=2_000_000_000,
        generation=0,
    )


def test_store_is_scoped_below_deeptutor_user_root(tmp_path: Path) -> None:
    store = CodexCredentialStore(tmp_path)

    assert store.root == tmp_path / "private" / "openai-codex"
    assert ".codex" not in str(store.root)


def test_store_uses_versioned_files_and_leaves_no_temporary_files(tmp_path: Path) -> None:
    store = CodexCredentialStore(tmp_path)
    committed = store.commit_credentials(_credentials("one"), expected_generation=0)
    store.save_catalog_cache({"models": []})

    assert committed.generation == 1
    assert {path.name for path in store.root.iterdir()} == {
        "auth.lock",
        "credentials.v1.json",
        "models-cache.v1.json",
        "state.v1.json",
    }
    assert not list(store.root.glob(".*.tmp"))
    assert not list(store.root.glob(".credentials.v1.json.*"))


def test_refresh_generation_cannot_overwrite_new_login(tmp_path: Path) -> None:
    store = CodexCredentialStore(tmp_path)
    first = store.commit_credentials(_credentials("old"), expected_generation=0)
    second = store.commit_credentials(_credentials("new"), expected_generation=first.generation)

    with pytest.raises(CodexAuthError, match="changed"):
        store.commit_credentials(
            _credentials("late-refresh"),
            expected_generation=first.generation,
        )

    loaded = store.load_credentials()
    assert loaded is not None
    assert loaded.access_token == second.access_token


def test_clear_increments_generation_and_prevents_credential_resurrection(tmp_path: Path) -> None:
    store = CodexCredentialStore(tmp_path)
    committed = store.commit_credentials(_credentials("old"), expected_generation=0)
    store.save_catalog_cache({"models": [{"slug": "old"}]})

    generation = store.clear_credentials(expected_generation=committed.generation)

    assert generation == 2
    assert store.current_generation() == 2
    assert store.load_credentials() is None
    assert store.load_catalog_cache() is None
    with pytest.raises(CodexAuthError, match="changed"):
        store.commit_credentials(_credentials("late"), expected_generation=1)


def test_two_threads_cannot_commit_the_same_generation(tmp_path: Path) -> None:
    store = CodexCredentialStore(tmp_path)
    first = store.commit_credentials(_credentials("first"), expected_generation=0)

    def commit(token: str) -> str:
        try:
            store.commit_credentials(_credentials(token), expected_generation=first.generation)
        except CodexAuthError as exc:
            return exc.code
        return "committed"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(commit, ("a", "b")))

    assert sorted(results) == ["committed", "generation_changed"]
    assert store.current_generation() == 2


def test_store_never_calls_path_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def fail_home(cls: type[Path]) -> Path:
        raise AssertionError("Path.home must not be used")

    monkeypatch.setattr(Path, "home", classmethod(fail_home))
    store = CodexCredentialStore(tmp_path)
    store.commit_credentials(_credentials("token"), expected_generation=0)
    store.clear_credentials(expected_generation=1)


def test_corrupt_credentials_raise_public_error(tmp_path: Path) -> None:
    store = CodexCredentialStore(tmp_path)
    store.root.mkdir(parents=True)
    store.credentials_path.write_text("{broken", encoding="utf-8")

    with pytest.raises(CodexAuthError) as exc_info:
        store.load_credentials()

    assert exc_info.value.code == "credential_corrupt"
    assert "{broken" not in str(exc_info.value)


def test_catalog_cache_round_trip(tmp_path: Path) -> None:
    store = CodexCredentialStore(tmp_path)

    store.save_catalog_cache({"etag": '"v1"', "models": [{"slug": "gpt-5.6-sol"}]})

    assert store.current_generation() == 0
    assert store.load_catalog_cache() == {
        "etag": '"v1"',
        "models": [{"slug": "gpt-5.6-sol"}],
    }


def test_existing_symlink_target_is_rejected(tmp_path: Path) -> None:
    store = CodexCredentialStore(tmp_path)
    store.root.mkdir(parents=True)
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    try:
        store.credentials_path.symlink_to(outside)
    except OSError:
        pytest.skip("Creating symlinks is unavailable on this platform")

    with pytest.raises(CodexAuthError) as exc_info:
        store.load_credentials()

    assert exc_info.value.code == "unsafe_storage_path"


def test_windows_reparse_point_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from deeptutor.services.codex_auth import storage

    store = CodexCredentialStore(tmp_path)
    store.root.mkdir(parents=True)
    store.credentials_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        storage,
        "_is_reparse_point",
        lambda path: path == store.credentials_path,
    )

    with pytest.raises(CodexAuthError) as exc_info:
        store.load_credentials()

    assert exc_info.value.code == "unsafe_storage_path"


@pytest.mark.skipif(
    os.name == "nt", reason="POSIX permission bits are not authoritative on Windows"
)
def test_private_files_are_owner_only_on_supported_platforms(tmp_path: Path) -> None:
    store = CodexCredentialStore(tmp_path)
    store.commit_credentials(_credentials("token"), expected_generation=0)

    mode = stat.S_IMODE(store.credentials_path.stat().st_mode)

    assert mode & (stat.S_IRWXG | stat.S_IRWXO) == 0
