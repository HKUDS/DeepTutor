"""
Pure-python helpers to read and write Windows .lnk (MS-SHLLINK) files.

Why exist: the shortcut is built byte-for-byte instead of through
`WScript.Shell`, so it also works in locked-down environments where COM
instantiation is unavailable. Only the subset a launcher shortcut needs is
implemented:

  header + LinkTargetIDList + LinkInfo(+VolumeID) + StringData
  (NAME / RELATIVE_PATH / WORKING_DIR / ARGUMENTS / ICON_LOCATION) + ExtraData.

The LinkTargetIDList is mandatory: a file carrying only LinkInfo is rejected by
ShellExecute with ERROR_NO_ASSOCIATION. The item list itself comes from
`shell32.ILCreateFromPathW` (see `_pidl_bytes`) because shell items embed
version-specific metadata that is impractical to synthesise.
"""

from __future__ import annotations

import os
import struct

# GUID 00021401-0000-0000-C000-000000000046 stored little-endian.
LINK_CLSID = bytes.fromhex("0114020000000000c000000000000046")
HEADER_SIZE = 0x4C

F_HAS_LINK_TARGET_IDLIST = 0x00000001
F_HAS_LINK_INFO = 0x00000002
F_HAS_NAME = 0x00000004
F_HAS_RELATIVE_PATH = 0x00000008
F_HAS_WORKING_DIR = 0x00000010
F_HAS_ARGUMENTS = 0x00000020
F_HAS_ICON_LOCATION = 0x00000040
F_IS_UNICODE = 0x00000080
F_FORCE_NO_LINK_INFO = 0x00000100
F_HAS_EXP_STRING = 0x00000200
F_RUN_IN_SEPARATE_PROCESS = 0x00000400
F_HAS_EXP_ICON = 0x00004000
F_ENABLE_TARGET_METADATA = 0x00080000
F_DISABLE_KNOWN_FOLDER_TRACKING = 0x00200000

FILE_ATTRIBUTE_NORMAL = 0x00000080
FILE_ATTRIBUTE_ARCHIVE = 0x00000020
FILE_ATTRIBUTE_DIRECTORY = 0x00000010

SHOW_NORMAL = 1
SHOW_MAXIMIZED = 3
SHOW_MINNOACTIVE = 7

TERMINAL_BLOCK = 0x00000000
BLOCK_ENVIRONMENT = 0xA0000001
BLOCK_PROPERTY_STORE = 0xA0000009


# --------------------------------------------------------------------------- #
# writer
# --------------------------------------------------------------------------- #


def _u16(value: int) -> bytes:
    return struct.pack("<I", value)[:2]


def _mbcs(text: str) -> bytes:
    """ANSI/CP_ACP encoding used by the non-unicode slots of a .lnk."""
    try:
        import codecs

        return codecs.encode(text, "mbcs")
    except Exception:  # pragma: no cover - non Windows / bad codepage
        return text.encode("utf-8", "replace")


def _utf16_z(text: str) -> bytes:
    return text.encode("utf-16-le") + b"\x00\x00"


def _string_data(items) -> bytes:
    """StringData section: for each slot a u16 char count (incl. NUL) + UTF-16LE."""
    out = bytearray()
    for text in items:
        if text is None:
            continue
        encoded = text.encode("utf-16-le") + b"\x00\x00"
        out += struct.pack("<H", len(encoded) // 2)
        out += encoded
    return bytes(out)


def _unicode_from(data: bytes, offset: int) -> str:
    """Read a UTF-16LE NUL-terminated string, staying 2-byte aligned."""
    pos = offset
    end = len(data) - 1
    while pos < end:
        if data[pos] == 0x00 and data[pos + 1] == 0x00:
            return data[offset:pos].decode("utf-16-le", "replace")
        pos += 2
    return data[offset:].decode("utf-16-le", "replace")


def _pidl_bytes(path: str) -> bytes:
    """LinkTargetIDList payload for `path`.

    Windows refuses a .lnk whose LinkTargetIDList is missing (ShellExecute
    reports ERROR_NO_ASSOCIATION), so the item list has to be real. Build it
    with `ILCreateFromPathW` rather than by hand: shell items carry version
    specific metadata that is easy to get wrong.
    """
    import ctypes

    abs_path = os.path.abspath(path)
    try:
        shell32 = ctypes.windll.shell32
        shell32.ILCreateFromPathW.argtypes = [ctypes.c_wchar_p]
        shell32.ILCreateFromPathW.restype = ctypes.c_void_p
        shell32.ILGetSize.argtypes = [ctypes.c_void_p]
        shell32.ILGetSize.restype = ctypes.c_uint
        ptr = shell32.ILCreateFromPathW(abs_path)
        if not ptr:
            return b""
        try:
            size = shell32.ILGetSize(ctypes.c_void_p(ptr))
            raw = ctypes.string_at(ptr, size)
        finally:
            ctypes.windll.ole32.CoTaskMemFree(ctypes.c_void_p(ptr))
        # drop the 2-byte ITEMIDLIST_NULL terminator, the lnk adds its own
        return raw[:-2] if raw.endswith(b"\x00\x00") else raw
    except Exception:  # pragma: no cover - defensive
        return b""


def build_lnk(
    *,
    target: str,
    arguments: str = "",
    working_dir: str = "",
    description: str = "",
    icon_location: str = "",
    icon_index: int = 0,
    show_command: int = SHOW_NORMAL,
    relative_path: str | None = None,
    env_vars: dict | None = None,
) -> bytes:
    """Return the bytes of a .lnk pointing at `target`."""
    flags = F_HAS_LINK_INFO | F_IS_UNICODE | F_HAS_LINK_TARGET_IDLIST | F_DISABLE_KNOWN_FOLDER_TRACKING
    if arguments:
        flags |= F_HAS_ARGUMENTS
    if working_dir:
        flags |= F_HAS_WORKING_DIR
    if description:
        flags |= F_HAS_NAME
    if icon_location:
        flags |= F_HAS_ICON_LOCATION
    if relative_path:
        flags |= F_HAS_RELATIVE_PATH

    header = bytearray()
    header += struct.pack("<I", HEADER_SIZE)
    header += LINK_CLSID
    header += struct.pack("<I", flags)
    header += struct.pack("<I", FILE_ATTRIBUTE_ARCHIVE)
    header += b"\x00" * 24  # three FILETIME fields
    header += struct.pack("<I", 0)  # TargetSize, unused
    header += struct.pack("<i", icon_index)
    header += struct.pack("<I", show_command)
    header += struct.pack("<H", 0)  # HotKey
    header += struct.pack("<H", 0)  # Reserved1
    header += struct.pack("<I", 0)  # Reserved2
    header += struct.pack("<I", 0)  # Reserved3

    id_list = _pidl_bytes(target)
    id_list_section = struct.pack("<H", len(id_list) + 2) + id_list + b"\x00\x00"
    link_info = _build_link_info(target)

    strings = _string_data(
        [
            description or None,  # NAME_STRING
            relative_path or None,  # RELATIVE_PATH
            working_dir or None,  # WORKING_DIR  (order per spec: name, rel, workdir, args, icon)
            arguments or None,  # COMMAND_LINE_ARGUMENTS
            icon_location or None,  # ICON_LOCATION
        ]
    )

    extra = bytearray()
    if env_vars:
        payload = b"".join(_utf16_z(k) + _utf16_z(v) for k, v in env_vars.items())
        # Unicode form: 0x00000001 marker followed by ANSI + unicode expansions is
        # not needed here — Windows also accepts the plain unicode block.
        body = b"\x00\x01\x00\x00" + payload  # unicode marker + entries
        extra += struct.pack("<II", len(body) + 8, BLOCK_ENVIRONMENT) + body
    extra += struct.pack("<II", 8, TERMINAL_BLOCK)

    return bytes(header) + id_list_section + link_info + strings + bytes(extra)


def _build_link_info(target: str) -> bytes:
    """LinkInfo with VolumeID + LocalBasePath (+ unicode variants)."""
    import os

    drive, _tail = os.path.splitdrive(os.path.abspath(target))
    local_base_path = os.path.abspath(target)
    serial, label = _volume_info(drive or "C:")

    # ---------------- VolumeID ----------------
    # Layout (MS-SHLLINK 2.3.2): VolumeIDSize, DriveType, DriveSerialNumber,
    # VolumeLabelOffset [, VolumeLabelOffsetUnicode], labels. When the optional
    # unicode slot exists the ANSI label moves from 0x10 to 0x14 — keeping it at
    # 0x10 overlaps the offset field and Windows rejects the whole link.
    # We only emit the ANSI form, so no unicode slot and no shift.
    label_ascii = _mbcs(label) if label else b""
    volume = bytearray()
    volume += b"\x00" * 4  # placeholder for VolumeIDSize
    volume += struct.pack("<I", 3)  # DriveType = DRIVE_FIXED
    volume += struct.pack("<I", serial)
    volume += struct.pack("<I", 0x10 if label_ascii else 0x14)
    if label_ascii:
        volume += label_ascii + b"\x00"
    struct.pack_into("<I", volume, 0, len(volume))

    local_ascii = _mbcs(local_base_path) + b"\x00"

    # offsets relative to LinkInfo start (header size 0x24 => unicode slots present)
    header_size = 0x24
    cursor = header_size
    volume_offset = cursor
    cursor += len(volume)
    local_base_offset = cursor
    cursor += len(local_ascii)
    local_base_unicode_offset = cursor
    local_utf16 = local_base_path.encode("utf-16-le") + b"\x00\x00"
    cursor += len(local_utf16)
    common_path_suffix_offset = cursor  # empty suffix (ascii + unicode NULs)
    suffix_utf16 = b"\x00\x00"
    cursor += 1 + len(suffix_utf16)
    total = cursor
    # keep everything DWORD aligned
    pad = (-total) % 4
    cursor += pad
    total = cursor

    info = bytearray()
    info += struct.pack("<I", total)
    info += struct.pack("<I", header_size)
    info += struct.pack("<I", 0x00000001)  # VolumeIDAndLocalBasePath
    info += struct.pack("<I", volume_offset)
    info += struct.pack("<I", local_base_offset)
    info += struct.pack("<I", 0)  # CommonNetworkRelativeLinkOffset (unused)
    info += struct.pack("<I", common_path_suffix_offset)
    info += struct.pack("<I", local_base_unicode_offset)
    info += struct.pack("<I", common_path_suffix_offset + 1)
    info += bytes(volume)
    info += local_ascii
    info += local_utf16
    info += b"\x00"
    info += suffix_utf16
    info += b"\x00" * pad
    return bytes(info)


def _volume_info(drive: str) -> tuple:
    """Return (serial, label) for `drive` (e.g. 'D:') using the Win32 API."""
    import ctypes

    root = drive + "\\" if drive else None
    serial = ctypes.c_uint()
    max_component = ctypes.c_uint()
    flags = ctypes.c_uint()
    buf = ctypes.create_unicode_buffer(261)
    fs_buf = ctypes.create_unicode_buffer(261)
    try:
        ok = ctypes.windll.kernel32.GetVolumeInformationW(
            ctypes.c_wchar_p(root),
            buf,
            ctypes.sizeof(buf),
            ctypes.byref(serial),
            ctypes.byref(max_component),
            ctypes.byref(flags),
            fs_buf,
            ctypes.sizeof(fs_buf),
        )
        if ok:
            return serial.value, buf.value
    except Exception:  # pragma: no cover - defensive
        pass
    return 0, ""


# --------------------------------------------------------------------------- #
# reader (enough to audit an existing shortcut)
# --------------------------------------------------------------------------- #


def parse_lnk(data: bytes) -> dict:
    """Extract the fields we care about from a .lnk byte blob."""
    out = {}
    (header_size,) = struct.unpack_from("<I", data, 0)
    clsid = data[4:20]
    (flags,) = struct.unpack_from("<I", data, 0x14)
    (attrs,) = struct.unpack_from("<I", data, 0x18)
    icon_index, show = struct.unpack_from("<iI", data, 0x38)
    out["headerSize"] = header_size
    out["clsidOk"] = clsid.hex() == LINK_CLSID.hex()
    out["flags"] = hex(flags)
    out["fileAttributes"] = hex(attrs)
    out["iconIndex"] = icon_index
    out["showCommand"] = show

    pos = header_size
    if flags & F_HAS_LINK_TARGET_IDLIST:
        (idl_size,) = struct.unpack_from("<H", data, pos)
        out["targetIdListBytes"] = idl_size
        pos += 2 + idl_size

    if flags & F_HAS_LINK_INFO:
        (info_size, info_header, info_flags) = struct.unpack_from("<III", data, pos)
        base = pos
        out["linkInfoSize"] = info_size
        out["linkInfoFlags"] = hex(info_flags)
        v_off, lb_off, net_off, suffix_off = struct.unpack_from("<IIII", data, pos + 12)
        if lb_off:
            out["localBasePath"] = _cstring(data, base + lb_off)
        if (info_flags & 0x00000001) and v_off:
            v = base + v_off
            drive_type, serial, label_off = struct.unpack_from("<III", data, v + 4)
            out["driveType"] = drive_type
            out["volumeSerial"] = hex(serial)
            # 0x14 == offset of the unicode slot => no ASCII label present
            if label_off and label_off != 0x14:
                out["volumeLabel"] = _cstring(data, v + label_off, limit=v + info_size)
        if info_header >= 0x24:
            (lb_u,) = struct.unpack_from("<I", data, pos + 0x1C)
            if lb_u:
                out["localBasePathUnicode"] = _unicode_from(data, base + lb_u)
        pos = base + info_size

    strings = []
    if flags & F_IS_UNICODE:
        order = [
            (F_HAS_NAME, "name"),
            (F_HAS_RELATIVE_PATH, "relativePath"),
            (F_HAS_WORKING_DIR, "workingDir"),
            (F_HAS_ARGUMENTS, "arguments"),
            (F_HAS_ICON_LOCATION, "iconLocation"),
        ]
        for bit, key in order:
            if not (flags & bit):
                continue
            (count,) = struct.unpack_from("<H", data, pos)
            pos += 2
            raw = data[pos : pos + count * 2]
            end = raw.rfind(b"\x00\x00")
            out[key] = raw[: end if end >= 0 else len(raw)].decode("utf-16-le", "replace")
            pos += count * 2
    return out


def _cstring(data: bytes, offset: int, limit: int | None = None) -> str:
    try:
        end = data.index(b"\x00", offset, len(data) if limit is None else limit)
    except ValueError:
        end = limit if limit is not None else len(data)
    return data[offset:end].decode("mbcs", "replace")


if __name__ == "__main__":
    import json
    import sys

    with open(sys.argv[1], "rb") as handle:
        print(json.dumps(parse_lnk(handle.read()), ensure_ascii=False, indent=2))
