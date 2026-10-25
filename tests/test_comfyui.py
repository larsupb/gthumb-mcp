"""Tests for ComfyUI workflow extraction."""

from __future__ import annotations

import json

import pytest
from PIL import Image as PILImage
from PIL.PngImagePlugin import PngInfo

from gthumb_mcp import comfyui

from .conftest import make_image

UI_WORKFLOW = {
    "nodes": [
        {"id": 4, "type": "CheckpointLoaderSimple", "widgets_values": ["dreamshaper.safetensors"]},
        {"id": 6, "type": "CLIPTextEncode", "widgets_values": ["a sunny beach"]},
        {"id": 7, "type": "CLIPTextEncode", "widgets_values": ["watermark"]},
        {"id": 9, "type": "SaveImage", "widgets_values": ["out"]},
        {"id": 3, "type": "KSampler", "widgets_values": [123, "fixed", 20, 7.0, "euler", "normal", 1.0, 6, 7]},
    ],
    "links": [],
}

API_PROMPT = {
    "3": {"class_type": "KSampler", "inputs": {"seed": 123, "positive": ["6", 0],
           "negative": ["7", 0], "model": ["4", 0]}},
    "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "dreamshaper.safetensors"}},
    "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "a sunny beach"}},
    "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "watermark"}},
}


def make_comfyui_png(path, workflow=None, prompt=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    im = PILImage.new("RGB", (16, 16), "blue")
    info = PngInfo()
    if workflow is not None:
        info.add_text("workflow", json.dumps(workflow))
    if prompt is not None:
        info.add_text("prompt", json.dumps(prompt))
    im.save(path, pnginfo=info)
    return path


def test_extract_ui_workflow_and_summary(gthumb_home):
    img = make_comfyui_png(gthumb_home["data"] / "img" / "comfy.png", UI_WORKFLOW, API_PROMPT)
    data = comfyui.extract(img)
    assert data["has_workflow"] is True
    assert data["node_count"] == 5
    assert data["models"] == ["dreamshaper.safetensors"]
    assert data["positive_prompt"] == "a sunny beach"
    assert data["negative_prompt"] == "watermark"
    assert data["workflow"]["nodes"][1]["widgets_values"] == ["a sunny beach"]
    assert data["prompt"]["6"]["inputs"]["text"] == "a sunny beach"


def test_extract_without_prompt(gthumb_home):
    img = make_comfyui_png(gthumb_home["data"] / "img" / "comfy.png", UI_WORKFLOW, API_PROMPT)
    data = comfyui.extract(img, include_prompt=False)
    assert "prompt" not in data
    assert data["workflow"]


def test_extract_without_workflow_raises(gthumb_home):
    img = make_image(gthumb_home["data"] / "img" / "plain.png")
    with pytest.raises(comfyui.ComfyUIError, match="No embedded ComfyUI workflow"):
        comfyui.extract(img)
    assert comfyui.has_workflow(img) is False


def test_has_workflow(gthumb_home):
    img = make_comfyui_png(gthumb_home["data"] / "img" / "comfy.png", UI_WORKFLOW, API_PROMPT)
    assert comfyui.has_workflow(img) is True


def test_jpeg_user_comment_fallback(gthumb_home):
    """ComfyUI JPEGs embed 'workflow: {...}' inside the EXIF UserComment."""
    img = gthumb_home["data"] / "img" / "comfy.jpg"
    img.parent.mkdir(parents=True, exist_ok=True)
    im = PILImage.new("RGB", (16, 16), "green")
    exif = im.getexif()
    exif[comfyui.EXIF_USER_COMMENT] = (
        "prompt: " + json.dumps(API_PROMPT) + " workflow: " + json.dumps(UI_WORKFLOW)
    )
    im.save(img, exif=exif.tobytes())

    assert comfyui.has_workflow(img) is True
    data = comfyui.extract(img)
    assert data["has_workflow"] is True
    assert data["node_count"] == 5
    assert data["models"] == ["dreamshaper.safetensors"]


UE_UI_GRAPH = {
    "nodes": [
        # rgthree "Anything Everywhere": sampler has no positive/negative
        # inputs, prompts are wired implicitly at execution time.
        {"id": 37, "type": "KSamplerSelect", "widgets_values": ["euler"]},
        {"id": 5, "type": "CLIPTextEncode", "widgets_values": ["(score_9, score_8_up), 1girl, selfie"]},
        {"id": 6, "type": "CLIPTextEncode", "widgets_values": ["score_6, watermark"]},
    ],
    "links": [],
}

UE_API_PROMPT = {
    "5": {"class_type": "CLIPTextEncode", "inputs": {"text": "(score_9, score_8_up), 1girl, selfie"}},
    "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "score_6, watermark"}},
    "37": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
}


def test_ue_wired_ui_graph_falls_back_to_text_nodes(gthumb_home):
    img = make_comfyui_png(gthumb_home["data"] / "img" / "ue.png", UE_UI_GRAPH, UE_API_PROMPT)
    data = comfyui.extract(img)
    assert data["has_workflow"] is True
    assert data["positive_prompt"] == "(score_9, score_8_up), 1girl, selfie"
    assert data["negative_prompt"] == "score_6, watermark"


def test_api_summary_falls_back_to_text_nodes(gthumb_home):
    data = comfyui.summarize(UE_API_PROMPT)
    assert data["positive_prompt"] == "(score_9, score_8_up), 1girl, selfie"
    assert data["negative_prompt"] == "score_6, watermark"


def test_extract_fills_missing_prompts_from_api_chunk(gthumb_home):
    """UI summary misses prompts; the API chunk must fill them (bug report case)."""
    img = make_comfyui_png(gthumb_home["data"] / "img" / "ue2.png", UE_UI_GRAPH, UE_API_PROMPT)
    ui_only = comfyui.summarize(UE_UI_GRAPH)
    assert ui_only["positive_prompt"] == "(score_9, score_8_up), 1girl, selfie"

    data = comfyui.extract(img, include_prompt=False)
    assert data["positive_prompt"] == "(score_9, score_8_up), 1girl, selfie"
    assert data["negative_prompt"] == "score_6, watermark"
    assert "prompt" not in data
