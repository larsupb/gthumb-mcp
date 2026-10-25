"""Read and write gThumb catalog files (.catalog) and saved searches (.search).

Both are XML documents listing file URIs:

    <?xml version="1.0" encoding="UTF-8"?>
    <catalog version="1.0">
      <name>My Catalog</name>
      <files>
        <file uri="file:///home/user/Pictures/a.jpg"/>
      </files>
    </catalog>

Saved searches use the same layout with a <search> root element.
gThumb reads these files from ~/.local/share/gthumb/catalogs (including
subdirectories) and refreshes the UI when they change on disk.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from .paths import catalogs_dir
from .util import atomic_write_text, path_to_uri, uri_to_path

CATALOG_EXTENSIONS = {".catalog", ".search"}


class CatalogError(Exception):
    pass


def _sanitize_filename(name: str) -> str:
    keep = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_ ."
    cleaned = "".join(c if c in keep else "_" for c in name).strip()
    return cleaned or "Untitled"


def resolve_catalog_path(name: str, must_exist: bool = True) -> Path:
    """Resolve a catalog by relative path (e.g. 'Random/Trips.catalog') or stem name."""
    root = catalogs_dir()
    candidate = name
    if not candidate.endswith(".catalog") and not candidate.endswith(".search"):
        candidate += ".catalog"
    path = (root / candidate).resolve()
    if root.resolve() not in path.parents and path.parent != root.resolve():
        raise CatalogError(f"Catalog path escapes the catalogs directory: {name}")
    if must_exist:
        if not path.is_file():
            # Fall back to searching by <name> element.
            for found in iter_catalog_files():
                meta = read_catalog(found)
                if meta["name"] == name:
                    return Path(meta["path"])
            raise CatalogError(f"Catalog not found: {name}")
    return path


def iter_catalog_files() -> list[Path]:
    root = catalogs_dir()
    if not root.is_dir():
        return []
    return sorted(
        p for p in root.rglob("*") if p.is_file() and p.suffix in CATALOG_EXTENSIONS
    )


def list_catalogs() -> list[dict]:
    result = []
    for path in iter_catalog_files():
        try:
            meta = read_catalog(path)
        except CatalogError:
            continue
        result.append(
            {
                "name": meta["name"],
                "relative": meta["relative"],
                "type": meta["type"],
                "file_count": len(meta["files"]),
                "path": meta["path"],
            }
        )
    return result


def read_catalog(path: Path) -> dict:
    """Parse a catalog/search file into {name, relative, type, files}."""
    path = Path(path)
    if path.suffix not in CATALOG_EXTENSIONS:
        raise CatalogError(f"Not a catalog file: {path}")
    try:
        tree = ET.parse(path)
    except (ET.ParseError, OSError) as exc:
        raise CatalogError(f"Cannot parse {path}: {exc}") from exc
    root = tree.getroot()
    name_el = root.find("name")
    name = (name_el.text or "").strip() if name_el is not None else ""
    files_el = root.find("files")
    files: list[str] = []
    if files_el is not None:
        for file_el in files_el.findall("file"):
            uri = file_el.get("uri")
            if uri:
                files.append(uri)
    return {
        "name": name or path.stem,
        "relative": str(path.relative_to(catalogs_dir())),
        "type": "search" if path.suffix == ".search" else "catalog",
        "files": files,
        "path": str(path),
    }


def _catalog_xml(root_tag: str, name: str, uris: list[str]) -> str:
    root = ET.Element(root_tag, {"version": "1.0"})
    name_el = ET.SubElement(root, "name")
    name_el.text = name
    files = ET.SubElement(root, "files")
    for uri in uris:
        ET.SubElement(files, "file", {"uri": uri})
    ET.indent(root)
    return ET.tostring(root, encoding="unicode", xml_declaration=False)


def write_catalog_file(path: Path, name: str, files: list[str | Path]) -> None:
    """Atomically write a catalog/search file. `files` are filesystem paths."""
    uris = [path_to_uri(f) if not str(f).startswith("file://") else str(f) for f in files]
    root_tag = "search" if path.suffix == ".search" else "catalog"
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n' + _catalog_xml(root_tag, name, uris)
    atomic_write_text(path, xml)


def create_catalog(name: str) -> dict:
    path = resolve_catalog_path(name, must_exist=False)
    if path.is_file():
        raise CatalogError(f"Catalog already exists: {name}")
    write_catalog_file(path, path.stem, [])
    return {"created": str(path), "relative": str(path.relative_to(catalogs_dir()))}


def delete_catalog(name: str) -> None:
    path = resolve_catalog_path(name, must_exist=True)
    path.unlink()


def read_catalog_files(name: str) -> list[Path]:
    """Return the file paths stored in a catalog."""
    meta = read_catalog(resolve_catalog_path(name))
    return [uri_to_path(u) for u in meta["files"]]


def add_to_catalog(name: str, paths: list[str | Path]) -> int:
    """Append paths to a catalog. Skips entries already present. Returns added count."""
    path = resolve_catalog_path(name)
    meta = read_catalog(path)
    existing = set(meta["files"])
    added = 0
    for p in paths:
        uri = path_to_uri(p)
        if uri not in existing:
            meta["files"].append(uri)
            existing.add(uri)
            added += 1
    if added:
        write_catalog_file(path, meta["name"], meta["files"])
    return added


def remove_from_catalog(name: str, paths: list[str | Path]) -> int:
    """Remove paths from a catalog. Returns removed count."""
    path = resolve_catalog_path(name)
    meta = read_catalog(path)
    remove_uris = {path_to_uri(p) for p in paths}
    kept = [u for u in meta["files"] if u not in remove_uris]
    removed = len(meta["files"]) - len(kept)
    if removed:
        write_catalog_file(path, meta["name"], kept)
    return removed
