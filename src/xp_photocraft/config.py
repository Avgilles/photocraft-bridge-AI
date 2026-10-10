"""Every tunable this project has, as plain module constants.

This module never reads ``os.environ``. The ComfyUI URL is the saved connection
(``connection.json``, set with ``xp-photocraft connect``); the data folder, the control port, the
work dir and the comfy.org API key are read where they are used (``cli.py``).
"""

from __future__ import annotations

# --- PhotoCraft control protocol ----------------------------------------------

# Loopback only (PhotoCraft refuses anything else). Same port as its docs' examples.
CONTROL_HOST = "127.0.0.1"
DEFAULT_CONTROL_PORT = 7878

# Desktop control waits up to 60 s for a reply; a socket that outlives it is broken.
CONTROL_TIMEOUT_S = 120.0
# PhotoCraft closes a control socket after a 30 s read timeout (control-protocol.md, "Transport
# limits"), and a generation waits longer than that: reconnect before a request past this idle time.
CONTROL_IDLE_RECONNECT_S = 20.0

# The bridge's data folder (under %LOCALAPPDATA%, $XDG_DATA_HOME or ~/.local/share) holds the
# work dir, granted to PhotoCraft as both automation roots (--automation-read-root /
# --automation-write-root: it refuses any path outside them, and paths sent over control are
# relative to them), the saved connection and the user's workflows (never in a repository).
APP_DIR = "xp-photocraft"
WORK_DIR = "work"
# A release is portable: this file next to the executable puts the data folder (connection,
# workflows, work dir) in ``data`` beside it, so one folder holds the whole installation.
PORTABLE_MARKER = "portable.txt"
PORTABLE_DATA_DIR = "data"
CONNECTION_FILE = "connection.json"
WORKFLOWS_FILE = "workflows.json"
TOKEN_FILENAME = "control.token"

# --- the round trip -----------------------------------------------------------

# Context around the selection sent to the model: on a 1248x1893 poster, 96 px around a
# 160x75 selection gave the model enough surroundings to match the light.
MARGIN_PX = 96

# Generation size of the built-in graph (its pc:scale node), in megapixels: the region's own
# size, clamped. Below the floor the model drops detail (a 120x50 px plate came out blank at
# 0.07 MP, fine from 0.25); above the ceiling it is slow for nothing. Measured 2026-10-09 on a 3090:
# sampling cost follows the pixel count once the reference latent is encoded at the same size.
GEN_MIN_MP = 0.25
GEN_MAX_MP = 1.0

REGION_FILE = "region.png"
MASK_FILE = "mask.png"
PLACED_FILE = "placed.png"
# The crossed card shown over the selection while it generates.
PLACEHOLDER_FILE = "placeholder.png"

# --- ComfyUI ---------------------------------------------------------------------

# ComfyUI's own default address, used until a connection is saved. Another PC: start ComfyUI
# there and `xp-photocraft connect` to it, on a trusted LAN or through an SSH tunnel.
DEFAULT_COMFY_URL = "http://127.0.0.1:8188"
COMFY_TIMEOUT_S = 60.0
# Testing a connection answers fast or not at all: a wrong address must not hang the UI.
CONNECT_TIMEOUT_S = 5.0
COMFY_POLL_S = 0.5
# An inpaint took ~70 s with cold models, ~20 s warm, on one consumer GPU. Ten minutes
# covers a cold load behind a queue.
COMFY_JOB_TIMEOUT_S = 600.0

# The built-in workflow: Qwen Image Edit 2511 + the 4-step Lightning LoRA, an API graph shipped
# with the package (also the starting point for your own settings).
BUILTIN_GRAPH = "qwen-edit-2511.api.json"
# Its loader nodes: the input to set, and the files ComfyUI's own "Qwen Image Edit 2511" templates
# install (the main one ships fp8mixed, the int8 one int8_convrot), first match wins. Each is
# looked up in the server's /object_info by file name, so it may sit in any subfolder.
BUILTIN_MODELS = {
    "UNETLoader": (
        "unet_name",
        (
            "qwen_image_edit_2511_fp8mixed.safetensors",
            "qwen_image_edit_2511_int8_convrot.safetensors",
            "qwen_image_edit_2511_bf16.safetensors",
        ),
    ),
    "CLIPLoader": ("clip_name", ("qwen_2.5_vl_7b_fp8_scaled.safetensors",)),
    "VAELoader": ("vae_name", ("qwen_image_vae.safetensors",)),
    "LoraLoaderModelOnly": (
        "lora_name",
        ("Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors",),
    ),
}

# Remove has no prompt of its own: it asks the edit model for the background.
REMOVE_PROMPT = (
    "remove the object inside the selection and reconstruct the background behind it, "
    "matching the surrounding texture, perspective and lighting"
)

# --- workflows -------------------------------------------------------------------

# The actions a workflow can be assigned to, and the workflow each runs until assigned.
ACTIONS = ("fill", "remove")
BUILTIN_WORKFLOW = "qwen-edit"
BUILTIN_LABEL = "Qwen Edit 2511 (ComfyUI)"

# An external workflow command reads this request (written in the work dir) and prints the image.
RUNNER_CONTRACT = "xp-photocraft/runner@1"
REQUEST_FILE = "request.json"
# Same budget as a ComfyUI job: a cloud model behind a queue can be slow too.
RUNNER_TIMEOUT_S = 600.0
