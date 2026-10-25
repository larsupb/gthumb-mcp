"""gThumb comment sidecar files (<folder>/.comments/<image>.xml).

Debian's gThumb 3.12 build has no exiv2/gexiv2 linkage, so its comments
extension stores tags (categories) as per-folder sidecar XML files next to
the images — regardless of the store-metadata-in-files setting. Format:

    <?xml version="1.0" encoding="UTF-8"?>
    <comment version="3.0">
      <caption/>
      <note/>
      <place/>
      <categories>
        <category value="Selfie"/>
      </categories>
    </comment>

This is what the gThumb UI reads and writes for tags on such builds, so the
server keeps sidecars in sync alongside the embedded XMP.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from .util import atomic_write_text

SIDECAR_DIR = ".comments"
COMMENT_VERSION = "3.0"


class SidecarError(Exception):
    pass


def sidecar_path(image_path: Path) -> Path:
    """Sidecar XML path for an image: <dir>/.comments/<image filename>.xml."""
    image_path = Path(image_path)
    return image_path.parent / SIDECAR_DIR / (image_path.name + ".xml")


def read_sidecar(image_path: Path) -> dict | None:
    """Parse a sidecar into its fields, or None if absent/unreadable."""
    path = sidecar_path(image_path)
    if not path.is_file():
        return None
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError):
        return None

    def text_of(tag: str) -> str:
        el = root.find(tag)
        return (el.text or "") if el is not None else ""

    rating_el = root.find("rating")
    try:
        rating = int(rating_el.get("value", "0")) if rating_el is not None else 0
    except (TypeError, ValueError):
        rating = 0

    return {
        "caption": text_of("caption"),
        "note": text_of("note"),
        "place": text_of("place"),
        "rating": rating,
        "categories": [
            el.get("value", "")
            for el in root.findall("categories/category")
            if el.get("value")
        ],
    }


def read_categories(image_path: Path) -> list[str]:
    """Sidecar categories for an image (UI-visible tags); [] if no sidecar."""
    sidecar = read_sidecar(image_path)
    return sidecar["categories"] if sidecar else []


def update_sidecar(
    image_path: Path,
    caption: str | None = None,
    note: str | None = None,
    place: str | None = None,
    rating: int | None = None,
    tags: list[str] | None = None,
    tags_replace: bool = True,
) -> dict:
    """Partially update a comment sidecar; only non-None fields change.

    This mirrors gThumb's own sidecar writer (gth-comment.c, comment
    version 3.0): caption/note/place as element text, `<rating value="N"/>`
    (omitted when 0), `<categories><category value=…/>`. All other content
    is preserved. Returns the full sidecar state after the update.
    """
    image_path = Path(image_path)
    path = sidecar_path(image_path)

    if path.is_file():
        try:
            tree = ET.parse(path)
        except ET.ParseError as exc:
            raise SidecarError(f"Cannot parse sidecar {path}: {exc}") from exc
        root = tree.getroot()
    else:
        root = ET.Element("comment", {"version": COMMENT_VERSION})
        ET.SubElement(root, "caption")
        ET.SubElement(root, "note")
        ET.SubElement(root, "place")
        ET.SubElement(root, "categories")
        tree = ET.ElementTree(root)

    def set_text(tag: str, value: str) -> None:
        el = root.find(tag)
        if el is None:
            el = ET.Element(tag)
            cats = root.find("categories")
            root.insert(list(root).index(cats), el) if cats is not None else root.append(el)
        el.text = value

    if caption is not None:
        set_text("caption", caption)
    if note is not None:
        set_text("note", note)
    if place is not None:
        set_text("place", place)

    if rating is not None:
        rating = max(0, min(5, int(rating)))
        el = root.find("rating")
        if rating == 0:
            if el is not None:
                root.remove(el)
        else:
            if el is None:
                # Match gThumb's own element order: rating sits after
                # place and before categories.
                el = ET.Element("rating")
                cats = root.find("categories")
                root.insert(list(root).index(cats), el) if cats is not None else root.append(el)
            el.set("value", str(rating))

    final_categories: list[str] = []
    if tags is not None:
        categories = root.find("categories")
        if categories is None:
            categories = ET.SubElement(root, "categories")
        existing = [
            el.get("value", "") for el in categories.findall("category") if el.get("value")
        ]
        final_categories = (
            list(dict.fromkeys(tags))
            if tags_replace
            else list(dict.fromkeys(existing + [t for t in tags if t not in existing]))
        )
        for el in list(categories.findall("category")):
            categories.remove(el)
        for tag in final_categories:
            ET.SubElement(categories, "category", {"value": tag})

    ET.indent(root)
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(
        root, encoding="unicode"
    )
    atomic_write_text(path, xml)

    sidecar = read_sidecar(image_path) or {}
    return {
        "caption": sidecar.get("caption", ""),
        "note": sidecar.get("note", ""),
        "place": sidecar.get("place", ""),
        "rating": sidecar.get("rating", 0),
        "categories": final_categories,
    }


def write_sidecar_tags(image_path: Path, tags: list[str], replace: bool = True) -> list[str]:
    """Write tags as sidecar categories (merging when replace=False).

    Preserves all other sidecar content. Returns the final category list.
    """
    state = update_sidecar(image_path, tags=tags, tags_replace=replace)
    return state["categories"]
