"""Locate gThumb's data files (catalogs, tags, thumbnails).

All lookups are functions (not constants) so that test environments can
redirect locations via environment variables at call time.
"""

from __future__ import annotations

import os
from pathlib import Path

GTHUMB_CONFIG_DIR = "GTHUMB_CONFIG_DIR"
GTHUMB_DATA_DIR = "GTHUMB_DATA_DIR"
XDG_CACHE_HOME = "XDG_CACHE_HOME"


def gthumb_config_dir() -> Path:
    """Directory holding tags.xml and other gThumb settings."""
    override = os.environ.get(GTHUMB_CONFIG_DIR)
    if override:
        return Path(override)
    return Path(os.environ.get("HOME", str(Path.home()))) / ".config" / "gthumb"


def gthumb_data_dir() -> Path:
    """Directory holding catalogs and saved searches."""
    override = os.environ.get(GTHUMB_DATA_DIR)
    if override:
        return Path(override)
    return Path(os.environ.get("HOME", str(Path.home()))) / ".local" / "share" / "gthumb"


def catalogs_dir() -> Path:
    return gthumb_data_dir() / "catalogs"


def tags_file() -> Path:
    return gthumb_config_dir() / "tags.xml"


def thumbnail_cache_dir() -> Path:
    """freedesktop.org shared thumbnail cache (~/.cache/thumbnails)."""
    override = os.environ.get(XDG_CACHE_HOME)
    base = Path(override) if override else Path.home() / ".cache"
    return base / "thumbnails"
