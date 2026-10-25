"""Tests for tags.xml handling."""

from __future__ import annotations

import pytest

from gthumb_mcp import tags

from .conftest import write_tags_xml


def test_list_tags_empty(gthumb_home):
    assert tags.list_tags() == []


def test_create_list_rename_delete(gthumb_home):
    write_tags_xml(gthumb_home["config"], ["Family", "Travel"])

    assert tags.list_tags() == ["Family", "Travel"]

    tags.create_tag("Beach")
    tags.create_tag("Family")  # idempotent
    assert tags.list_tags() == ["Family", "Travel", "Beach"]

    tags.rename_tag("Travel", "Vacation")
    assert tags.list_tags() == ["Family", "Vacation", "Beach"]

    tags.delete_tag("Beach")
    assert tags.list_tags() == ["Family", "Vacation"]

    with pytest.raises(tags.TagError):
        tags.delete_tag("Nonexistent")


def test_delete_tag_removes_snapshot(gthumb_home):
    write_tags_xml(gthumb_home["config"], ["Family"])
    snapshot = tags.tags_search_file("Family")
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_text("<search/>")

    tags.delete_tag("Family")
    assert not snapshot.exists()
