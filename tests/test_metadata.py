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

    # replace_keywords wipes the whole XMP, so set rating/comment afterwards
    # (set_rating/set_comment don't wipe).
    metadata.replace_keywords(img, ["Family", "Beach"])
    metadata.set_rating(img, 5)
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


def test_replace_keywords_clears_iptc_ghost_store(gthumb_home):
    img = make_image(gthumb_home["data"] / "img" / "b.png")

    # Simulate a legacy tool that wrote keywords only to the IPTC IIM block.
    metadata._run(["-overwrite_original", "-IPTC:Keywords=Whirlpool", str(img)])
    assert metadata.get_tags(img) == ["Whirlpool"]

    metadata.replace_keywords(img, ["Proper"])

    # Ghost store wiped and rebuilt with exactly the new tags; nothing stale.
    assert metadata.get_tags(img) == ["Proper"]
    assert metadata.get_image_info(img)["tags"] == ["Proper"]


def test_replace_keywords_empty_clears_everything(gthumb_home):
    img = make_image(gthumb_home["data"] / "img" / "c.png")
    metadata.replace_keywords(img, ["one", "two"], write_iptc=True)
    assert metadata.get_tags(img) == ["one", "two"]

    metadata.replace_keywords(img, [])

    assert metadata.get_tags(img) == []


def test_replace_keywords_restores_non_keyword_fields(gthumb_home):
    img = make_image(gthumb_home["data"] / "img" / "d.png")
    metadata.set_rating(img, 3)
    metadata.set_comment(img, title="Title", description="Desc", location="Loc")

    # The wipe clears all XMP; restore must re-apply the sidecar-managed
    # fields (rating/title/description/location) alongside the new tags.
    restore = {"rating": 3, "caption": "Title", "note": "Desc", "place": "Loc"}
    metadata.replace_keywords(img, ["tag"], restore=restore)

    info = metadata.get_image_info(img)
    assert info["rating"] == 3
    assert info["title"] == "Title"
    assert info["description"] == "Desc"
    assert info["location"] == "Loc"
    assert info["tags"] == ["tag"]


def test_rating_clamped(gthumb_home):
    img = make_image(gthumb_home["data"] / "img" / "c.png")
    metadata.set_rating(img, 99)
    assert metadata.get_image_info(img)["rating"] == 5
    metadata.set_rating(img, -3)
    assert metadata.get_image_info(img)["rating"] == 0
