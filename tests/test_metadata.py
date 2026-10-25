"""Tests for embedded XMP metadata via exiftool (skipped when exiftool is missing)."""

from __future__ import annotations

import shutil

import pytest

from gthumb_mcp import metadata

from .conftest import make_image

pytestmark = pytest.mark.skipif(
    shutil.which("exiftool") is None, reason="exiftool not installed"
)


def test_set_and_read_rating_tags_comment(gthumb_home):
    img = make_image(gthumb_home["data"] / "img" / "a.png")

    metadata.set_rating(img, 5)
    metadata.set_tags(img, ["Family", "Beach"], replace=True)
    metadata.set_comment(img, title="Sunset", description="At the shore", location="Nice")

    info = metadata.get_image_info(img)
    assert info["rating"] == 5
    assert info["tags"] == ["Family", "Beach"]
    assert info["title"] == "Sunset"
    assert info["description"] == "At the shore"
    assert info["location"] == "Nice"
    assert info["width"] == 64
    assert info["height"] == 48
    assert info["file_type"] == "PNG"


def test_set_tags_append_and_replace(gthumb_home):
    img = make_image(gthumb_home["data"] / "img" / "b.png")

    metadata.set_tags(img, ["one", "two"], replace=True)
    metadata.set_tags(img, ["three"], replace=False)
    assert metadata.get_image_info(img)["tags"] == ["one", "two", "three"]

    metadata.set_tags(img, ["four"], replace=True)
    assert metadata.get_image_info(img)["tags"] == ["four"]


def test_rating_clamped(gthumb_home):
    img = make_image(gthumb_home["data"] / "img" / "c.png")
    metadata.set_rating(img, 99)
    assert metadata.get_image_info(img)["rating"] == 5
    metadata.set_rating(img, -3)
    assert metadata.get_image_info(img)["rating"] == 0
