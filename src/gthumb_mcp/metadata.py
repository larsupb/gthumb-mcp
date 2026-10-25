"""Read and write embedded image metadata via exiftool.

gThumb 3.12 stores metadata inside the image files by default
(org.gnome.gthumb.general store-metadata-in-files=true), using these fields:

- Title        -> XMP-dc:Title
- Description  -> XMP-dc:Description
- Tags         -> XMP-dc:Subject (list)
- Rating       -> XMP-xmp:Rating (integer 0-5)
- Location     -> XMP-iptcCore:Location

exiftool reads and writes exactly these fields, so anything this server
writes is picked up by gThumb the next time the file is (re)loaded.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

RATING_MIN, RATING_MAX = 0, 5

READ_ARGS = [
    "-ImageWidth",
    "-ImageHeight",
    "-FileSize#",
    "-FileType",
    "-Model",
    "-LensModel",
    "-DateTimeOriginal",
    "-CreateDate",
    "-GPSLatitude",
    "-GPSLongitude",
    "-XMP:Rating",
    "-XMP-dc:Title",
    "-XMP-dc:Description",
    "-XMP-dc:Subject",
    "-XMP-iptcCore:Location",
    # Alternate keyword stores some tools write; merged into the tag list so
    # ghost tags can't hide from searches and audits.
    "-IPTC:Keywords",
    "-Iptc4xmpCore:Keywords",
]

IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff",
    ".heic", ".heif", ".avif", ".jxl", ".cr2", ".cr3", ".nef", ".arw",
    ".orf", ".raf", ".rw2", ".dng",
}


class ExifToolError(Exception):
    pass


def _run(args: list[str], timeout: float = 60.0) -> str:
    exe = shutil.which("exiftool")
    if exe is None:
        raise ExifToolError(
            "exiftool is not installed. Install it with: sudo apt install libimage-exiftool-perl"
        )
    try:
        proc = subprocess.run(
            [exe, *args], capture_output=True, text=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise ExifToolError(f"exiftool timed out after {timeout}s") from exc
    if proc.returncode != 0:
        raise ExifToolError(f"exiftool failed: {proc.stderr.strip() or proc.stdout.strip()}")
    return proc.stdout


def read_metadata_batch(paths: list[Path]) -> list[dict]:
    """Read metadata for several files with one exiftool invocation."""
    if not paths:
        return []
    out = _run(["-j", "-n", "-charset", "utf8", *READ_ARGS, *[str(p) for p in paths]])
    return json.loads(out) if out.strip() else []


def read_metadata(path: Path) -> dict:
    """Read metadata for a single file. Returns {} if the file has none."""
    result = read_metadata_batch([path])
    return result[0] if result else {}


def _one(raw: dict) -> dict:
    """Normalize one exiftool JSON record into a stable schema."""
    def num(key: str) -> int | float | None:
        value = raw.get(key)
        if value is None:
            return None
        try:
            return int(value) if float(value).is_integer() else float(value)
        except (TypeError, ValueError):
            return None

    # All embedded keyword stores, merged (deduplicated, order-preserving):
    # XMP dc:Subject, XMP Iptc4xmpCore:Keywords (read-only ghost store some
    # tools leave behind) and the IPTC IIM Keywords block.
    tags: list[str] = []
    for key in ("Subject", "Iptc4xmpCore:Keywords", "Keywords"):
        value = raw.get(key)
        if value is None:
            continue
        for tag in value if isinstance(value, list) else [value]:
            if tag and tag not in tags:
                tags.append(tag)

    rating = num("Rating")
    return {
        "width": num("ImageWidth"),
        "height": num("ImageHeight"),
        "file_type": raw.get("FileType"),
        "file_size": num("FileSize"),
        "camera": raw.get("Model"),
        "lens": raw.get("LensModel"),
        "date_taken": raw.get("DateTimeOriginal") or raw.get("CreateDate"),
        "rating": rating,
        "title": raw.get("Title"),
        "description": raw.get("Description"),
        "location": raw.get("Location"),
        "tags": tags,
        "gps": (
            {"lat": raw["GPSLatitude"], "lon": raw["GPSLongitude"]}
            if raw.get("GPSLatitude") is not None and raw.get("GPSLongitude") is not None
            else None
        ),
    }


def get_image_info(path: Path) -> dict:
    return _one(read_metadata(path))


def get_tags(path: Path) -> list[str]:
    """All embedded keywords of an image: XMP dc:Subject, XMP
    Iptc4xmpCore:Keywords and the IPTC IIM Keywords block, merged."""
    return _one(read_metadata(path))["tags"]


def replace_keywords(
    path: Path, tags: list[str], restore: dict | None = None, write_iptc: bool = True
) -> list[str]:
    """Replace ALL embedded keyword stores with `tags`: XMP dc:Subject, XMP
    Iptc4xmpCore:Keywords (a read-only ghost store some tools leave behind —
    the only way to clear it is wiping the whole XMP) and the IPTC IIM
    Keywords block.

    `restore` (gThumb sidecar state from sidecars.read_sidecar) re-applies the
    non-keyword XMP fields this server manages after the wipe: rating, title,
    description, location. ComfyUI PNG tEXt chunks (workflow/prompt) are plain
    text chunks and are NOT touched by -xmp:all= / -iptc:all=.
    """
    # Wipe every keyword representation first (also removes ghost stores).
    _run(["-overwrite_original", "-xmp:all=", "-iptc:all=", str(path)])

    args = ["-overwrite_original"]
    if restore:
        if restore.get("rating"):
            args.append(f"-XMP:Rating={restore['rating']}")
        if restore.get("caption"):
            args.append(f"-XMP-dc:Title={restore['caption']}")
        if restore.get("note"):
            args.append(f"-XMP-dc:Description={restore['note']}")
        if restore.get("place"):
            args.append(f"-XMP-iptcCore:Location={restore['place']}")
    for tag in tags:
        # '+=' after the wipe: starts from an empty list, so this accumulates
        # exactly `tags` (a plain '=' after a group clear behaves
        # unpredictably, and '-=' combined with '=' in one command is worse).
        args.append(f"-XMP-dc:Subject+={tag}")
    if write_iptc:
        for tag in tags:
            args.append(f"-IPTC:Keywords+={tag}")
    if len(args) > 1:  # nothing to re-write for empty tag lists
        _run([*args, str(path)])
    return tags


def set_rating(path: Path, rating: int) -> int:
    rating = max(RATING_MIN, min(RATING_MAX, int(rating)))
    _run(["-overwrite_original", f"-XMP:Rating={rating}", str(path)])
    return rating


def set_comment(path: Path, title: str | None = None, description: str | None = None,
                location: str | None = None) -> None:
    args = ["-overwrite_original"]
    if title is not None:
        args.append(f"-XMP-dc:Title={title}")
    if description is not None:
        args.append(f"-XMP-dc:Description={description}")
    if location is not None:
        args.append(f"-XMP-iptcCore:Location={location}")
    if len(args) > 1:
        _run([*args, str(path)])


def iter_image_files(directory: Path, recursive: bool = True) -> list[Path]:
    directory = Path(directory)
    it = directory.rglob("*") if recursive else directory.glob("*")
    return sorted(p for p in it if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS)
