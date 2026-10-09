"""ComfyUI over HTTP: upload, queue, wait, fetch. The only module that pulls in ``httpx``."""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from xp_photocraft.config import COMFY_JOB_TIMEOUT_S, COMFY_POLL_S, COMFY_TIMEOUT_S
from xp_photocraft.workflows import Models

# Where each model's name list lives in /object_info: (node class, input name).
_MODEL_INPUTS = {
    "unet": ("UNETLoader", "unet_name"),
    "clip": ("CLIPLoader", "clip_name"),
    "vae": ("VAELoader", "vae_name"),
    "lora": ("LoraLoaderModelOnly", "lora_name"),
}


class ComfyError(RuntimeError):
    """ComfyUI refused the graph, failed while running it, or produced no image."""


class Comfy:
    """A ComfyUI server reachable over HTTP: this PC, another PC on the LAN, or a tunnel."""

    def __init__(self, base_url: str, timeout: float = COMFY_TIMEOUT_S) -> None:
        # trust_env=False: an HTTP(S)_PROXY meant for the internet must not see this traffic.
        self._http = httpx.Client(base_url=base_url, trust_env=False, timeout=timeout)

    def find_models(self, wanted: Models) -> Models:
        """Return ``wanted`` with each file name as the server lists it (any subfolder)."""
        found: dict[str, str] = {}
        missing: list[str] = []
        for field, (node, name_input) in _MODEL_INPUTS.items():
            info = self._http.get(f"/object_info/{node}").json()
            names: list[str] = info[node]["input"]["required"][name_input][0]
            file_name = getattr(wanted, field)
            match = next((n for n in names if _basename(n) == file_name), None)
            if match is None:
                missing.append(file_name)
            found[field] = match or file_name
        if missing:
            raise ComfyError(f"models not on the ComfyUI server: {', '.join(missing)}")
        return Models(**found)

    def upload(self, file: Path) -> str:
        """Upload an input image and return the name ComfyUI stored it under."""
        files = {"image": (file.name, file.read_bytes(), "image/png")}
        response = self._http.post("/upload/image", files=files, data={"overwrite": "true"})
        response.raise_for_status()
        return str(response.json()["name"])

    def run(self, graph: dict[str, Any]) -> bytes:
        """Queue an API-format graph, wait for it, and return its first output image."""
        queued = self._http.post("/prompt", json={"prompt": graph, "client_id": uuid.uuid4().hex})
        if queued.status_code != 200:
            raise ComfyError(f"graph refused: {queued.text[:500]}")
        history = self._wait(str(queued.json()["prompt_id"]))
        image = _first_image(history)
        view = self._http.get("/view", params=image)
        view.raise_for_status()
        return view.content

    def _wait(self, prompt_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + COMFY_JOB_TIMEOUT_S
        while time.monotonic() < deadline:
            entry: dict[str, Any] | None = (
                self._http.get(f"/history/{prompt_id}").json().get(prompt_id)
            )
            if entry and entry.get("status", {}).get("status_str") == "error":
                raise ComfyError(f"ComfyUI failed: {str(entry['status'].get('messages'))[:800]}")
            if entry and entry.get("outputs"):
                return entry
            time.sleep(COMFY_POLL_S)
        raise ComfyError(f"no result after {COMFY_JOB_TIMEOUT_S:.0f} s (prompt {prompt_id})")


def _basename(name: str) -> str:
    # Windows servers list subfolders with backslashes.
    return name.replace("\\", "/").rsplit("/", 1)[-1]


def _first_image(history: dict[str, Any]) -> dict[str, str]:
    for output in history["outputs"].values():
        for image in output.get("images", []):
            return {
                "filename": image["filename"],
                "subfolder": image["subfolder"],
                "type": image["type"],
            }
    raise ComfyError("the graph finished without an output image")
