"""Shared pytest fixtures: a fake gThumb home directory."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from gthumb_mcp.util import path_to_uri

CONFIG_DIR = "config"
DATA_DIR = "data"
CACHE_DIR = "cache"


@pytest.fixture
def gthumb_home(tmp_path, monkeypatch) -> dict[str, Path]:
    """Redirect all gthumb_mcp paths into a temporary directory."""
    dirs = {
        "config": tmp_path / CONFIG_DIR,
        "data": tmp_path / DATA_DIR,
        "cache": tmp_path / CACHE_DIR,
    }
    dirs["config"].mkdir()
    dirs["data"].mkdir()
    dirs["cache"].mkdir()
    monkeypatch.setenv("GTHUMB_CONFIG_DIR", str(dirs["config"]))
    monkeypatch.setenv("GTHUMB_DATA_DIR", str(dirs["data"]))
    monkeypatch.setenv("XDG_CACHE_HOME", str(dirs["cache"]))
    return dirs


def make_image(path: Path, size: tuple[int, int] = (64, 48), color=(200, 10, 10)) -> Path:
    """Create a minimal PNG image for tests."""
    from PIL import Image as PILImage

    path.parent.mkdir(parents=True, exist_ok=True)
    PILImage.new("RGB", size, color).save(path, format="PNG")
    return path


def write_tags_xml(config_dir: Path, tags: list[str]) -> None:
    root = ET.Element("tags", {"version": "1.0"})
    for tag in tags:
        ET.SubElement(root, "tag", {"value": tag})
    ET.indent(root)
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode")
    (config_dir / "tags.xml").write_text(xml, encoding="utf-8")


def write_catalog(data_dir: Path, relative: str, name: str, paths: list[Path]) -> Path:
    path = data_dir / "catalogs" / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    files = ET.Element("files")
    for p in paths:
        ET.SubElement(files, "file", {"uri": path_to_uri(p)})
    root = ET.Element("catalog", {"version": "1.0"})
    name_el = ET.SubElement(root, "name")
    name_el.text = name
    root.append(files)
    ET.indent(root)
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode")
    path.write_text(xml, encoding="utf-8")
    return path
