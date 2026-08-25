from __future__ import annotations

import os
from pathlib import Path


def atomic_write_text(path: Path, content: str, encoding: str = "utf-8") -> None:
    """Write text to `path` atomically — either the old content or the new, never a partial file.

    A process killed mid-write (the MCP server terminated, a crash) with a
    plain `Path.write_text()` can leave a truncated file on disk. Writes to
    a sibling temp file first and `os.replace()`s it into place —
    `replace()` is atomic on POSIX and Windows *within the same
    filesystem*, which a same-directory temp file guarantees. On any
    failure before the replace, the original file (if any) is left
    untouched, and the temp file is cleaned up rather than orphaned.
    """
    tmp_path = path.with_name(f".{path.name}.tmp{os.getpid()}")
    try:
        tmp_path.write_text(content, encoding=encoding)
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
