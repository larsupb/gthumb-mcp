"""Tests for catalog (.catalog/.search) parsing and writing."""

from __future__ import annotations

import pytest

from gthumb_mcp import catalogs

from .conftest import make_image, write_catalog


def test_list_and_read_catalog(gthumb_home):
    img = make_image(gthumb_home["data"] / "pics" / "a.jpg")
    write_catalog(gthumb_home["data"], "Favorites.catalog", "Favorites", [img])

    listed = catalogs.list_catalogs()
    assert len(listed) == 1
    assert listed[0]["name"] == "Favorites"
    assert listed[0]["type"] == "catalog"
    assert listed[0]["file_count"] == 1

    files = catalogs.read_catalog_files("Favorites")
    assert files == [img.resolve()]


def test_create_add_remove_roundtrip(gthumb_home):
    catalogs.create_catalog("Trips")
    img1 = make_image(gthumb_home["data"] / "pics" / "one.jpg")
    img2 = make_image(gthumb_home["data"] / "pics" / "two.jpg")

    assert catalogs.add_to_catalog("Trips", [img1, img2]) == 2
    # Duplicate add is skipped.
    assert catalogs.add_to_catalog("Trips", [img1]) == 0
    assert catalogs.read_catalog_files("Trips") == [img1.resolve(), img2.resolve()]

    assert catalogs.remove_from_catalog("Trips", [img1]) == 1
    assert catalogs.read_catalog_files("Trips") == [img2.resolve()]


def test_create_in_subdirectory(gthumb_home):
    catalogs.create_catalog("Random/Trips")
    path = gthumb_home["data"] / "catalogs" / "Random" / "Trips.catalog"
    assert path.is_file()
    listed = catalogs.list_catalogs()
    assert listed[0]["relative"] == "Random/Trips.catalog"
