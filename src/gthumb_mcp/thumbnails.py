"""freedesktop.org thumbnail cache access (~/.cache/thumbnails).

Thumbnails are PNGs named after the MD5 of the image's file:// URI:
  ~/.cache/thumbnails/normal/<md5>.png  -> up to 128x128
  ~/.cache/thumbnails/large/<md5>.png   -> up to 512x512

gThumb uses this same cache, so thumbnails generated here show up for
gThumb and vice versa. Missing thumbnails are generated with Pillow and
stored in the cache using the spec's Thumb::URI / Thumb::MTime annotations.
"""

from __future__ import annotations

import hashlib
import io
import os
import time
from pathlib import Path

from PIL import Image as PILImage
from PIL.PngImagePlugin import PngInfo

from .paths import thumbnail_cache_dir
from .util import path_to_uri

THUMBNAIL_SIZES = {"normal": 128, "large": 512}


class ThumbnailError(Exception):
    pass


def thumbnail_cache_path(image_path: Path, size: str = "large") -> Path:
    if size not in THUMBNAIL_SIZES:
        raise ThumbnailError(f"size must be one of {sorted(THUMBNAIL_SIZES)}, got: {size}")
    uri = path_to_uri(image_path)
    digest = hashlib.md5(uri.encode("utf-8")).hexdigest()  # noqa: S324 - spec mandates MD5
    return thumbnail_cache_dir() / size / f"{digest}.png"


def cached_thumbnail(image_path: Path, size: str = "large") -> Path | None:
    """Return the cached thumbnail path if gThumb/anything already created one."""
    path = thumbnail_cache_path(image_path, size)
    return path if path.is_file() else None


def ensure_thumbnail(image_path: Path, size: str = "large") -> Path:
    """Return a thumbnail file for image_path, generating and caching it if needed."""
    cached = cached_thumbnail(image_path, size)
    if cached is not None:
        return cached
    target = thumbnail_cache_path(image_path, size)
    png = render_thumbnail(image_path, THUMBNAIL_SIZES[size], uri=path_to_uri(image_path))
    _store(target, png)
    return target


def _store(target: Path, png_bytes: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(target.parent, 0o700)
    except OSError:
        pass
    tmp = target.with_suffix(".png.tmp")
    tmp.write_bytes(png_bytes)
    os.replace(tmp, target)


def render_thumbnail(image_path: Path, max_px: int, uri: str | None = None) -> bytes:
    """Render thumbnail PNG bytes for an image (does not touch the cache)."""
    with PILImage.open(image_path) as im:
        frame = im.convert("RGB") if im.mode not in ("RGB", "RGBA") else im
        frame.thumbnail((max_px, max_px), PILImage.LANCZOS)
        buf = io.BytesIO()
        info = PngInfo()
        info.add_text("Software", "gthumb-mcp")
        if uri is None:
            uri = path_to_uri(image_path)
        info.add_text("Thumb::URI", uri)
        info.add_text("Thumb::MTime", str(int(os.path.getmtime(image_path))))
        frame.save(buf, format="PNG", pnginfo=info)
        return buf.getvalue()


def load_image_bytes(image_path: Path, max_size: int = 1024) -> tuple[bytes, str]:
    """Load an image, downscaled to fit max_size, as (png_bytes, format)."""
    with PILImage.open(image_path) as im:
        frame = im.convert("RGB") if im.mode not in ("RGB", "RGBA") else im
        if max_size > 0:
            frame.thumbnail((max_size, max_size), PILImage.LANCZOS)
        buf = io.BytesIO()
        frame.save(buf, format="PNG")
        return buf.getvalue(), "png"


def cache_age_seconds(path: Path) -> float:
    return max(0.0, time.time() - path.stat().st_mtime)
