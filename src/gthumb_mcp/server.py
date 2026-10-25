"""gThumb MCP server: exposes gThumb catalogs, tags and image metadata as MCP tools."""

from __future__ import annotations

import fnmatch
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from mcp.server.mcpserver import Image, MCPServer

from . import catalogs, metadata, tags, thumbnails

mcp = MCPServer("gthumb")

IMAGE_FILE = "image file (path)"
CATALOG_NAME = "catalog or saved-search name, e.g. 'Command Line' or 'Random/Trips.catalog'"


def _ok(data) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False)


def _existing_file(path: str) -> Path:
    p = Path(path).expanduser()
    if not p.is_file():
        raise ValueError(f"File not found: {path}")
    return p


def _existing_dir(path: str) -> Path:
    p = Path(path).expanduser()
    if not p.is_dir():
        raise ValueError(f"Directory not found: {path}")
    return p


# ---------------------------------------------------------------- catalogs

@mcp.tool()
def list_catalogs() -> str:
    """List all gThumb catalogs and saved searches with their item counts."""
    return _ok(catalogs.list_catalogs())


@mcp.tool()
def get_catalog(name: str) -> str:
    """Get the list of image files stored in a gThumb catalog or saved search."""
    files = catalogs.read_catalog_files(name)
    return _ok({"name": name, "count": len(files), "files": [str(f) for f in files]})


@mcp.tool()
def create_catalog(name: str) -> str:
    """Create a new, empty gThumb catalog. Use a relative path like 'Random/Trips' to place it in a subfolder."""
    return _ok(catalogs.create_catalog(name))


@mcp.tool()
def delete_catalog(name: str) -> str:
    """Delete a gThumb catalog (.catalog) or saved-search (.search) file."""
    catalogs.delete_catalog(name)
    return _ok({"deleted": name})


@mcp.tool()
def add_to_catalog(name: str, paths: list[str]) -> str:
    """Add image files to a gThumb catalog (duplicates are skipped)."""
    added = catalogs.add_to_catalog(name, paths)
    return _ok({"catalog": name, "added": added})


@mcp.tool()
def remove_from_catalog(name: str, paths: list[str]) -> str:
    """Remove image files from a gThumb catalog."""
    removed = catalogs.remove_from_catalog(name, paths)
    return _ok({"catalog": name, "removed": removed})


# ---------------------------------------------------------------- tags

@mcp.tool()
def list_tags() -> str:
    """List all tags known to gThumb (from ~/.config/gthumb/tags.xml)."""
    return _ok({"tags": tags.list_tags()})


@mcp.tool()
def create_tag(tag: str) -> str:
    """Create a new tag in gThumb."""
    tags.create_tag(tag)
    return _ok({"created": tag})


@mcp.tool()
def delete_tag(tag: str) -> str:
    """Delete a tag definition (does not rewrite images; use set_tags to untag files)."""
    tags.delete_tag(tag)
    return _ok({"deleted": tag})


@mcp.tool()
def rename_tag(old: str, new: str) -> str:
    """Rename a tag in gThumb's tag list (and its cached search snapshot)."""
    tags.rename_tag(old, new)
    return _ok({"renamed": old, "to": new})


@mcp.tool()
def find_images_by_tag(tag: str, directory: str | None = None) -> str:
    """Find images with a gThumb tag. Reads the cached snapshot by default;
    pass `directory` to instead scan embedded XMP metadata live under that directory."""
    if directory is not None:
        base = _existing_dir(directory)
        candidates = metadata.iter_image_files(base)
        matches = []
        for info, path in _metadata_with_paths(candidates):
            if tag in (info.get("tags") or []):
                matches.append(str(path))
        return _ok({"tag": tag, "source": "embedded-xmp", "count": len(matches), "files": matches})

    snapshot = tags.read_tag_snapshot(tag)
    if snapshot is None:
        return _ok({"tag": tag, "source": "snapshot", "count": 0,
                    "files": [], "note": "No cached snapshot; pass directory to scan embedded XMP."})
    return _ok({"tag": tag, "source": "snapshot", "count": len(snapshot),
                "files": [str(p) for p in snapshot]})


# ---------------------------------------------------------------- metadata

@mcp.tool()
def get_image_info(path: str) -> str:
    """Get image details: dimensions, format, camera, date, GPS, and gThumb metadata (title, description, tags, rating)."""
    p = _existing_file(path)
    info = metadata.get_image_info(p)
    info["path"] = str(p)
    return _ok(info)


@mcp.tool()
def set_rating(path: str, rating: int) -> str:
    """Set the gThumb star rating (0-5) of an image, stored as embedded XMP. This modifies the file."""
    p = _existing_file(path)
    applied = metadata.set_rating(p, rating)
    return _ok({"path": str(p), "rating": applied})


@mcp.tool()
def set_tags(path: str, tags: list[str], replace: bool = True) -> str:
    """Set the gThumb tags of an image (embedded XMP). Set replace=false to append instead. This modifies the file."""
    p = _existing_file(path)
    applied = metadata.set_tags(p, tags, replace=replace)
    return _ok({"path": str(p), "tags": applied, "replaced": replace})


@mcp.tool()
def set_comment(path: str, title: str | None = None, description: str | None = None,
                location: str | None = None) -> str:
    """Set an image's title, description (comment) and/or location in gThumb-compatible embedded XMP. Only non-None fields are changed."""
    p = _existing_file(path)
    metadata.set_comment(p, title=title, description=description, location=location)
    return _ok({"path": str(p), "title": title, "description": description, "location": location})


# ---------------------------------------------------------------- search & view

def _metadata_with_paths(paths: list[Path], chunk: int = 400):
    for start in range(0, len(paths), chunk):
        for rec in metadata.read_metadata_batch(paths[start:start + chunk]):
            src = rec.get("SourceFile")
            yield metadata._one(rec), Path(src) if src else None


@mcp.tool()
def find_images(directory: str, name_pattern: str | None = None, tag: str | None = None,
                min_rating: int | None = None, newer_than: str | None = None,
                older_than: str | None = None, limit: int = 50) -> str:
    """Find images under a directory, optionally filtered by filename pattern (glob), tag, minimum rating (0-5) or modification date (ISO, e.g. 2025-01-01)."""
    base = _existing_dir(directory)
    candidates = metadata.iter_image_files(base)
    if name_pattern:
        pat = name_pattern.lower()
        candidates = [p for p in candidates if fnmatch.fnmatch(p.name.lower(), pat)]

    def mtime(p: Path) -> float:
        return p.stat().st_mtime

    if newer_than:
        floor = datetime.fromisoformat(newer_than).replace(tzinfo=timezone.utc).timestamp()
        candidates = [p for p in candidates if mtime(p) >= floor]
    if older_than:
        ceiling = datetime.fromisoformat(older_than).replace(tzinfo=timezone.utc).timestamp()
        candidates = [p for p in candidates if mtime(p) <= ceiling]
    candidates.sort(key=mtime, reverse=True)

    if tag or min_rating is not None:
        matches = []
        for info, path in _metadata_with_paths(candidates):
            if path is None:
                continue
            if min_rating is not None and (info.get("rating") or 0) < min_rating:
                continue
            if tag and tag not in (info.get("tags") or []):
                continue
            matches.append({"path": str(path), "rating": info.get("rating"),
                            "tags": info.get("tags"), "date_taken": info.get("date_taken")})
            if len(matches) >= limit:
                break
        return _ok({"directory": str(base), "count": len(matches), "images": matches})

    return _ok({"directory": str(base), "count": len(candidates),
                "images": [{"path": str(p), "mtime": datetime.fromtimestamp(mtime(p), timezone.utc).isoformat()}
                           for p in candidates[:limit]]})


@mcp.tool()
def get_thumbnail(path: str, size: str = "large") -> Image:
    """Get an image's thumbnail (128px 'normal' or 512px 'large') from the shared
    freedesktop thumbnail cache used by gThumb, generating one if missing."""
    p = _existing_file(path)
    thumb = thumbnails.ensure_thumbnail(p, size)
    return Image(data=thumb.read_bytes(), format="png")


@mcp.tool()
def get_image(path: str, max_size: int = 1024) -> Image:
    """Get an image's full content for viewing, downscaled to fit max_size pixels."""
    p = _existing_file(path)
    data, fmt = thumbnails.load_image_bytes(p, max_size)
    return Image(data=data, format=fmt)


# ---------------------------------------------------------------- convenience

@mcp.tool()
def open_in_gthumb(path: str) -> str:
    """Open a file (or directory) in the gThumb desktop application."""
    p = _existing_file(path)
    subprocess.Popen(  # noqa: S603 - fixed binary name, user-supplied single arg
        ["gthumb", str(p)], start_new_session=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return _ok({"opened": str(p)})


def main() -> None:
    """Entry point: run the MCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
