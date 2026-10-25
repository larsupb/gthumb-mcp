"""gThumb MCP server: exposes gThumb catalogs, tags and image metadata as MCP tools."""

from __future__ import annotations

import fnmatch
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from mcp.server.mcpserver import Image, MCPServer

from . import catalogs, comfyui, metadata, sidecars, thumbnails
from . import tags as tags_module

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
    return _ok({"tags": tags_module.list_tags()})


@mcp.tool()
def create_tag(tag: str) -> str:
    """Create a new tag in gThumb."""
    tags_module.create_tag(tag)
    return _ok({"created": tag})


@mcp.tool()
def delete_tag(tag: str) -> str:
    """Delete a tag definition (does not rewrite images; use set_tags to untag files)."""
    tags_module.delete_tag(tag)
    return _ok({"deleted": tag})


@mcp.tool()
def rename_tag(old: str, new: str) -> str:
    """Rename a tag in gThumb's tag list (and its cached search snapshot)."""
    tags_module.rename_tag(old, new)
    return _ok({"renamed": old, "to": new})


@mcp.tool()
def find_images_by_tags(tags: list[str], match: str = "AND", directory: str | None = None) -> str:
    """Find images by multiple gThumb tags. match='AND': images having ALL tags;
    match='OR': images having AT LEAST ONE tag. Reads gThumb's cached tag snapshots
    by default; pass `directory` to instead scan embedded XMP metadata live."""
    match = (match or "AND").upper()
    if match not in ("AND", "OR"):
        raise ValueError("match must be 'AND' or 'OR'")
    wanted = [t.strip() for t in tags if t.strip()]
    if not wanted:
        raise ValueError("tags must not be empty")

    if directory is not None:
        base = _existing_dir(directory)
        candidates = metadata.iter_image_files(base)
        wanted_set = set(wanted)
        matches = []
        for info, path in _metadata_with_paths(candidates):
            if path is None:
                continue
            present = wanted_set & _all_tags_for(path, info)
            ok = len(present) == len(wanted) if match == "AND" else len(present) > 0
            if ok:
                entry = {"path": str(path)}
                if match == "OR":
                    entry["matched_tags"] = sorted(present)
                matches.append(entry)
        return _ok({"tags": wanted, "match": match, "source": "embedded-xmp",
                    "count": len(matches), "files": matches})

    # Snapshot mode: combine gThumb's per-tag cached search results.
    sets: dict[str, set[str]] = {}
    missing: list[str] = []
    for tag in wanted:
        snapshot = tags_module.read_tag_snapshot(tag)
        if snapshot is None:
            missing.append(tag)
        else:
            sets[tag] = {str(p) for p in snapshot}
    if missing:
        if match == "AND" or not sets:
            raise ValueError(
                "No gThumb tag snapshot for tag(s): " + ", ".join(missing)
                + ". Pass a `directory` to scan embedded XMP metadata live instead."
            )

    if match == "AND":
        files = sorted(set.intersection(*sets.values()))
    else:
        files = sorted(set.union(*sets.values())) if sets else []

    result = {"tags": wanted, "match": match, "source": "snapshot",
              "count": len(files), "files": files}
    if match == "OR":
        result["matched_tags"] = {
            f: sorted(t for t, s in sets.items() if f in s) for f in files
        }
    if missing:
        result["note"] = ("No snapshot for tag(s): " + ", ".join(missing)
                          + " — they contributed nothing to this OR query")
    return _ok(result)


# ---------------------------------------------------------------- metadata

@mcp.tool()
def get_image_info(path: str) -> str:
    """Get image details: dimensions, format, camera, date, GPS, and gThumb metadata (title, description, tags, rating)."""
    p = _existing_file(path)
    info = metadata.get_image_info(p)
    # Merge sidecar data: depending on the gThumb build, tags and comments
    # live in embedded XMP, .comments sidecars, or both. Sidecar values fill
    # in whatever the embedded XMP is missing.
    sidecar = sidecars.read_sidecar(p)
    if sidecar:
        for key, sidecar_key in (("title", "caption"), ("description", "note"),
                                 ("location", "place")):
            if info.get(key) in (None, "") and sidecar[sidecar_key]:
                info[key] = sidecar[sidecar_key]
        if info.get("rating") in (None, 0) and sidecar["rating"]:
            info["rating"] = sidecar["rating"]
        info["tags"] = list(dict.fromkeys(
            list(info.get("tags") or []) + sidecar["categories"]
        ))
    info["path"] = str(p)
    info["has_comfyui_workflow"] = comfyui.has_workflow(p)
    return _ok(info)


@mcp.tool()
def set_rating(path: str, rating: int) -> str:
    """Set the gThumb star rating (0-5) of an image: embedded XMP (exiftool)
    and the comment sidecar the gThumb UI reads. This modifies the file."""
    p = _existing_file(path)
    applied = metadata.set_rating(p, rating)
    sidecars.update_sidecar(p, rating=applied)
    return _ok({"path": str(p), "rating": applied})


@mcp.tool()
def set_tags(path: str, tags: list[str], replace: bool = True) -> str:
    """Set the gThumb tags of an image. Set replace=false to append instead.
    Writes both the gThumb comment sidecar (.comments/<name>.xml — what the
    gThumb UI reads) and embedded metadata (exiftool). Replace mode clears
    ALL embedded keyword stores (XMP dc:Subject, Iptc4xmpCore:Keywords and
    IPTC:Keywords) before writing, so no ghost tags survive. This modifies
    the files."""
    p = _existing_file(path)
    requested = [str(t).strip() for t in tags if str(t).strip()]
    sidecar_state = sidecars.read_sidecar(p)

    if replace:
        final = list(dict.fromkeys(requested))
        write_iptc = True
    elif not requested:
        # Append with nothing to add: pure no-op.
        return _ok({"path": str(p),
                    "tags": list(dict.fromkeys(
                        sidecars.read_categories(p) + metadata.get_tags(p))),
                    "replaced": False,
                    "sidecar": str(sidecars.sidecar_path(p))})
    else:
        # Append: union of what all stores already have.
        existing_embedded = metadata.read_metadata(p)
        write_iptc = "Keywords" in existing_embedded
        existing = list(dict.fromkeys(
            sidecars.read_categories(p) + metadata.get_tags(p)
        ))
        final = list(dict.fromkeys(existing + requested))

    sidecars.write_sidecar_tags(p, final, replace=True)
    # restore= re-applies rating/title/description/location that the XMP
    # wipe removes; write_iptc only creates an IPTC block where one existed.
    metadata.replace_keywords(p, final, restore=sidecar_state,
                              write_iptc=write_iptc)
    for tag in final:
        tags_module.create_tag(tag)  # register new tags in tags.xml
    return _ok({"path": str(p), "tags": final, "replaced": replace,
                "sidecar": str(sidecars.sidecar_path(p))})


@mcp.tool()
def set_comment(path: str, title: str | None = None, description: str | None = None,
                location: str | None = None) -> str:
    """Set an image's title, description (comment) and/or location: written as
    embedded XMP (exiftool) and to the comment sidecar the gThumb UI reads
    (sidecar caption/note/place). Only non-None fields are changed."""
    p = _existing_file(path)
    metadata.set_comment(p, title=title, description=description, location=location)
    sidecars.update_sidecar(p, caption=title, note=description, place=location)
    return _ok({"path": str(p), "title": title, "description": description, "location": location})


# ---------------------------------------------------------------- search & view

def _all_tags_for(path: Path, info: dict | None = None) -> set[str]:
    """Union of embedded XMP tags and gThumb comment-sidecar categories.

    Depending on the gThumb build, tags live in embedded XMP (exiv2-linked
    builds) or in .comments sidecar XMLs (Debian builds) — read both.
    """
    tags = set((info or {}).get("tags") or [])
    tags.update(sidecars.read_categories(path))
    return tags


@mcp.tool()
def get_comfyui_workflow(path: str, include_prompt: bool = True) -> str:
    """Get the ComfyUI workflow embedded in an image (PNG text chunks), if any:
    the full UI graph, plus a summary (node count, models, positive/negative prompts).
    Set include_prompt=true to also return the API-format 'prompt' graph."""
    p = _existing_file(path)
    return _ok(comfyui.extract(p, include_prompt=include_prompt))


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
            file_tags = _all_tags_for(path, info)
            if min_rating is not None and (info.get("rating") or 0) < min_rating:
                continue
            if tag and tag not in file_tags:
                continue
            matches.append({"path": str(path), "rating": info.get("rating"),
                            "tags": sorted(file_tags), "date_taken": info.get("date_taken")})
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
