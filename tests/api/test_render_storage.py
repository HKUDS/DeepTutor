from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from urllib.parse import urlsplit

from fastapi.testclient import TestClient
import pytest

from tests.api.test_workspace_router import workspace_api as workspace_api


@pytest.fixture
def render_api(workspace_api, monkeypatch: pytest.MonkeyPatch):
    from deeptutor.api.routers import render_storage
    from deeptutor.services import session

    client, service = workspace_api
    monkeypatch.setattr(render_storage, "get_content_workspace_service", lambda: service)
    store = SimpleNamespace(list_nonterminal_turns=AsyncMock(return_value=[]))
    monkeypatch.setattr(session, "get_session_store", lambda: store)
    binding = service.current_binding(ensure_output=True)
    turn = binding.root / "outputs/math_animator/session/turn"
    artifact = turn / "artifacts/movie.mp4"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"final video")
    source = turn / "source/scene.py"
    source.parent.mkdir()
    source.write_text("print('source')")
    cache = turn / "media/videos/partial_movie_files/segment.mp4"
    cache.parent.mkdir(parents=True)
    cache.write_bytes(b"temporary render")
    item = service.publish(binding, [{"path": service.relative_path(binding, artifact)}])[0]
    item = replace(item, url=urlsplit(item.url).path)
    return client, service, item, turn, store


def test_preview_cleanup_and_playback_preserve_final_files(render_api):
    client, service, item, turn, _ = render_api
    preview = client.get(item.url + "/render-storage")
    assert preview.status_code == 200, preview.json()
    assert preview.json()["file_path"] == str(turn / "artifacts/movie.mp4")
    assert preview.json()["cache_bytes"] == len(b"temporary render")
    assert preview.json()["cache_files"] == 1
    assert client.get(item.url + "/render-storage").json() == preview.json()
    cleaned = client.post(
        item.url + "/clean-render-cache", json={"fingerprint": preview.json()["fingerprint"]}
    )
    assert cleaned.status_code == 200
    assert cleaned.json()["freed_bytes"] == len(b"temporary render")
    assert not (turn / "media").exists()
    assert (turn / "source/scene.py").read_text() == "print('source')"
    assert (turn / "artifacts/movie.mp4").read_bytes() == b"final video"
    assert client.get(item.url).content == b"final video"
    assert client.get(item.url + "/render-storage").json()["cache_files"] == 0


def test_cleanup_refuses_changed_preview(render_api):
    client, _, item, turn, _ = render_api
    preview = client.get(item.url + "/render-storage").json()
    (turn / "media/new.txt").write_text("another render")
    response = client.post(
        item.url + "/clean-render-cache", json={"fingerprint": preview["fingerprint"]}
    )
    assert response.status_code == 409
    assert (turn / "media/new.txt").exists()


def test_cleanup_refuses_active_turns(render_api):
    client, _, item, turn, store = render_api
    preview = client.get(item.url + "/render-storage").json()
    store.list_nonterminal_turns.return_value = [{"id": "running"}]
    assert (
        client.post(
            item.url + "/clean-render-cache", json={"fingerprint": preview["fingerprint"]}
        ).status_code
        == 409
    )
    assert (turn / "media").exists()


def test_cleanup_excludes_other_writers(render_api):
    from deeptutor.services.workspace.activity import data_activity

    client, _, item, turn, _ = render_api
    preview = client.get(item.url + "/render-storage").json()
    with data_activity():
        response = client.post(
            item.url + "/clean-render-cache", json={"fingerprint": preview["fingerprint"]}
        )
    assert response.status_code == 409
    assert (turn / "media").exists()


@pytest.mark.parametrize("position", ["media", "child", "artifact-parent"])
def test_symlinks_never_delete_the_target(render_api, tmp_path: Path, position: str):
    client, _, item, turn, _ = render_api
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "keep.txt"
    sentinel.write_text("keep")
    preview = client.get(item.url + "/render-storage").json()
    if position == "child":
        (turn / "media/link").symlink_to(outside, target_is_directory=True)
    elif position == "media":
        (turn / "media").rename(turn / "original-media")
        (turn / "media").symlink_to(outside, target_is_directory=True)
    else:
        (turn / "artifacts").rename(turn / "original-artifacts")
        (turn / "artifacts").symlink_to(turn / "original-artifacts", target_is_directory=True)
    assert client.get(item.url + "/render-storage").status_code == 404
    assert (
        client.post(
            item.url + "/clean-render-cache", json={"fingerprint": preview["fingerprint"]}
        ).status_code
        == 409
    )
    assert sentinel.read_text() == "keep"


def test_unrelated_and_missing_originals_are_not_cleanable(render_api):
    client, service, item, turn, _ = render_api
    (turn / "artifacts/movie.mp4").unlink()
    assert client.get(item.url + "/render-storage").status_code == 404
    binding = service.current_binding()
    (binding.root / "notes.md").write_text("private note")
    note = service.publish(binding, [{"path": "notes.md"}])[0]
    assert client.get(note.url + "/render-storage").status_code == 404
    assert client.get(item.url).content == b"final video"


def test_reveal_requires_local_origin_and_uses_validated_path(render_api, monkeypatch):
    from deeptutor.api.routers import render_storage

    client, _, item, turn, _ = render_api
    run = Mock()
    monkeypatch.setattr(render_storage.subprocess, "run", run)
    monkeypatch.setattr(render_storage.sys, "platform", "darwin")
    local = TestClient(client.app, base_url="http://localhost", client=("127.0.0.1", 1234))
    assert local.get(item.url + "/render-storage").json()["can_reveal"] is True
    assert (
        local.post(item.url + "/reveal", headers={"origin": "https://evil.example"}).status_code
        == 403
    )
    assert local.post(item.url + "/reveal").status_code == 403
    assert (
        client.post(item.url + "/reveal", headers={"origin": "http://localhost"}).status_code == 403
    )
    run.assert_not_called()
    assert (
        local.post(item.url + "/reveal", headers={"origin": "http://localhost:3782"}).status_code
        == 200
    )
    assert run.call_args.args[0] == ["open", "-R", str(turn / "artifacts/movie.mp4")]


@pytest.fixture
def chat_output_api(workspace_api):
    client, service = workspace_api
    binding = service.current_binding(ensure_output=True)
    relative = "outputs/chat/session/turn_one/exec/outputs/chat/session/turn_one/gap-lock.html"
    output = service.resolve(binding, relative, write=True)
    output.parent.mkdir(parents=True)
    output.write_text("<html>gap lock diagram</html>")
    item = service.publish(binding, [{"path": relative}])[0]
    item = replace(item, url=urlsplit(item.url).path)
    return client, service, item, output


def test_chat_output_file_actions_preserve_the_attachment(chat_output_api):
    client, _, item, output = chat_output_api
    response = client.get(item.url + "/file-storage")
    assert response.status_code == 200, response.json()
    preview = response.json()
    assert preview["file_path"] == str(output)
    assert preview["file_bytes"] == output.stat().st_size
    deleted = client.post(
        item.url + "/remove-generated-output",
        json={"fingerprint": preview["fingerprint"]},
    )
    assert deleted.status_code == 200, deleted.json()
    assert not output.exists()
    assert client.get(item.url).content == b"<html>gap lock diagram</html>"


def test_direct_chat_output_file_actions_preserve_the_attachment(chat_output_api):
    client, service, _, _ = chat_output_api
    binding = service.current_binding()
    relative = "outputs/chat/session/turn_run-123/showme-next-key-lock-range.html"
    output = service.resolve(binding, relative, write=True)
    output.parent.mkdir(parents=True)
    output.write_text("<html>next-key-lock</html>")
    item = service.publish(binding, [{"path": relative}])[0]
    item = replace(item, url=urlsplit(item.url).path)
    preview_response = client.get(item.url + "/file-storage")
    assert preview_response.status_code == 200, preview_response.json()
    preview = preview_response.json()
    assert preview["file_path"] == str(output)
    deleted = client.post(
        item.url + "/remove-generated-output",
        json={"fingerprint": preview["fingerprint"]},
    )
    assert deleted.status_code == 200, deleted.json()
    assert not output.exists()
    assert client.get(item.url).content == b"<html>next-key-lock</html>"


def test_exec_turn_output_file_actions_preserve_the_attachment(chat_output_api):
    client, service, _, _ = chat_output_api
    binding = service.current_binding()
    relative = "outputs/chat/session/turn_run-456/exec/lp-replay-simulator.html"
    output = service.resolve(binding, relative, write=True)
    output.parent.mkdir(parents=True)
    output.write_text("<html>LP replay</html>")
    item = service.publish(binding, [{"path": relative}])[0]
    item = replace(item, url=urlsplit(item.url).path)
    response = client.get(item.url + "/file-storage")
    assert response.status_code == 200, response.json()
    assert response.json()["file_path"] == str(output)


def test_chat_output_removal_refuses_changed_files(chat_output_api):
    client, _, item, output = chat_output_api
    preview = client.get(item.url + "/file-storage").json()
    output.write_text("changed after preview")
    response = client.post(
        item.url + "/remove-generated-output",
        json={"fingerprint": preview["fingerprint"]},
    )
    assert response.status_code == 409
    assert output.exists()


def test_chat_output_removal_refuses_active_turns(chat_output_api, monkeypatch):
    from deeptutor.services import session

    client, _, item, output = chat_output_api
    store = SimpleNamespace(list_nonterminal_turns=AsyncMock(return_value=[{"id": "running"}]))
    monkeypatch.setattr(session, "get_session_store", lambda: store)
    preview = client.get(item.url + "/file-storage").json()
    response = client.post(
        item.url + "/remove-generated-output",
        json={"fingerprint": preview["fingerprint"]},
    )
    assert response.status_code == 409
    assert output.exists()


def test_chat_output_actions_reject_other_paths(chat_output_api):
    client, service, item, output = chat_output_api
    binding = service.current_binding()
    other = binding.root / "notes.md"
    other.write_text("private")
    unrelated = service.publish(binding, [{"path": "notes.md"}])[0]
    assert client.get(unrelated.url + "/file-storage").status_code == 404
    assert client.post(item.url + "/reveal-generated-output").status_code == 403
    assert output.exists()


def test_chat_output_reveal_requires_local_browser(chat_output_api, monkeypatch):
    from deeptutor.api.routers import render_storage

    client, _, item, _ = chat_output_api
    run = Mock()
    monkeypatch.setattr(render_storage.subprocess, "run", run)
    monkeypatch.setattr(render_storage.sys, "platform", "darwin")
    local = TestClient(client.app, base_url="http://localhost", client=("127.0.0.1", 1234))
    assert local.post(item.url + "/reveal-generated-output").status_code == 403
    response = local.post(
        item.url + "/reveal-generated-output", headers={"origin": "http://localhost:3782"}
    )
    assert response.status_code == 200
    assert run.call_args.args[0][:2] == ["open", "-R"]
    assert run.call_args.args[0][-1].endswith("/gap-lock.html")


def test_chat_output_actions_reject_symlinked_paths(chat_output_api, tmp_path: Path):
    client, _, item, output = chat_output_api
    external = tmp_path / "outside.html"
    external.write_text("leave intact")
    output.unlink()
    output.symlink_to(external)
    assert client.get(item.url + "/file-storage").status_code == 404
    assert external.read_text() == "leave intact"
