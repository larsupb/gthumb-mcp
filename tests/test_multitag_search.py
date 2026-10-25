"""Tests for multi-tag AND/OR search (snapshot and live modes)."""

from __future__ import annotations

import json

import pytest

from gthumb_mcp import server

from .conftest import make_image, write_catalog


@pytest.fixture
def tagged(gthumb_home):
    """Three images tagged: a=Beach+Family, b=Beach, c=Family."""
    a = make_image(gthumb_home["data"] / "img" / "a.jpg")
    b = make_image(gthumb_home["data"] / "img" / "b.jpg")
    c = make_image(gthumb_home["data"] / "img" / "c.jpg")
    write_catalog(gthumb_home["data"], "Tags/Beach.search", "Beach", [a, b])
    write_catalog(gthumb_home["data"], "Tags/Family.search", "Family", [a, c])
    return a.resolve(), b.resolve(), c.resolve()


def str_files(result: dict) -> set[str]:
    return {f if isinstance(f, str) else f["path"] for f in result["files"]}


def test_and_intersection(gthumb_home, tagged):
    a, b, c = tagged
    res = server.find_images_by_tags(tags=["Beach", "Family"], match="AND")
    data = json.loads(res)
    assert data["match"] == "AND"
    assert str_files(data) == {str(a)}


def test_or_union_with_matched_tags(gthumb_home, tagged):
    a, b, c = tagged
    res = server.find_images_by_tags(tags=["Beach", "Family"], match="OR")
    data = json.loads(res)
    assert str_files(data) == {str(a), str(b), str(c)}
    assert data["matched_tags"][str(a)] == ["Beach", "Family"]
    assert data["matched_tags"][str(b)] == ["Beach"]
    assert data["matched_tags"][str(c)] == ["Family"]


def test_and_with_missing_snapshot_raises(gthumb_home, tagged):
    with pytest.raises(ValueError, match="No gThumb tag snapshot"):
        server.find_images_by_tags(tags=["Beach", "Nonexistent"], match="AND")


def test_or_tolerates_missing_snapshot(gthumb_home, tagged):
    a, b, c = tagged
    res = server.find_images_by_tags(tags=["Beach", "Nonexistent"], match="OR")
    data = __import__("json").loads(res)
    assert str_files(data) == {str(a), str(b)}
    assert "Nonexistent" in data["note"]


def test_invalid_match_mode(gthumb_home):
    with pytest.raises(ValueError, match="match must be"):
        server.find_images_by_tags(tags=["Beach"], match="XOR")


def test_live_scan_and(gthumb_home, tagged):
    import json

    a, b, c = tagged
    # Tag the files themselves (embedded XMP): a gets both, b only Beach.
    from gthumb_mcp import metadata

    metadata.set_tags(a, ["Beach", "Family"], replace=True)
    metadata.set_tags(b, ["Beach"], replace=True)
    res = server.find_images_by_tags(
        tags=["Beach", "Family"], match="AND", directory=str(gthumb_home["data"])
    )
    data = json.loads(res)
    assert data["source"] == "embedded-xmp"
    assert str_files(data) == {str(a)}

    res = server.find_images_by_tags(
        tags=["Beach", "Family"], match="OR", directory=str(gthumb_home["data"])
    )
    data = json.loads(res)
    assert str_files(data) == {str(a), str(b)}
