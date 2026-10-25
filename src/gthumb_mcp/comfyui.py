"""Extract embedded ComfyUI workflow data from image files.

ComfyUI-saved PNGs contain two text chunks:

- ``workflow``: the full UI-format graph (nodes, links, positions) — the part
  that can be dragged back onto the ComfyUI canvas or loaded via "Load".
- ``prompt``: the API-format prompt (the flattened node graph that was run).

JPEGs saved by ComfyUI embed the same data inside the EXIF UserComment
(``prompt: {...} workflow: {...}``), which is used as a fallback here.

Everything in this module is best-effort: images are arbitrary files, so no
summary extraction should ever break the basic "deliver the JSON" purpose.
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image as PILImage

WORKFLOW_CHUNK = "workflow"
PROMPT_CHUNK = "prompt"

# EXIF tag for UserComment (0x9286); used by ComfyUI's JPEG saves.
EXIF_USER_COMMENT = 0x9286

MODEL_EXTENSIONS = (".safetensors", ".sft", ".ckpt", ".pt", ".bin", ".gguf")


class ComfyUIError(Exception):
    pass


def _parse_json_object(raw) -> dict | None:
    if not isinstance(raw, str) or not raw.lstrip().startswith("{"):
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _balanced_json(text: str, start: int) -> tuple[str | None, int]:
    """Return the balanced {...} JSON string starting at/after `start`."""
    depth = 0
    in_str = False
    escaped = False
    begin = None
    for i in range(start, len(text)):
        c = text[i]
        if escaped:
            escaped = False
        elif c == "\\":
            escaped = True
        elif c == '"':
            in_str = not in_str
        elif not in_str:
            if c == "{":
                depth += 1
                if begin is None:
                    begin = i
            elif c == "}":
                depth -= 1
                if depth == 0 and begin is not None:
                    return text[begin : i + 1], i + 1
    return None, start


def _from_user_comment(comment: str) -> dict | None:
    """Best-effort parse of ComfyUI's JPEG UserComment (prompt/workflow JSONs)."""
    lowered = comment.lower()

    def find_json(key: str) -> dict | None:
        idx = lowered.find(key)
        while idx != -1:
            raw, resume = _balanced_json(comment, idx)
            if raw is None:
                return None
            data = _parse_json_object(raw)
            if data is not None:
                return data
            idx = lowered.find(key, resume)
        return None

    return find_json(WORKFLOW_CHUNK)


def _clean_user_comment(raw) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="ignore")
    return raw


def _nodes_of(graph: dict) -> list | dict | None:
    """UI format has a 'nodes' list; API format is a dict of node ids."""
    if isinstance(graph.get("nodes"), list):
        return graph["nodes"]
    return None


def _summarize_ui(graph: dict) -> dict:
    nodes = graph.get("nodes") or []
    models: list[str] = []
    for node in nodes:
        for value in node.get("widgets_values") or []:
            if isinstance(value, str) and value.lower().endswith(MODEL_EXTENSIONS):
                if value not in models:
                    models.append(value)
    positive = negative = None
    sampler = next((n for n in nodes if "KSampler" in str(n.get("type", ""))), None)

    # Strategy 1: follow the positive/negative input links from the sampler.
    if sampler is not None:
        named_inputs = {i.get("name"): i for i in (sampler.get("inputs") or [])}
        if "positive" in named_inputs and positive is None:
            positive = _resolve_ui_prompt(graph, sampler, "positive")
        if "negative" in named_inputs and negative is None:
            negative = _resolve_ui_prompt(graph, sampler, "negative")

    # Strategy 2: older ComfyUI writes positive/negative node ids as the last
    # two widget values of the sampler.
    if (positive is None or negative is None) and sampler is not None:
        try:
            widget_ids = [v for v in (sampler.get("widgets_values") or [])
                          if isinstance(v, (int, str))]
            if len(widget_ids) >= 2:
                by_id = {str(node.get("id")): node for node in nodes}
                pos_vals = (by_id.get(str(widget_ids[-2])) or {}).get("widgets_values") or []
                neg_vals = (by_id.get(str(widget_ids[-1])) or {}).get("widgets_values") or []
                if positive is None and pos_vals and isinstance(pos_vals[0], str) and len(pos_vals[0]) > 1:
                    positive = pos_vals[0]
                if negative is None and neg_vals and isinstance(neg_vals[0], str) and len(neg_vals[0]) > 1:
                    negative = neg_vals[0]
        except Exception:  # noqa: BLE001 - each strategy is best-effort
            pass

    # Strategy 3 (last resort; covers rgthree "Anything Everywhere" wiring,
    # where samplers carry no resolvable prompt links): the first two text-
    # encoding nodes, in graph order.
    if positive is None:
        positive = _first_text_widget(nodes)
    if negative is None:
        negative = _first_text_widget(nodes, skip=positive)
    return {"node_count": len(nodes), "models": models,
            "positive_prompt": positive, "negative_prompt": negative}


def _resolve_ui_prompt(graph: dict, sampler: dict, link_name: str):
    """Follow a named input link from the sampler to the source node's text widget."""
    try:
        links = {l[0]: l for l in graph.get("links") or []}
        inp = next(i for i in (sampler.get("inputs") or []) if i.get("name") == link_name)
        link = links.get(inp.get("link"))
        if link is None:
            return None
        src = next(n for n in graph.get("nodes") or [] if n.get("id") == link[1])
        strs = [v for v in (src.get("widgets_values") or []) if isinstance(v, str)]
        return max(strs, key=len) if strs else None
    except (StopIteration, KeyError, TypeError):
        return None


def _first_text_widget(nodes, skip=None):
    """First text-looking widget among text-encoding nodes, in node-id order.

    ComfyUI convention is that the positive prompt node is created before the
    negative one, so sorting by node id gives positive-then-negative even when
    the node array lists them the other way around.
    """
    encoders = sorted(
        (n for n in nodes if "CLIPTextEncode" in str(n.get("type", ""))),
        key=lambda n: _node_id_sort((str(n.get("id")), n)),
    )
    for node in encoders:
        vals = [v for v in (node.get("widgets_values") or []) if isinstance(v, str)]
        for v in vals:
            if v != skip and len(v) > 1:
                return v
    return None


def _summarize_api(graph: dict) -> dict:
    models: list[str] = []
    for node in graph.values():
        for value in (node.get("inputs") or {}).values():
            if isinstance(value, str) and value.lower().endswith(MODEL_EXTENSIONS):
                if value not in models:
                    models.append(value)
    positive = negative = None

    # Strategy 1: a sampler with resolvable positive/negative node references.
    samplers = [n for n in graph.values()
                if "KSampler" in str(n.get("class_type", ""))
                and isinstance(n.get("inputs"), dict)
                and "positive" in n["inputs"] and "negative" in n["inputs"]]
    for sampler in samplers:
        if positive is None:
            positive = _api_text(graph, (sampler["inputs"].get("positive") or [None])[0])
        if negative is None:
            negative = _api_text(graph, (sampler["inputs"].get("negative") or [None])[0])

    # Strategy 2 (covers e.g. rgthree "Anything Everywhere" wiring, where the
    # sampler carries no prompt references): the first two text-encoding nodes
    # in node-id order.
    if positive is None or negative is None:
        encoders = [node for _, node in sorted(graph.items(), key=_node_id_sort)
                    if "CLIPTextEncode" in str(node.get("class_type", ""))]
        texts = [(node.get("inputs") or {}).get("text") for node in encoders]
        texts = [t for t in texts if isinstance(t, str) and len(t) > 1]
        if positive is None and texts:
            positive = texts[0]
        if negative is None and len(texts) > 1:
            negative = texts[1]
    return {"node_count": len(graph), "models": models,
            "positive_prompt": positive, "negative_prompt": negative}


def _api_text(graph, ref):
    try:
        node = graph.get(str(ref[0])) or {}
        return (node.get("inputs") or {}).get("text")
    except (KeyError, IndexError, TypeError):
        return None


def _node_id_sort(item):
    node_id = str(item[0])
    return (0, int(node_id), "") if node_id.isdigit() else (1, 0, node_id)


def summarize(graph: dict) -> dict:
    """Extract a small, agent-friendly summary from a workflow graph."""
    summary = {"node_count": None, "models": [],
               "positive_prompt": None, "negative_prompt": None}
    try:
        nodes = _nodes_of(graph)
        summary.update(_summarize_ui(graph) if nodes is not None else _summarize_api(graph))
    except Exception:  # noqa: BLE001 - summary is best-effort only
        pass
    return summary


def has_workflow(path: Path) -> bool:
    """Cheap check whether a file embeds a ComfyUI workflow."""
    try:
        with PILImage.open(path) as im:
            text = getattr(im, "text", {}) or {}
            if WORKFLOW_CHUNK in text:
                return True
            exif = im.getexif()
            comment = exif.get(EXIF_USER_COMMENT) if exif else None
            comment = _clean_user_comment(comment)
            return WORKFLOW_CHUNK in comment.lower() if comment else False
    except Exception:  # noqa: BLE001 - unreadable/foreign files simply have none
        return False


def extract(path: Path, include_prompt: bool = True) -> dict:
    """Return the embedded ComfyUI workflow (and prompt) for an image."""
    workflow = prompt = None
    try:
        with PILImage.open(path) as im:
            text = getattr(im, "text", {}) or {}
            workflow = _parse_json_object(text.get(WORKFLOW_CHUNK))
            prompt = _parse_json_object(text.get(PROMPT_CHUNK))
            user_comment = _clean_user_comment(
                im.getexif().get(EXIF_USER_COMMENT) if im.getexif() else None
            )
    except PILImage.DecompressionBombError:
        raise  # let Pillow's safety limit surface as-is
    except Exception as exc:  # noqa: BLE001 - unreadable images have no workflow
        raise ComfyUIError(f"Cannot read image: {exc}") from exc

    if workflow is None and user_comment:
        workflow = _from_user_comment(user_comment)

    if workflow is None:
        raise ComfyUIError(
            f"No embedded ComfyUI workflow found in {path.name} "
            "(not saved by ComfyUI, or stripped)"
        )

    summary = summarize(workflow)
    if prompt is not None:
        # The API chunk is the flattened, executed graph — the most reliable
        # source when the UI graph hides prompt wiring (e.g. rgthree
        # "Anything Everywhere" nodes). Fill only what the UI summary missed.
        api_summary = summarize(prompt)
        for key in ("positive_prompt", "negative_prompt"):
            if summary[key] is None:
                summary[key] = api_summary[key]

    result = {
        "has_workflow": True,
        "file": str(path),
        **summary,
        "workflow": workflow,
    }
    if include_prompt:
        result["prompt"] = prompt
    return result
