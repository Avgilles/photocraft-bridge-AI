"""Every tunable this project has, as plain module constants.

This module never reads ``os.environ``: the three settings a user may change (ComfyUI URL,
PhotoCraft control port, work dir) are CLI options with an environment variable each,
declared where they are used (``cli.py``).
"""

from __future__ import annotations

from pathlib import Path

# --- PhotoCraft control protocol ----------------------------------------------

# Loopback only (PhotoCraft refuses anything else). Same port as its docs' examples.
CONTROL_HOST = "127.0.0.1"
DEFAULT_CONTROL_PORT = 7878

# Desktop control waits up to 60 s for a reply; a socket that outlives it is broken.
CONTROL_TIMEOUT_S = 120.0

# The bridge's files live in ONE folder, granted to PhotoCraft as both automation
# roots (--automation-read-root / --automation-write-root): PhotoCraft refuses any
# path outside them, and paths sent over control are relative to them.
WORK_SEGMENTS = ("xp-photocraft", "work")
TOKEN_FILENAME = "control.token"

# --- the round trip -----------------------------------------------------------

# Context around the selection sent to the model: on a 1248x1893 poster, 96 px around a
# 160x75 selection gave the model enough surroundings to match the light.
MARGIN_PX = 96

REGION_FILE = "region.png"
MASK_FILE = "mask.png"
PLACED_FILE = "placed.png"

# --- ComfyUI ---------------------------------------------------------------------

# ComfyUI's own default address. Another PC: start ComfyUI there and point --server (or
# XP_PHOTOCRAFT_COMFY_URL) at it, directly on a trusted LAN or through an SSH tunnel.
DEFAULT_COMFY_URL = "http://127.0.0.1:8188"
COMFY_TIMEOUT_S = 60.0
COMFY_POLL_S = 0.5
# An inpaint took ~70 s with cold models, ~20 s warm, on one consumer GPU. Ten minutes
# covers a cold load behind a queue.
COMFY_JOB_TIMEOUT_S = 600.0

# Qwen Image Edit 2511 + the 4-step Lightning LoRA, by file name. Each is looked up in the
# server's /object_info by name, so it may sit in any subfolder of its models folder.
UNET = "qwen_image_edit_2511_int8_convrot.safetensors"
CLIP = "qwen_2.5_vl_7b_fp8_scaled.safetensors"
VAE = "qwen_image_vae.safetensors"
LORA = "Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors"

# Remove has no prompt of its own: it asks the edit model for the background.
REMOVE_PROMPT = (
    "remove the object inside the selection and reconstruct the background behind it, "
    "matching the surrounding texture, perspective and lighting"
)

OUTPUT_PREFIX = "xp-photocraft/fill"


def work_dir(local_app_data: Path) -> Path:
    """Return the bridge's work dir under a ``%LOCALAPPDATA%``-like base."""
    return local_app_data.joinpath(*WORK_SEGMENTS)
