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

    rating = num("Rating")
    tags = raw.get("Subject") or []
    if isinstance(tags, str):
        tags = [tags]
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


def set_rating(path: Path, rating: int) -> int:
    rating = max(RATING_MIN, min(RATING_MAX, int(rating)))
    _run(["-overwrite_original", f"-XMP:Rating={rating}", str(path)])
    return rating


def set_tags(path: Path, tags: list[str], replace: bool = True) -> list[str]:
    tags = [str(t).strip() for t in tags if str(t).strip()]
    if not tags:
        if replace:  # empty list + replace -> clear the tag list entirely
            _run(["-overwrite_original", "-XMP-dc:Subject-=", str(path)])
        return []
    if replace:
        # Plain '=' assignments REPLACE the stored list; multiple '=' args
        # accumulate into the new list. Do NOT combine with '-=' in the same
        # command: that turns the subsequent '=' into an append instead.
        args = ["-overwrite_original"] + [f"-XMP-dc:Subject={t}" for t in tags]
    else:
        args = ["-overwrite_original"] + [f"-XMP-dc:Subject+={t}" for t in tags]
    _run([*args, str(path)])
    return tags


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
