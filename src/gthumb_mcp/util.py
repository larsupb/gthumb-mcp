"""Small shared helpers."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit


def path_to_uri(path: str | os.PathLike[str]) -> str:
    """Convert a filesystem path to a file:// URI, percent-encoded like gThumb does."""
    return "file://" + quote(str(Path(path).resolve()))


def uri_to_path(uri: str) -> Path:
    """Convert a file:// URI back to a filesystem path."""
    return Path(unquote(urlsplit(uri).path))


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write bytes atomically: temp file in the same directory, then os.replace."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))
