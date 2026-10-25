# gthumb-mcp

An MCP (Model Context Protocol) server that exposes a [gThumb](https://wiki.gnome.org/Apps/Gthumb)
image library to AI agents: catalogs, tags, star ratings, comments, thumbnails and search.

It works directly with gThumb's own data — no database, no duplication:

| Data | Location | Access |
|---|---|---|
| Catalogs & saved searches | `~/.local/share/gthumb/catalogs/` (`*.catalog`, `*.search`) | read + write |
| Tag definitions | `~/.config/gthumb/tags.xml` | read + write |
| Per-tag search snapshots | `~/.local/share/gthumb/catalogs/Tags/*.search` | read |
| Ratings, tags, title, comment | embedded XMP inside the image files | read + write via `exiftool` |
| Tags (comment sidecars) | `<folder>/.comments/<image>.xml` | read + write |
| Thumbnails | `~/.cache/thumbnails` (freedesktop spec) | read + write |

gThumb picks up everything this server writes on its next refresh — and vice versa.

## Requirements

- Linux with gThumb 3.12 (other 3.x versions likely work)
- Python 3.12+ and [uv](https://docs.astral.sh/uv/)
- **exiftool** — `sudo apt install libimage-exiftool-perl`
  (everything except the metadata tools works without it)

## Install

```bash
uv sync
```

## Run

```bash
uv run gthumb-mcp        # MCP stdio server
```

## Register with an MCP client

opencode (`~/.config/opencode/opencode.json`):

```json
{
  "mcp": {
    "gthumb": {
      "type": "local",
      "command": [
        "uv", "--directory", "/absolute/path/to/gthumb-mcp", "run", "gthumb-mcp"
      ],
      "enabled": true
    }
  }
}
```

Claude Desktop (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "gthumb": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/gthumb-mcp", "run", "gthumb-mcp"]
    }
  }
}
```

## Tools

**Catalogs**

| Tool | Description |
|---|---|
| `list_catalogs()` | All catalogs and saved searches with item counts |
| `get_catalog(name)` | The files stored in a catalog |
| `create_catalog(name)` | New, empty catalog (supports subfolders, e.g. `Random/Trips`) |
| `delete_catalog(name)` | Delete a catalog or saved-search file |
| `add_to_catalog(name, paths)` | Add images (duplicates skipped) |
| `remove_from_catalog(name, paths)` | Remove images |

**Tags**

| Tool | Description |
|---|---|
| `list_tags()` | All tags known to gThumb |
| `create_tag(tag)` / `delete_tag(tag)` / `rename_tag(old, new)` | Manage tag definitions |
| `find_images_by_tags(tags, match, directory?)` | Multi-tag search: `match="AND"` (all tags) or `match="OR"` (any tag); snapshot-based by default, or a live XMP scan of a directory. OR results include which tags matched |

**Image metadata** (embedded XMP, same fields gThumb writes)

| Tool | Description |
|---|---|
| `get_image_info(path)` | Dimensions, format, camera, date, GPS, title, description, tags, rating |
| `set_rating(path, 0..5)` | Star rating — embedded XMP + comment sidecar |
| `set_tags(path, tags, replace)` | Set (`replace=true`) or append (`replace=false`) tags — replace mode clears *all* embedded keyword stores (XMP dc:Subject, Iptc4xmpCore:Keywords, IPTC:Keywords) before writing, so no ghost tags survive; written to the comment sidecar *and* embedded metadata |
| `set_comment(path, title?, description?, location?)` | Title/comment/location — written to both the comment sidecar and embedded XMP; only non-`None` fields change |

**Search & view**

| Tool | Description |
|---|---|
| `find_images(directory, name_pattern?, tag?, min_rating?, newer_than?, older_than?, limit)` | Filter by filename glob, tag, rating and modification date |
| `get_thumbnail(path, size)` | From the shared thumbnail cache (`normal` 128 px / `large` 512 px), generated if missing |
| `get_image(path, max_size)` | Image content, downscaled, for model viewing |
| `get_comfyui_workflow(path, include_prompt?)` | ComfyUI workflow embedded in an image, with a summary (see below) |

**Convenience**

| Tool | Description |
|---|---|
| `open_in_gthumb(path)` | Open a file or directory in the gThumb desktop app |

## ComfyUI workflow delivery

Images saved by ComfyUI embed their generation graph as PNG text chunks
(`workflow`: the UI graph, and `prompt`: the API-format graph). The
`get_comfyui_workflow` tool returns both as parsed JSON plus a best-effort
summary, so an agent can understand — and even recreate — how an image was
generated:

```json
{
  "has_workflow": true,
  "node_count": 14,
  "models": ["SD1.5/Characters/character-lora-v50.safetensors",
             "SD1.5/Improve/add_detail.safetensors"],
  "positive_prompt": "a photo of a …",
  "negative_prompt": "watermark",
  "workflow": { "…": "full UI graph, drag-and-droppable back into ComfyUI" },
  "prompt": { "…": "API-format graph (with include_prompt=true)" }
}
```

`get_image_info` includes a `has_comfyui_workflow` flag for cheap availability
checks. JPEGs saved by ComfyUI (workflow embedded in the EXIF UserComment)
are supported as a fallback. Prompt extraction is best-effort — third-party
node collections wire samplers differently. When the sampler's prompt links
cannot be resolved (e.g. rgthree "Anything Everywhere" / "Prompts Everywhere"
wiring), the summary falls back to the first two text-encoding nodes by node
id and, when present, to the API-format `prompt` chunk. The complete graph
JSON is always delivered regardless.

## Example session

> **User:** Show me my catalogs, then the images tagged *Beach*.
>
> ```json
> {"tool": "list_catalogs"}
> → [{"name": "Favorites", "type": "catalog", "file_count": 42}, …]
>
> {"tool": "find_images_by_tag", "arguments": {"tag": "Beach"}}
> → {"source": "snapshot", "count": 118, "files": ["/home/user/Pictures/2024-07/beach_001.jpg", …]}
> ```
>
> **User:** Rate the first one 5 stars.
>
> ```json
> {"tool": "set_rating", "arguments": {"path": "/home/user/Pictures/2024-07/beach_001.jpg", "rating": 5}}
> → {"path": "/home/user/Pictures/2024-07/beach_001.jpg", "rating": 5}
> ```

## How it works

- **Catalogs** are parsed and rewritten as XML in exactly gThumb's format. All writes
  are atomic (temp file + `os.replace`), so a crash can't corrupt gThumb's files.
- **Tags, titles, comments and ratings** are read/written as embedded XMP via
  exiftool *and* as gThumb comment sidecars (`<folder>/.comments/<image>.xml`).
  Which store the gThumb UI uses depends on the build: exiv2-linked builds read
  embedded XMP, while Debian's gThumb 3.12 package has no exiv2 linkage and
  uses sidecars exclusively (regardless of the store-metadata-in-files
  setting) — so both are kept in sync:

  | gThumb field | XMP field | Sidecar element |
  |---|---|---|
  | Title | `XMP-dc:Title` | `<caption>` |
  | Description / comment | `XMP-dc:Description` | `<note>` |
  | Tags | `XMP-dc:Subject` (list) | `<categories><category value=…/>` |
  | Rating | `XMP-xmp:Rating` (integer 0–5) | `<rating value="N"/>` |

  Tag searches and `get_image_info` read both stores and merge results.
  Note the exiftool list semantics used here: plain `=` assignments *replace* the
  whole tag list, `+=` appends, and an empty list with `replace=true` clears it.
- **Legacy keyword stores are cleared, not just dc:subject.** Files tagged by
  other tools often carry keywords in additional embedded stores — the IPTC IIM
  `Keywords` block and the XMP `Iptc4xmpCore:Keywords` property (read-only in
  exiftool, so a plain tag rewrite can never remove it). `set_tags` with
  `replace=true` therefore wipes every keyword representation with
  `-xmp:all= -iptc:all=` first and rebuilds from scratch (re-applying rating,
  title, description and location afterwards; PNG text chunks such as embedded
  ComfyUI workflows are unaffected). Append mode unions all existing stores
  and only creates an IPTC block where one already existed. `get_image_info`
  and tag searches merge all embedded keyword stores, so stale ghosts can
  neither hide nor leak into results.
- **Thumbnails** follow the [freedesktop thumbnailer spec](https://specifications.freedesktop.org/thumbnail-spec/latest/):
  the cache key is the MD5 of the image's `file://` URI, and generated thumbnails carry
  the spec's `Thumb::URI` / `Thumb::MTime` annotations. gThumb shares this cache, so
  thumbnails are generated at most once, no matter who requests them.
- `find_images_by_tag` reads gThumb's cached per-tag snapshot by default (fast,
  updated whenever gThumb runs a tag search). Pass a `directory` to instead scan the
  embedded XMP of files live — slower, but reflects the current file contents.
- If gThumb is running while catalogs change externally, refresh/reopen its
  library view to see the updates.

## Configuration

| Environment variable | Default | Purpose |
|---|---|---|
| `GTHUMB_CONFIG_DIR` | `~/.config/gthumb` | tags.xml location |
| `GTHUMB_DATA_DIR` | `~/.local/share/gthumb` | catalogs location |
| `XDG_CACHE_HOME` | `~/.cache` | thumbnail cache root |

These redirects are mainly useful for testing; no gThumb installation is touched
by the test suite.

## Development

```bash
uv sync
uv run pytest        # 13 tests; exiftool-dependent tests skip if exiftool is missing
```

Project layout:

```
src/gthumb_mcp/
├── server.py        # FastMCP-style server: 20 tools, stdio transport
├── paths.py         # gThumb data locations (env-overridable)
├── catalogs.py      # .catalog / .search XML parsing and atomic writing
├── tags.py          # tags.xml and per-tag search snapshots
├── metadata.py      # exiftool wrapper for embedded XMP
├── sidecars.py      # .comments comment sidecars (UI-visible tags)
├── comfyui.py       # embedded ComfyUI workflow extraction
├── thumbnails.py    # freedesktop thumbnail cache
└── util.py          # file:// URI conversion, atomic writes
```

## License

[MIT](LICENSE)
