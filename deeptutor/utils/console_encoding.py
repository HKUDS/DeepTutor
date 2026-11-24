"""Console fallback for narrow output encodings."""

import sys


def relax_console_encoding(streams: tuple[object, ...] | None = None) -> None:
    """Make the launcher's own console output lossy instead of fatal.

    Child pipes are already decoded with ``errors="replace"`` (see ``_spawn``)
    and the children themselves get ``PYTHONIOENCODING=utf-8:replace``, but the
    parent process re-encodes every relayed line with the console's own codec.
    On a legacy Windows code page (cp950/cp936/cp932) an ordinary Next.js
    banner character like ``✓`` then raises ``UnicodeEncodeError`` inside
    ``_stream_output``, killing the relay thread — the app keeps running but
    goes silent for the rest of the session (issue #702).
    """
    for stream in streams if streams is not None else (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(errors="replace")
        except (ValueError, OSError):
            # Already-detached or non-reconfigurable stream: nothing to relax.
            continue
