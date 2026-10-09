"""API-format ComfyUI graphs; node titles carry the ``pc:*`` tags (image, mask, prompt, seed).

The inpaint graph uses ComfyUI core nodes only. The mask is loaded on its own
(``LoadImageMask``, red channel, white = repaint).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from xp_photocraft.config import CLIP, LORA, OUTPUT_PREFIX, UNET, VAE


@dataclass(frozen=True)
class Models:
    """Model names as the ComfyUI server lists them (subfolder included)."""

    unet: str = UNET
    clip: str = CLIP
    vae: str = VAE
    lora: str = LORA


def inpaint(image: str, mask: str, prompt: str, seed: int, models: Models) -> dict[str, Any]:
    """Qwen Image Edit 2511 inpaint of ``mask`` inside ``image``, composited over it."""

    def encode(text: str) -> dict[str, Any]:
        return {"clip": ["clip", 0], "vae": ["vae", 0], "image1": ["scale", 0], "prompt": text}

    return {
        "image": _node("LoadImage", {"image": image}, "pc:image"),
        "mask": _node("LoadImageMask", {"image": mask, "channel": "red"}, "pc:mask"),
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
        "pos": _node("TextEncodeQwenImageEditPlus", encode(prompt), "pc:prompt"),
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
                "seed": seed,
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
