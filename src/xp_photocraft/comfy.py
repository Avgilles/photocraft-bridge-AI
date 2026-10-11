"""ComfyUI over HTTP: upload, queue, wait, fetch. The only module that pulls in ``httpx``."""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from xp_photocraft.config import (
    BUILTIN_MODELS,
    COMFY_JOB_TIMEOUT_S,
    COMFY_POLL_S,
    COMFY_TIMEOUT_S,
)


class ComfyError(RuntimeError):
    """ComfyUI refused the graph, failed while running it, or produced no image."""


class Comfy:
    """A ComfyUI server reachable over HTTP: this PC, another PC on the LAN, or a tunnel."""

    def __init__(self, base_url: str, timeout: float = COMFY_TIMEOUT_S, api_key: str = "") -> None:
        # trust_env=False: an HTTP(S)_PROXY meant for the internet must not see this traffic.
        self._http = httpx.Client(base_url=base_url, trust_env=False, timeout=timeout)
        # Partner nodes (Nano Banana, …) bill this comfy.org account; never logged, never printed.
        self._extra = {"extra_data": {"api_key_comfy_org": api_key}} if api_key else {}

    def ping(self) -> None:
        """Raise unless a ComfyUI server answers (any models, any custom nodes)."""
        if "system" not in self._http.get("/system_stats").json():
            raise ComfyError("not a ComfyUI server")

    def find_models(self) -> dict[str, dict[str, str]]:
        """Return the built-in loaders' inputs by node class, with this server's file names."""
        found: dict[str, dict[str, str]] = {}
        missing: list[str] = []
        for node, (name_input, files) in BUILTIN_MODELS.items():
            match = self._server_file(node, name_input, files)
            if match:
                found[node] = {name_input: match}
            else:
                missing.append(files[0])
        if missing:
            raise ComfyError(f"models not on the ComfyUI server: {', '.join(missing)}")
        return found

    def resolve_models(self, graph: dict[str, Any]) -> None:
        """Point a graph's loaders of the built-in models at this server's files, in place.

        Its own file in any subfolder first, else another variant (fp8mixed, int8_convrot,
        bf16): the shipped graph names the template's files, a server may hold the others. A
        file the server lacks is left as is, for ComfyUI to name in its refusal.
        """
        for node in graph.values():
            spec = BUILTIN_MODELS.get(str(node.get("class_type")))
            if spec is None or node["inputs"].get(spec[0]) not in spec[1]:
                continue
            name_input, files = spec
            match = self._server_file(
                node["class_type"], name_input, (node["inputs"][name_input], *files)
            )
            if match:
                node["inputs"][name_input] = match

    def _server_file(self, node: str, name_input: str, files: tuple[str, ...]) -> str:
        """The server's name for the first of ``files`` it has (in any subfolder), else ""."""
        info = self._http.get(f"/object_info/{node}").json()
        names: list[str] = info[node]["input"]["required"][name_input][0]
        by_file = {_basename(n): n for n in names}
        return next((by_file[f] for f in files if f in by_file), "")

    def upload(self, file: Path) -> str:
        """Upload an input image and return the name ComfyUI stored it under."""
        files = {"image": (file.name, file.read_bytes(), "image/png")}
        response = self._http.post("/upload/image", files=files, data={"overwrite": "true"})
        response.raise_for_status()
        return str(response.json()["name"])

    def run(self, graph: dict[str, Any], output_node: str = "") -> bytes:
        """Queue an API-format graph, wait for it, and return ``output_node``'s image.

        Without ``output_node``: the first saved image (a preview is a fallback, not a result).
        """
        body = {"prompt": graph, "client_id": uuid.uuid4().hex, **self._extra}
        queued = self._http.post("/prompt", json=body)
        if queued.status_code != 200:
            raise ComfyError(f"graph refused: {_refusal(queued)}")
        history = self._wait(str(queued.json()["prompt_id"]))
        image = _pick_image(history["outputs"], output_node)
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
                raise ComfyError(f"ComfyUI failed: {_execution_error(entry['status'])}")
            if entry and entry.get("outputs"):
                return entry
            time.sleep(COMFY_POLL_S)
        raise ComfyError(f"no result after {COMFY_JOB_TIMEOUT_S:.0f} s (prompt {prompt_id})")


def _basename(name: str) -> str:
    # Windows servers list subfolders with backslashes.
    return name.replace("\\", "/").rsplit("/", 1)[-1]


def _refusal(response: httpx.Response) -> str:
    """Why ComfyUI refused a graph, on one line: a missing model is named, not dumped as JSON."""
    try:
        reply = response.json()
    except ValueError:
        return " ".join(response.text.split())[:300]
    for node in reply.get("node_errors", {}).values():
        for error in node.get("errors", []):
            if error.get("type") == "value_not_in_list":
                missing = error.get("extra_info", {}).get("received_value")
                return f"{node.get('class_type')}: {missing} is not on the ComfyUI server"
            return f"{node.get('class_type')}: {error.get('details') or error.get('message')}"[:300]
    return str(reply.get("error", {}).get("message", "unknown reason"))[:300]


def _execution_error(status: dict[str, Any]) -> str:
    """The failing node and its message, on one line (the task bar shows one line)."""
    for kind, data in status.get("messages", []):
        if kind == "execution_error":
            message = " ".join(str(data.get("exception_message", "")).split())
            return f"{data.get('node_type')}: {message}"[:300]
    return " ".join(str(status.get("messages")).split())[:300]


def _pick_image(outputs: dict[str, Any], output_node: str) -> dict[str, str]:
    images = outputs.get(output_node, {}).get("images", [])
    if not images:  # saved images ("output") before previews ("temp"); sorted() is stable
        everything = [image for output in outputs.values() for image in output.get("images", [])]
        images = sorted(everything, key=lambda image: image.get("type") != "output")
    if not images:
        raise ComfyError("the graph finished without an output image")
    return {key: images[0][key] for key in ("filename", "subfolder", "type")}
