"""Member names of ZIP archives written without the UTF-8 name flag.

The ZIP format stores a name as CP437 unless bit 11 (the UTF-8 flag) is set,
and :mod:`zipfile` decodes it that way. Windows' built-in "Compressed (zipped)
folder" ignores the rule and writes the system ANSI code page (GBK on Chinese
Windows) without the flag, and some other tools write UTF-8 without it, so
``ZipInfo.filename`` comes out as mojibake (``第一章.md`` → ``╡┌╥╗╒┬.md``).
CP437 maps every byte, so the original bytes can be recovered and decoded again.
"""

from __future__ import annotations

import zipfile

_UTF8_NAME_FLAG = 0x800
# The same preference FileTypeRouter.TEXT_DECODING_CANDIDATES applies to
# uploaded text of unknown encoding: UTF-8 first, then the Chinese code pages.
_UNFLAGGED_NAME_ENCODINGS = ("utf-8", "gbk", "gb18030")


def zip_member_name(info: zipfile.ZipInfo) -> str:
    """The member's name as the archiving tool meant it.

    Flagged UTF-8 and plain ASCII names are returned unchanged. Otherwise the
    raw bytes are recovered from ``orig_filename`` (``filename`` has already
    had ``os.sep`` rewritten, which would corrupt a GBK byte 0x5C) and decoded
    with the first encoding that accepts them; failing that, the CP437 reading
    is kept.
    """
    name = info.filename
    if info.flag_bits & _UTF8_NAME_FLAG or name.isascii():
        return name
    raw = info.orig_filename.encode("cp437")
    for encoding in _UNFLAGGED_NAME_ENCODINGS:
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return name


__all__ = ["zip_member_name"]
