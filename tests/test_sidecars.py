"""Tests for gThumb comment sidecar files (.comments/<image>.xml)."""

from __future__ import annotations

import json
import shutil
import xml.etree.ElementTree as ET

import pytest

from gthumb_mcp import metadata, server, sidecars, tags as tags_module

from .conftest import make_image

EXIFTOOL = shutil.which("exiftool") is not None


def test_sidecar_path(gthumb_home):
    img = gthumb_home["data"] / "img" / "pic.png"
    assert sidecars.sidecar_path(img) == img.parent / ".comments" / "pic.png.xml"


def test_sidecar_created_when_absent(gthumb_home):
    img = make_image(gthumb_home["data"] / "img" / "a.png")
    final = sidecars.write_sidecar_tags(img, ["Beach", "Family"], replace=True)

    assert final == ["Beach", "Family"]
    path = sidecars.sidecar_path(img)
    root = ET.parse(path).getroot()
    assert root.tag == "comment"
    assert root.get("version") == "3.0"
    # gThumb's schema: caption/note/place must exist (empty is fine).
    for tag in ("caption", "note", "place", "categories"):
        assert root.find(tag) is not None
    cats = [c.get("value") for c in root.find("categories").findall("category")]
    assert cats == ["Beach", "Family"]
    # Exactly one category element per tag.
    assert len(root.find("categories").findall("category")) == 2


def test_append_merges_and_preserves_other_fields(gthumb_home):
    img = make_image(gthumb_home["data"] / "img" / "b.png")
    img.parent.mkdir(parents=True, exist_ok=True)
    path = sidecars.sidecar_path(img)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<comment version="3.0">\n'
        "  <caption>Some title</caption>\n"
        "  <note>A note</note>\n"
        "  <place>Someplace</place>\n"
        "  <categories>\n"
        '    <category value="Existing"/>\n'
        "  </categories>\n"
        "</comment>\n",
        encoding="utf-8",
    )

    final = sidecars.write_sidecar_tags(img, ["New"], replace=False)

    assert final == ["Existing", "New"]
    root = ET.parse(path).getroot()
    assert root.find("caption").text == "Some title"
    assert root.find("note").text == "A note"
    assert root.find("place").text == "Someplace"
    cats = [c.get("value") for c in root.find("categories").findall("category")]
    assert cats == ["Existing", "New"]


def test_replace_with_empty_clears_categories_only(gthumb_home):
    img = make_image(gthumb_home["data"] / "img" / "c.png")
    sidecars.write_sidecar_tags(img, ["Old"], replace=True)

    final = sidecars.write_sidecar_tags(img, [], replace=True)

    assert final == []
    root = ET.parse(sidecars.sidecar_path(img)).getroot()
    assert root.find("categories").findall("category") == []


def test_read_categories_missing_sidecar(gthumb_home):
    img = make_image(gthumb_home["data"] / "img" / "d.png")
    assert sidecars.read_categories(img) == []
    assert sidecars.read_sidecar(img) is None


def test_update_sidecar_rating(gthumb_home):
    img = make_image(gthumb_home["data"] / "img" / "r.png")
    state = sidecars.update_sidecar(img, rating=4)

    assert state["rating"] == 4
    root = ET.parse(sidecars.sidecar_path(img)).getroot()
    rating = root.find("rating")
    assert rating is not None
    assert rating.get("value") == "4"
    # gThumb only writes <rating> when > 0.
    assert sidecars.update_sidecar(img, rating=0)["rating"] == 0
    assert ET.parse(sidecars.sidecar_path(img)).getroot().find("rating") is None


def test_update_sidecar_partial_fields_preserved(gthumb_home):
    img = make_image(gthumb_home["data"] / "img" / "s.png")
    sidecars.update_sidecar(img, caption="Title", note="Body", rating=3, tags=["Keep"])

    sidecars.update_sidecar(img, caption="New title")  # only caption changes
    state = sidecars.read_sidecar(img)
    assert state["caption"] == "New title"
    assert state["note"] == "Body"
    assert state["rating"] == 3
    assert state["categories"] == ["Keep"]


def test_set_rating_writes_sidecar_and_xmp(gthumb_home):
    img = make_image(gthumb_home["data"] / "img" / "t.jpg")
    server.set_rating(str(img), 5)

    assert sidecars.read_sidecar(img)["rating"] == 5
    assert metadata.get_image_info(img)["rating"] == 5


def test_set_comment_writes_sidecar_fields(gthumb_home):
    img = make_image(gthumb_home["data"] / "img" / "u.png")
    server.set_tags(str(img), ["Keep"], replace=True)
    server.set_comment(str(img), title="A title", description="A description", location="A place")

    sidecar = sidecars.read_sidecar(img)
    assert sidecar["caption"] == "A title"
    assert sidecar["note"] == "A description"
    assert sidecar["place"] == "A place"
    assert sidecar["categories"] == ["Keep"]  # untouched by set_comment


def test_get_image_info_fills_missing_fields_from_sidecar(gthumb_home):
    img = make_image(gthumb_home["data"] / "img" / "v.png")
    sidecars.update_sidecar(img, caption="Sidecar title", note="Sidecar note", rating=4, tags=["T"])

    info = json.loads(server.get_image_info(str(img)))
    assert info["title"] == "Sidecar title"
    assert info["description"] == "Sidecar note"
    assert info["rating"] == 4
    assert info["tags"] == ["T"]


def test_set_tags_writes_sidecar_and_tags_xml(gthumb_home):
    img = make_image(gthumb_home["data"] / "img" / "e.jpg")
    res = json.loads(server.set_tags(str(img), ["Selfie"], replace=True))

    assert res["tags"] == ["Selfie"]
    root = ET.parse(sidecars.sidecar_path(img)).getroot()
    cats = [c.get("value") for c in root.find("categories").findall("category")]
    assert cats == ["Selfie"]
    assert "Selfie" in tags_module.list_tags()  # registered in tags.xml


def test_set_tags_append_unions_sidecar_and_xmp(gthumb_home):
    img = make_image(gthumb_home["data"] / "img" / "f.jpg")
    server.set_tags(str(img), ["First"], replace=True)

    res = json.loads(server.set_tags(str(img), ["Second"], replace=False))

    assert res["tags"] == ["First", "Second"]
    root = ET.parse(sidecars.sidecar_path(img)).getroot()
    cats = [c.get("value") for c in root.find("categories").findall("category")]
    assert cats == ["First", "Second"]


def test_get_image_info_merges_sidecar_tags(gthumb_home):
    img = make_image(gthumb_home["data"] / "img" / "g.png")
    sidecars.write_sidecar_tags(img, ["SidecarTag"], replace=True)

    info = json.loads(server.get_image_info(str(img)))
    assert info["tags"] == ["SidecarTag"]


@pytest.mark.skipif(not EXIFTOOL, reason="exiftool not installed")
def test_live_scan_includes_sidecar_only_tags(gthumb_home):
    tagged = make_image(gthumb_home["data"] / "img" / "h.jpg")
    untagged = make_image(gthumb_home["data"] / "img" / "i.jpg")
    # Sidecar-only tag: no embedded XMP on either file.
    sidecars.write_sidecar_tags(tagged, ["SidecarOnly"], replace=True)

    res = server.find_images_by_tags(
        tags=["SidecarOnly"], match="AND", directory=str(gthumb_home["data"])
    )
    data = json.loads(res)
    assert data["source"] == "embedded-xmp"
    assert data["count"] == 1
    found = [entry["path"] for entry in data["files"]]
    assert found == [str(tagged.resolve())]


@pytest.mark.skipif(not EXIFTOOL, reason="exiftool not installed")
def test_set_tags_writes_both_stores_consistently(gthumb_home):
    img = make_image(gthumb_home["data"] / "img" / "j.png")
    server.set_tags(str(img), ["One"], replace=True)
    server.set_tags(str(img), ["Two"], replace=False)

    # Both stores must carry the union, so gThumb UI and XMP readers agree.
    assert sidecars.read_categories(img) == ["One", "Two"]
    assert metadata.get_tags(img) == ["One", "Two"]
