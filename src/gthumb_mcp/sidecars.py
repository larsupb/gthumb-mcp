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

    return {
        "caption": text_of("caption"),
        "note": text_of("note"),
        "place": text_of("place"),
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


def write_sidecar_tags(image_path: Path, tags: list[str], replace: bool = True) -> list[str]:
    """Write tags as sidecar categories.

    Preserves all other sidecar content (caption/note/place, unknown elements).
    With replace=True the category list becomes exactly `tags`; with
    replace=False requested tags are merged into the existing ones. Returns
    the final category list.
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

    categories = root.find("categories")
    if categories is None:
        categories = ET.SubElement(root, "categories")

    existing = [
        el.get("value", "") for el in categories.findall("category") if el.get("value")
    ]
    if replace:
        final = list(dict.fromkeys(tags))
    else:
        final = list(dict.fromkeys(existing + [t for t in tags if t not in existing]))

    # Rebuild only the categories element; everything else is untouched.
    for el in list(categories.findall("category")):
        categories.remove(el)
    for tag in final:
        ET.SubElement(categories, "category", {"value": tag})

    ET.indent(root)
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(
        root, encoding="unicode"
    )
    atomic_write_text(path, xml)
    return final
