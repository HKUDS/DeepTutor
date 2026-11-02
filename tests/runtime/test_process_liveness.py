"""Liveness probe behaviour using mocked OS and ctypes boundaries only."""

from __future__ import annotations

import ctypes
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from deeptutor.runtime import process as runtime_process

STILL_ACTIVE = 259
LARGE_HANDLE = 0x00001F2E3D4C5B6A
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

_FAKE_WINTYPES = SimpleNamespace(DWORD=ctypes.c_ulong, BOOL=ctypes.c_long)


def _patch_os(monkeypatch: pytest.MonkeyPatch, name: str) -> SimpleNamespace:
    os_mock = SimpleNamespace(name=name, kill=Mock())
    monkeypatch.setattr(runtime_process, "os", os_mock)
    return os_mock


def _install_fake_ctypes(
    monkeypatch: pytest.MonkeyPatch,
    kernel32: Mock | None,
    last_error: int = 0,
) -> None:
    monkeypatch.setitem(
        sys.modules,
        "ctypes",
        SimpleNamespace(
            WinDLL=None if kernel32 is None else Mock(return_value=kernel32),
            get_last_error=Mock(return_value=last_error),
            byref=lambda obj: obj,
            c_void_p=ctypes.c_void_p,
            POINTER=ctypes.POINTER,
            wintypes=_FAKE_WINTYPES,
        ),
    )


def _patch_windows(
    monkeypatch: pytest.MonkeyPatch,
    kernel32: Mock,
    last_error: int = 0,
) -> SimpleNamespace:
    os_mock = _patch_os(monkeypatch, "nt")
    _install_fake_ctypes(monkeypatch, kernel32, last_error)
    return os_mock


def _make_kernel32(
    *,
    handle: int = LARGE_HANDLE,
    exit_code: int = STILL_ACTIVE,
    query_ok: bool = True,
    query_exc: BaseException | None = None,
    close_result: bool = True,
    close_exc: BaseException | None = None,
) -> Mock:
    kernel32 = Mock(name="kernel32")

    def _get_exit_code(process_handle, exit_code_ref):
        if query_exc is not None:
            raise query_exc
        exit_code_ref.value = exit_code
        return query_ok

    kernel32.OpenProcess = Mock(return_value=handle)
    kernel32.GetExitCodeProcess = Mock(side_effect=_get_exit_code)
    if close_exc is None:
        kernel32.CloseHandle = Mock(side_effect=lambda _handle: close_result)
    else:
        kernel32.CloseHandle = Mock(side_effect=close_exc)
    return kernel32


def _assert_ffi_signatures(kernel32: Mock) -> None:
    assert kernel32.OpenProcess.argtypes == (
        _FAKE_WINTYPES.DWORD,
        _FAKE_WINTYPES.BOOL,
        _FAKE_WINTYPES.DWORD,
    )
    assert kernel32.OpenProcess.restype is ctypes.c_void_p
    assert kernel32.GetExitCodeProcess.argtypes == (
        ctypes.c_void_p,
        ctypes.POINTER(_FAKE_WINTYPES.DWORD),
    )
    assert kernel32.GetExitCodeProcess.restype is _FAKE_WINTYPES.BOOL
    assert kernel32.CloseHandle.argtypes == (ctypes.c_void_p,)
    assert kernel32.CloseHandle.restype is _FAKE_WINTYPES.BOOL


@pytest.mark.parametrize("exit_code,expected", [(STILL_ACTIVE, "alive"), (0, "dead")])
def test_windows_valid_handle_reports_state_and_closes_once(
    monkeypatch: pytest.MonkeyPatch, exit_code: int, expected: str
) -> None:
    kernel32 = _make_kernel32(exit_code=exit_code)
    os_mock = _patch_windows(monkeypatch, kernel32)

    assert runtime_process.probe_process_liveness(1234) == expected

    _assert_ffi_signatures(kernel32)
    kernel32.OpenProcess.assert_called_once_with(PROCESS_QUERY_LIMITED_INFORMATION, False, 1234)
    query_args = kernel32.GetExitCodeProcess.call_args.args
    assert query_args[0] == LARGE_HANDLE
    assert isinstance(query_args[1], _FAKE_WINTYPES.DWORD)
    assert kernel32.CloseHandle.call_count == 1
    kernel32.CloseHandle.assert_called_once_with(LARGE_HANDLE)
    os_mock.kill.assert_not_called()


@pytest.mark.parametrize(
    "last_error,expected",
    [(87, "dead"), (5, "unknown"), (0, "unknown"), (6, "unknown")],
)
def test_windows_open_process_null_classifies_by_last_error(
    monkeypatch: pytest.MonkeyPatch, last_error: int, expected: str
) -> None:
    kernel32 = _make_kernel32(handle=0)
    os_mock = _patch_windows(monkeypatch, kernel32, last_error=last_error)

    assert runtime_process.probe_process_liveness(4321) == expected

    kernel32.GetExitCodeProcess.assert_not_called()
    kernel32.CloseHandle.assert_not_called()
    os_mock.kill.assert_not_called()


@pytest.mark.parametrize(
    "query_ok,query_exc",
    [(False, None), (True, OSError("query failed"))],
)
def test_windows_query_failure_returns_unknown_and_still_closes(
    monkeypatch: pytest.MonkeyPatch, query_ok: bool, query_exc: BaseException | None
) -> None:
    kernel32 = _make_kernel32(query_ok=query_ok, query_exc=query_exc)
    os_mock = _patch_windows(monkeypatch, kernel32)

    assert runtime_process.probe_process_liveness(999) == "unknown"

    kernel32.CloseHandle.assert_called_once_with(LARGE_HANDLE)
    os_mock.kill.assert_not_called()


@pytest.mark.parametrize(
    "close_result,close_exc",
    [(False, None), (True, OSError("close failed"))],
)
def test_windows_close_failure_returns_unknown_even_when_dead(
    monkeypatch: pytest.MonkeyPatch, close_result: bool, close_exc: BaseException | None
) -> None:
    kernel32 = _make_kernel32(exit_code=0, close_result=close_result, close_exc=close_exc)
    os_mock = _patch_windows(monkeypatch, kernel32)

    assert runtime_process.probe_process_liveness(999) == "unknown"

    kernel32.CloseHandle.assert_called_once_with(LARGE_HANDLE)
    os_mock.kill.assert_not_called()


def test_windows_without_windll_returns_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    os_mock = _patch_os(monkeypatch, "nt")
    _install_fake_ctypes(monkeypatch, kernel32=None)

    assert runtime_process.probe_process_liveness(777) == "unknown"
    os_mock.kill.assert_not_called()


def test_windows_ctypes_import_error_returns_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    os_mock = _patch_os(monkeypatch, "nt")
    monkeypatch.setitem(sys.modules, "ctypes", None)

    assert runtime_process.probe_process_liveness(777) == "unknown"
    os_mock.kill.assert_not_called()


@pytest.mark.parametrize("pid", [None, 0, -1, True, 1.5, "1", 2**32])
def test_windows_invalid_pid_returns_unknown_without_system_calls(
    monkeypatch: pytest.MonkeyPatch, pid: object
) -> None:
    os_mock = _patch_os(monkeypatch, "nt")
    kernel32 = _make_kernel32()
    _install_fake_ctypes(monkeypatch, kernel32)

    assert runtime_process.probe_process_liveness(pid) == "unknown"

    os_mock.kill.assert_not_called()
    kernel32.OpenProcess.assert_not_called()
    kernel32.GetExitCodeProcess.assert_not_called()
    kernel32.CloseHandle.assert_not_called()


@pytest.mark.parametrize(
    "kill_effect,expected",
    [
        (None, "alive"),
        (ProcessLookupError(), "dead"),
        (PermissionError(), "unknown"),
        (OSError("probe failed"), "unknown"),
        (OverflowError("pid too large"), "unknown"),
    ],
)
def test_posix_kill_outcomes(
    monkeypatch: pytest.MonkeyPatch, kill_effect: BaseException | None, expected: str
) -> None:
    os_mock = _patch_os(monkeypatch, "posix")
    if kill_effect is not None:
        os_mock.kill.side_effect = kill_effect

    assert runtime_process.probe_process_liveness(4242) == expected
    os_mock.kill.assert_called_once_with(4242, 0)


def test_legacy_is_process_alive_invalid_pids() -> None:
    assert runtime_process.is_process_alive(None) is False
    assert runtime_process.is_process_alive(0) is False
    assert runtime_process.is_process_alive(-5) is False


@pytest.mark.parametrize("exit_code,expected", [(STILL_ACTIVE, True), (0, False)])
def test_legacy_is_process_alive_windows_dispatcher(
    monkeypatch: pytest.MonkeyPatch, exit_code: int, expected: bool
) -> None:
    kernel32 = _make_kernel32(exit_code=exit_code)
    os_mock = _patch_windows(monkeypatch, kernel32)

    assert runtime_process.is_process_alive(31337) is expected

    kernel32.CloseHandle.assert_called_once_with(LARGE_HANDLE)
    os_mock.kill.assert_not_called()
