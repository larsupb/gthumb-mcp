"""Tests for the thumbnail cache."""

from __future__ import annotations

from gthumb_mcp import thumbnails

from .conftest import make_image


def test_thumbnail_is_generated_and_cached(gthumb_home):
    img = make_image(gthumb_home["data"] / "img" / "a.png")

    cached = thumbnails.cached_thumbnail(img, "large")
    assert cached is None

    thumb = thumbnails.ensure_thumbnail(img, "large")
    assert thumb.is_file()
    assert thumb.parent == gthumb_home["cache"] / "thumbnails" / "large"

    # Second call must be served from the cache (same path).
    assert thumbnails.ensure_thumbnail(img, "large") == thumb


def test_thumbnail_matches_freedesktop_md5_layout(gthumb_home):
    import hashlib

    img = make_image(gthumb_home["data"] / "img" / "b.png")
    thumb = thumbnails.ensure_thumbnail(img, "normal")
    uri = f"file://{img.resolve()}"
    expected_name = hashlib.md5(uri.encode()).hexdigest() + ".png"  # noqa: S324
    assert thumb.name == expected_name

    # The Thumb::URI annotation must be present in the PNG.
    data = thumb.read_bytes()
    assert uri.encode() in data
