"""Local MinerU failure classification (issue #1612, outcome 4).

Covers the reason codes returned by
:func:`deeptutor.services.parsing.engines.mineru.local.parse_document_with_mineru_result`,
how ``backend`` maps them to distinct :class:`MinerUError` messages, and the
unchanged bool contract of the legacy helpers.
"""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from deeptutor.services.parsing.engines.mineru import backend as mineru_backend
from deeptutor.services.parsing.engines.mineru import local as mineru_local
from deeptutor.services.parsing.engines.mineru.config import MinerUConfig, MinerUError
from deeptutor.services.parsing.engines.mineru.local import (
    LocalParseReason,
    LocalParseResult,
    parse_document_with_mineru,
    parse_document_with_mineru_result,
)

REASONS = list(LocalParseReason)


@pytest.fixture()
def pdf(tmp_path: Path) -> Path:
    source = tmp_path / "exam.pdf"
    source.write_bytes(b"%PDF-1.4")
    return source


def _install_fake_popen(
    monkeypatch: pytest.MonkeyPatch,
    *,
    returncode: int = 0,
    lines: tuple[str, ...] = (),
    artifacts: tuple[str, ...] = (),
) -> None:
    """Patch the subprocess factory so the local CLI is simulated in-process."""

    class FakeProcess:
        def __init__(self, cmd, **_kwargs) -> None:  # noqa: ANN001
            target = Path(cmd[cmd.index("-o") + 1])
            for name in artifacts:
                path = target / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("# parsed", encoding="utf-8")
            self.stdout = iter(lines)

        def wait(self) -> int:
            return returncode

    monkeypatch.setattr(mineru_local.subprocess, "Popen", FakeProcess)


# ---------------------------------------------------------------------------
# parse_document_with_mineru_result — reason codes
# ---------------------------------------------------------------------------


def test_cli_missing_reports_reason(
    pdf: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mineru_local, "check_mineru_installed", lambda: None)

    result = parse_document_with_mineru_result(pdf, tmp_path / "out")

    assert result.ok is False
    assert result.reason is LocalParseReason.CLI_MISSING
    assert result.detail


def test_input_missing_reports_reason(pdf: Path, tmp_path: Path) -> None:
    missing = tmp_path / "gone.pdf"

    result = parse_document_with_mineru_result(missing, tmp_path / "out", cli_command="mineru")

    assert result.reason is LocalParseReason.INPUT_MISSING
    assert result.detail == str(missing.resolve())


def test_unsupported_input_reports_reason(tmp_path: Path) -> None:
    source = tmp_path / "notes.xyz"
    source.write_text("x", encoding="utf-8")

    result = parse_document_with_mineru_result(source, tmp_path / "out", cli_command="mineru")

    assert result.reason is LocalParseReason.UNSUPPORTED_INPUT
    assert result.detail == ".xyz"


def test_legacy_cli_input_reports_reason(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "lesson.docx"
    source.write_bytes(b"office")
    monkeypatch.setattr(
        mineru_local.subprocess,
        "Popen",
        lambda *_args, **_kwargs: pytest.fail("legacy CLI must not be invoked"),
    )

    result = parse_document_with_mineru_result(source, tmp_path / "out", cli_command="magic-pdf")

    assert result.reason is LocalParseReason.LEGACY_CLI_INPUT


def test_nonzero_exit_keeps_bounded_stderr_tail(
    pdf: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_popen(
        monkeypatch,
        returncode=7,
        lines=("first problem", "second problem"),
    )

    result = parse_document_with_mineru_result(pdf, tmp_path / "out", cli_command="mineru")

    assert result.reason is LocalParseReason.NONZERO_EXIT
    assert "exit code 7" in result.detail
    assert "first problem" in result.detail
    assert "second problem" in result.detail


def test_no_artifacts_reports_reason(
    pdf: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_popen(monkeypatch, returncode=0, artifacts=())

    result = parse_document_with_mineru_result(pdf, tmp_path / "out", cli_command="mineru")

    assert result.reason is LocalParseReason.NO_ARTIFACTS


def test_internal_exception_reports_reason(
    pdf: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_args, **_kwargs):  # noqa: ANN002, ANN003
        raise subprocess.TimeoutExpired(cmd="mineru", timeout=1)

    monkeypatch.setattr(mineru_local.subprocess, "Popen", boom)

    result = parse_document_with_mineru_result(pdf, tmp_path / "out", cli_command="mineru")

    assert result.reason is LocalParseReason.EXCEPTION
    assert "TimeoutExpired" in result.detail


def test_success_reports_ok(pdf: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_popen(monkeypatch, artifacts=("exam.md",))

    result = parse_document_with_mineru_result(pdf, tmp_path / "out", cli_command="mineru")

    assert result.ok is True
    assert result.reason is None
    assert (tmp_path / "out" / "exam" / "exam.md").exists()


def test_failure_detail_is_bounded() -> None:
    result = LocalParseResult.failure(LocalParseReason.EXCEPTION, "x" * 1000)

    assert len(result.detail) <= mineru_local._FAILURE_DETAIL_MAX_CHARS + 1


# ---------------------------------------------------------------------------
# backend mapping and legacy contract
# ---------------------------------------------------------------------------


def test_backend_maps_every_reason_to_a_distinct_error(
    pdf: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exe = tmp_path / "mineru"
    exe.write_text("#!/bin/sh\n", encoding="utf-8")
    exe.chmod(0o755)
    config = MinerUConfig(mode="local", local_cli_path=str(exe))
    messages: dict[str, str] = {}

    for reason in REASONS:
        monkeypatch.setattr(
            mineru_backend,
            "parse_document_with_mineru_result",
            lambda *_args, _reason=reason, **_kwargs: LocalParseResult(
                ok=False, reason=_reason, detail="excerpt-here"
            ),
        )
        with pytest.raises(MinerUError) as exc:
            mineru_backend.parse_document_to_workdir(pdf, tmp_path / f"out-{reason}", config=config)
        assert exc.value.code == str(reason)
        assert exc.value.detail == "excerpt-here"
        messages[str(reason)] = str(exc.value)

    assert len(set(messages.values())) == len(messages)
    install_hits = [
        key for key, message in messages.items() if "Ensure MinerU is installed" in message
    ]
    assert install_hits == ["cli_missing"]


def test_backend_runtime_failure_does_not_claim_missing_install(
    pdf: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        mineru_backend,
        "parse_document_with_mineru_result",
        lambda *_args, **_kwargs: LocalParseResult(
            ok=False, reason=LocalParseReason.NONZERO_EXIT, detail="exit code 9: broken"
        ),
    )

    with pytest.raises(MinerUError) as exc:
        mineru_backend.parse_document_to_workdir(
            pdf, tmp_path / "out", config=MinerUConfig(mode="local")
        )

    assert exc.value.code == "nonzero_exit"
    assert "Ensure MinerU is installed" not in str(exc.value)
    assert "exit code 9" in str(exc.value)


def test_legacy_bool_helpers_keep_their_contract(
    pdf: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mineru_local, "check_mineru_installed", lambda: None)
    assert parse_document_with_mineru(pdf, tmp_path / "out") is False

    source = tmp_path / "lesson.docx"
    source.write_bytes(b"office")
    assert mineru_local.parse_pdf_with_mineru(str(source)) is False


def test_error_without_classification_keeps_old_shape() -> None:
    error = MinerUError("boom")

    assert error.code is None
    assert error.detail == ""
    assert str(error) == "boom"
