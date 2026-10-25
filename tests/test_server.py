"""Smoke tests that the MCP server registers all tools correctly."""

from __future__ import annotations

import asyncio
import json

from gthumb_mcp import server

EXPECTED_TOOLS = {
    "list_catalogs", "get_catalog", "create_catalog", "delete_catalog",
    "add_to_catalog", "remove_from_catalog",
    "list_tags", "create_tag", "delete_tag", "rename_tag", "find_images_by_tag",
    "get_image_info", "set_rating", "set_tags", "set_comment",
    "find_images", "get_thumbnail", "get_image", "open_in_gthumb",
}


def test_all_tools_registered():
    tools = asyncio.run(server.mcp.list_tools())
    names = {t.name for t in tools}
    assert EXPECTED_TOOLS <= names


def test_server_tool_end_to_end(gthumb_home):
    """Exercise catalog + tag tools through the MCP function layer."""
    from .conftest import make_image

    img = make_image(gthumb_home["data"] / "img" / "pic.png")

    assert json.loads(server.create_catalog("Test"))["created"]
    assert json.loads(server.add_to_catalog("Test", [str(img)]))["added"] == 1

    cat = json.loads(server.get_catalog("Test"))
    assert cat["files"] == [str(img.resolve())]

    assert json.loads(server.create_tag("TestTag"))
    assert "TestTag" in json.loads(server.list_tags())["tags"]

    found = json.loads(server.find_images(str(gthumb_home["data"]), name_pattern="pic.png"))
    assert found["count"] == 1
    assert found["images"][0]["path"] == str(img.resolve())
