"""Every tunable this project has, as plain module constants.

This module never reads ``os.environ``. The ComfyUI URL is the saved connection
(``connection.json``, set with ``xp-photocraft connect``); the control port and the work dir are
CLI options with an environment variable each, declared where they are used (``cli.py``).
"""

from __future__ import annotations

from pathlib import Path

# --- PhotoCraft control protocol ----------------------------------------------

# Loopback only (PhotoCraft refuses anything else). Same port as its docs' examples.
CONTROL_HOST = "127.0.0.1"
DEFAULT_CONTROL_PORT = 7878

# Desktop control waits up to 60 s for a reply; a socket that outlives it is broken.
CONTROL_TIMEOUT_S = 120.0
# PhotoCraft closes a control socket after a 30 s read timeout (control-protocol.md, "Transport
# limits"), and a generation waits longer than that: reconnect before a request past this idle time.
CONTROL_IDLE_RECONNECT_S = 20.0

# The bridge's files live in ONE folder, granted to PhotoCraft as both automation
# roots (--automation-read-root / --automation-write-root): PhotoCraft refuses any
# path outside them, and paths sent over control are relative to them.
WORK_SEGMENTS = ("xp-photocraft", "work")
# The saved ComfyUI connection, beside the work dir (never in a repository).
CONNECTION_SEGMENTS = ("xp-photocraft", "connection.json")
# The user's workflows (external commands) and the one each action runs, beside it.
WORKFLOWS_SEGMENTS = ("xp-photocraft", "workflows.json")
TOKEN_FILENAME = "control.token"

# --- the round trip -----------------------------------------------------------

# Context around the selection sent to the model: on a 1248x1893 poster, 96 px around a
# 160x75 selection gave the model enough surroundings to match the light.
MARGIN_PX = 96

REGION_FILE = "region.png"
MASK_FILE = "mask.png"
PLACED_FILE = "placed.png"

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


def work_dir(local_app_data: Path) -> Path:
    """Return the bridge's work dir under a ``%LOCALAPPDATA%``-like base."""
    return local_app_data.joinpath(*WORK_SEGMENTS)


def connection_file(local_app_data: Path) -> Path:
    """Return the saved connection's file under a ``%LOCALAPPDATA%``-like base."""
    return local_app_data.joinpath(*CONNECTION_SEGMENTS)


def workflows_file(local_app_data: Path) -> Path:
    """Return the user's workflows file under a ``%LOCALAPPDATA%``-like base."""
    return local_app_data.joinpath(*WORKFLOWS_SEGMENTS)
