"""Expose Windows' registered Open with actions to the desktop main process."""

from __future__ import annotations

import argparse
from collections.abc import Generator
from contextlib import closing, contextmanager
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import sys
from uuid import UUID


class GUID(ctypes.Structure):
    _fields_ = [
        ("data1", wintypes.DWORD),
        ("data2", wintypes.WORD),
        ("data3", wintypes.WORD),
        ("data4", ctypes.c_ubyte * 8),
    ]

    @classmethod
    def parse(cls, value: str) -> GUID:
        return cls.from_buffer_copy(UUID(value).bytes_le)


class OpenAsInfo(ctypes.Structure):
    _fields_ = [
        ("file", wintypes.LPCWSTR),
        ("file_type", wintypes.LPCWSTR),
        ("flags", wintypes.DWORD),
    ]


# Interface method indices from ShObjIdl_core.h, including IUnknown.
_RELEASE = 2
_NEXT = 3
_GET_NAME = 3
_GET_UI_NAME = 4
_INVOKE = 8
_BIND_TO_HANDLER = 3

_S_OK = 0
_S_FALSE = 1
_ASSOC_FILTER_RECOMMENDED = 1
_OAIF_EXEC = 4
_COINIT_APARTMENTTHREADED = 2
_NO_ASSOCIATION = 0x80070483
_CANCELLED = 0x800704C7

# ctypes exposes the library loader only on Windows.
_WINDOWS_DLLS = getattr(ctypes, "windll", None)
_HRESULT = ctypes.c_long
_VOID_P = ctypes.c_void_p
_OUT_PTR = ctypes.POINTER(_VOID_P)
_REF_GUID = ctypes.POINTER(GUID)
_IID_SHELL_ITEM = GUID.parse("43826d1e-e718-42ee-bc55-a1e261c37bfe")
_BHID_DATA_OBJECT = GUID.parse("b8c0bd9f-ed24-455c-83e6-d5390c4fe8c4")
_IID_DATA_OBJECT = GUID.parse("0000010e-0000-0000-c000-000000000046")


def _com_call(pointer, index, result_type, argument_types, *arguments):
    vtable = ctypes.cast(pointer, ctypes.POINTER(_OUT_PTR)).contents
    method = ctypes.WINFUNCTYPE(result_type, _VOID_P, *argument_types)(vtable[index])
    return method(pointer, *arguments)


def _check(result: int, name: str) -> None:
    if result < 0:
        raise OSError(f"{name} failed (HRESULT 0x{result & 0xFFFFFFFF:08X}).")


@contextmanager
def _com_out_pointer():
    pointer = _VOID_P()
    try:
        yield pointer
    finally:
        if pointer:
            _com_call(pointer, _RELEASE, wintypes.ULONG, ())


def _handler_string(handler, method: int) -> str | None:
    # The Shell allocates the returned string. Keep its address so it can be freed.
    address = _VOID_P()
    try:
        if _com_call(handler, method, _HRESULT, (_OUT_PTR,), ctypes.byref(address)) != _S_OK:
            return None
        return ctypes.wstring_at(address) if address else None
    finally:
        if address:
            _WINDOWS_DLLS.ole32.CoTaskMemFree(address)


def _handlers(extension: str) -> Generator[ctypes.c_void_p, None, None]:
    if not extension:
        return
    shell = _WINDOWS_DLLS.shell32
    enumerate_handlers = shell.SHAssocEnumHandlers
    enumerate_handlers.argtypes = (wintypes.LPCWSTR, ctypes.c_int, _OUT_PTR)
    enumerate_handlers.restype = _HRESULT
    with _com_out_pointer() as enumerator:
        result = enumerate_handlers(extension, _ASSOC_FILTER_RECOMMENDED, ctypes.byref(enumerator))
        if result & 0xFFFFFFFF == _NO_ASSOCIATION:
            return
        _check(result, "SHAssocEnumHandlers")
        if not enumerator:
            return
        while True:
            with _com_out_pointer() as handler:
                result = _com_call(
                    enumerator,
                    _NEXT,
                    _HRESULT,
                    (wintypes.ULONG, _OUT_PTR, _VOID_P),
                    1,
                    ctypes.byref(handler),
                    None,
                )
                if result == _S_FALSE:
                    return
                _check(result, "IEnumAssocHandlers.Next")
                if not handler:
                    return
                yield handler


def _list_handlers(extension: str) -> list[dict[str, str]]:
    seen: set[str] = set()
    candidates = []
    with closing(_handlers(extension)) as handlers:
        for handler in handlers:
            identifier = _handler_string(handler, _GET_NAME)
            label = _handler_string(handler, _GET_UI_NAME)
            if not identifier or not label or identifier.casefold() in seen:
                continue
            candidates.append({"id": identifier, "label": label})
            seen.add(identifier.casefold())
    return candidates


@contextmanager
def _file_data_object(file: Path):
    create_shell_item = _WINDOWS_DLLS.shell32.SHCreateItemFromParsingName
    create_shell_item.argtypes = (wintypes.LPCWSTR, _VOID_P, _REF_GUID, _OUT_PTR)
    create_shell_item.restype = _HRESULT
    with _com_out_pointer() as item, _com_out_pointer() as data_object:
        _check(
            create_shell_item(str(file), None, ctypes.byref(_IID_SHELL_ITEM), ctypes.byref(item)),
            "SHCreateItemFromParsingName",
        )
        _check(
            _com_call(
                item,
                _BIND_TO_HANDLER,
                _HRESULT,
                (_VOID_P, _REF_GUID, _REF_GUID, _OUT_PTR),
                None,
                ctypes.byref(_BHID_DATA_OBJECT),
                ctypes.byref(_IID_DATA_OBJECT),
                ctypes.byref(data_object),
            ),
            "IShellItem.BindToHandler",
        )
        yield data_object


def _open(file: Path, selected_id: str) -> None:
    with closing(_handlers(file.suffix)) as handlers:
        for handler in handlers:
            identifier = _handler_string(handler, _GET_NAME)
            if identifier and identifier.casefold() == selected_id.casefold():
                with _file_data_object(file) as data_object:
                    _check(
                        _com_call(handler, _INVOKE, _HRESULT, (_VOID_P,), data_object),
                        "IAssocHandler.Invoke",
                    )
                return
    raise ValueError("The selected application is no longer registered for this file type.")


def _picker(file: Path) -> None:
    open_with = _WINDOWS_DLLS.shell32.SHOpenWithDialog
    open_with.argtypes = (wintypes.HWND, ctypes.POINTER(OpenAsInfo))
    open_with.restype = _HRESULT
    options = OpenAsInfo(str(file), None, _OAIF_EXEC)
    result = open_with(None, ctypes.byref(options))
    if result & 0xFFFFFFFF != _CANCELLED:
        _check(result, "SHOpenWithDialog")


def _local_file(raw: str) -> Path:
    def valid_path(file: Path) -> bool:
        return (
            file.is_absolute()
            and not file.anchor.startswith("\\\\")
            and ":" not in str(file)[len(file.drive) :]
        )

    file = Path(raw)
    if not valid_path(file):
        raise ValueError("Open with requires an absolute local file path.")
    resolved = file.resolve(strict=True)
    if not valid_path(resolved) or not resolved.is_file():
        raise ValueError("Open with requires a regular local file.")
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("list", "open", "picker"))
    parser.add_argument("file")
    parser.add_argument("handler", nargs="?")
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("Open with is only supported on Windows.")
    if (args.action == "open") != bool(args.handler):
        parser.error("Pass one handler ID for the open action.")
    try:
        file = _local_file(args.file)
        ole32 = _WINDOWS_DLLS.ole32
        _check(ole32.CoInitializeEx(None, _COINIT_APARTMENTTHREADED), "CoInitializeEx")
        try:
            if args.action == "list":
                print(json.dumps(_list_handlers(file.suffix)))
            elif args.action == "open":
                _open(file, args.handler)
            else:
                _picker(file)
        finally:
            ole32.CoUninitialize()
    except (ValueError, OSError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
