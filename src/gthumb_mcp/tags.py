"""Read and write gThumb's tag definitions (~/.config/gthumb/tags.xml).

Tags themselves are stored on images (embedded XMP in the
"store metadata in files" mode, which is gThumb 3.12's default).
tags.xml only declares the known tag names; the Tags/ directory inside
the catalogs folder holds per-tag search snapshots gThumb keeps as caches.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .paths import catalogs_dir, tags_file
from .util import atomic_write_text


class TagError(Exception):
    pass


def _sanitize_tag(name: str) -> str:
    cleaned = name.strip()
    if not cleaned:
        raise TagError("Tag name must not be empty")
    return cleaned


def list_tags() -> list[str]:
    path = tags_file()
    if not path.is_file():
        return []
    tree = ET.parse(path)
    return [
        el.get("value", "")
        for el in tree.getroot().findall("tag")
        if el.get("value")
    ]


def _write_tags(tags: list[str]) -> None:
    root = ET.Element("tags", {"version": "1.0"})
    for tag in tags:
        ET.SubElement(root, "tag", {"value": tag})
    ET.indent(root)
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(
        root, encoding="unicode"
    )
    atomic_write_text(tags_file(), xml)


def create_tag(tag: str) -> None:
    tag = _sanitize_tag(tag)
    tags = list_tags()
    if tag not in tags:
        tags.append(tag)
        _write_tags(tags)


def delete_tag(tag: str) -> None:
    tag = _sanitize_tag(tag)
    tags = list_tags()
    if tag not in tags:
        raise TagError(f"Tag not found: {tag}")
    _write_tags([t for t in tags if t != tag])
    # Remove the cached per-tag search snapshot, if any.
    snapshot = tags_search_file(tag)
    if snapshot.is_file():
        snapshot.unlink()


def rename_tag(old: str, new: str) -> None:
    old = _sanitize_tag(old)
    new = _sanitize_tag(new)
    tags = list_tags()
    if old not in tags:
        raise TagError(f"Tag not found: {old}")
    if new in tags:
        raise TagError(f"Tag already exists: {new}")
    _write_tags([new if t == old else t for t in tags])
    old_snapshot = tags_search_file(old)
    new_snapshot = tags_search_file(new)
    if old_snapshot.is_file():
        old_snapshot.rename(new_snapshot)


def tags_search_file(tag: str) -> Path:
    """Snapshot file gThumb keeps under catalogs/Tags/<tag>.search."""
    return catalogs_dir() / "Tags" / f"{tag}.search"


def read_tag_snapshot(tag: str) -> list[Path] | None:
    """Return image paths from the per-tag search snapshot, or None if absent."""
    path = tags_search_file(tag)
    if not path.is_file():
        return None
    tree = ET.parse(path)
    files = []
    files_el = tree.getroot().find("files")
    if files_el is not None:
        for el in files_el.findall("file"):
            uri = el.get("uri")
            if uri:
                files.append(Path(unquote(urlsplit(uri).path)))
    return files
