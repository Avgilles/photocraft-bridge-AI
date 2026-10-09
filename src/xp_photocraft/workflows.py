"""The built-in workflow, as an API-format ComfyUI graph tagged like any user graph.

Node titles carry the ``pc:*`` tags (image, mask, prompt, seed) the engine fills in
(``engines.ComfyGraph``). ComfyUI core nodes only; the mask is loaded on its own
(``LoadImageMask``, red channel, white = repaint).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from xp_photocraft.config import OUTPUT_PREFIX


@dataclass(frozen=True)
class Models:
    """Model names as the ComfyUI server lists them (subfolder included)."""

    unet: str
    clip: str
    vae: str
    lora: str


def inpaint(models: Models) -> dict[str, Any]:
    """Qwen Image Edit 2511 inpaint of the ``pc:mask`` area of ``pc:image``, composited over it."""

    def encode(text: str) -> dict[str, Any]:
        return {"clip": ["clip", 0], "vae": ["vae", 0], "image1": ["scale", 0], "prompt": text}

    return {
        "image": _node("LoadImage", {"image": ""}, "pc:image"),
        "mask": _node("LoadImageMask", {"image": "", "channel": "red"}, "pc:mask"),
        "scale": _node(
            "ImageScaleToTotalPixels",
            {
                "image": ["image", 0],
                "upscale_method": "lanczos",
                "megapixels": 1.0,
                "resolution_steps": 1,
            },
        ),
        "grow": _node("GrowMask", {"mask": ["mask", 0], "expand": 6, "tapered_corners": True}),
        "unet": _node("UNETLoader", {"unet_name": models.unet, "weight_dtype": "default"}),
        "clip": _node(
            "CLIPLoader", {"clip_name": models.clip, "type": "qwen_image", "device": "default"}
        ),
        "vae": _node("VAELoader", {"vae_name": models.vae}),
        "aura": _node("ModelSamplingAuraFlow", {"model": ["unet", 0], "shift": 3.1}),
        "norm": _node("CFGNorm", {"model": ["aura", 0], "strength": 1}),
        "lora": _node(
            "LoraLoaderModelOnly",
            {"model": ["norm", 0], "lora_name": models.lora, "strength_model": 1},
        ),
        "pos": _node("TextEncodeQwenImageEditPlus", encode(""), "pc:prompt"),
        "neg": _node("TextEncodeQwenImageEditPlus", encode("")),
        "inpaint": _node(
            "InpaintModelConditioning",
            {
                "positive": ["pos", 0],
                "negative": ["neg", 0],
                "vae": ["vae", 0],
                "pixels": ["scale", 0],
                "mask": ["grow", 0],
                "noise_mask": True,
            },
        ),
        "sampler": _node(
            "KSampler",
            {
                "model": ["lora", 0],
                "seed": 0,
                "steps": 4,
                "cfg": 1,
                "sampler_name": "euler",
                "scheduler": "simple",
                "positive": ["inpaint", 0],
                "negative": ["inpaint", 1],
                "latent_image": ["inpaint", 2],
                "denoise": 1,
            },
            "pc:seed",
        ),
        "decode": _node("VAEDecode", {"samples": ["sampler", 0], "vae": ["vae", 0]}),
        "composite": _node(
            "ImageCompositeMasked",
            {
                "destination": ["scale", 0],
                "source": ["decode", 0],
                "x": 0,
                "y": 0,
                "resize_source": False,
                "mask": ["grow", 0],
            },
        ),
        "save": _node(
            "SaveImage", {"images": ["composite", 0], "filename_prefix": OUTPUT_PREFIX}, "pc:output"
        ),
    }


def _node(class_type: str, inputs: dict[str, Any], title: str = "") -> dict[str, Any]:
    node: dict[str, Any] = {"class_type": class_type, "inputs": inputs}
    if title:
        node["_meta"] = {"title": title}
    return node
