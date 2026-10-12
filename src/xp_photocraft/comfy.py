"""ComfyUI over HTTP: upload, queue, wait, fetch. The only module that pulls in ``httpx``."""

from __future__ import annotations

import copy
import logging
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from xp_photocraft.config import (
    BUILTIN_MODELS,
    COMFY_JOB_TIMEOUT_S,
    COMFY_POLL_S,
    COMFY_TIMEOUT_S,
)

logger = logging.getLogger(__name__)

# Inputs naming a model file; their values are checked against the server's own lists.
_MODEL_SUFFIXES = (".safetensors", ".ckpt", ".pt", ".pth", ".bin", ".gguf", ".sft")


class ComfyError(RuntimeError):
    """ComfyUI refused the graph, failed while running it, or produced no image."""


class Cancelled(RuntimeError):
    """The caller withdrew the job while it waited: taken off ComfyUI's queue, or stopped."""


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

    def missing(self, graph: dict[str, Any]) -> list[str]:
        """What ``graph`` needs that this server lacks: node types, then model files, one line each.

        A built-in model's other variant counts as found, as when it runs (``resolve_models``).
        """
        graph = copy.deepcopy(graph)
        self.resolve_models(graph)
        found: list[str] = []
        for node in graph.values():
            class_type = str(node.get("class_type"))
            spec = self._spec(class_type)
            if spec is None:
                found.append(f"{class_type}: this node type is not on the ComfyUI server")
                continue
            for name, value in node.get("inputs", {}).items():
                if not (isinstance(value, str) and value.lower().endswith(_MODEL_SUFFIXES)):
                    continue
                names = _choices(spec, name)
                if names is not None and _basename(value) not in {_basename(n) for n in names}:
                    found.append(f"{class_type}: {_basename(value)} is not on the ComfyUI server")
        return found

    def _spec(self, node: str) -> dict[str, Any] | None:
        """``node``'s input spec from /object_info; None for a node type the server lacks."""
        info: dict[str, Any] = self._http.get(f"/object_info/{node}").json()
        return info[node].get("input", {}) if node in info else None

    def _server_file(self, node: str, name_input: str, files: tuple[str, ...]) -> str:
        """The server's name for the first of ``files`` it has (in any subfolder), else ""."""
        by_file = {_basename(n): n for n in _choices(self._spec(node) or {}, name_input) or []}
        return next((by_file[f] for f in files if f in by_file), "")

    def upload(self, file: Path) -> str:
        """Upload an input image and return the name ComfyUI stored it under."""
        files = {"image": (file.name, file.read_bytes(), "image/png")}
        response = self._http.post("/upload/image", files=files, data={"overwrite": "true"})
        response.raise_for_status()
        return str(response.json()["name"])

    def run(
        self,
        graph: dict[str, Any],
        output_node: str = "",
        still_wanted: Callable[[], bool] = lambda: True,
    ) -> bytes:
        """Queue an API-format graph, wait for it, and return ``output_node``'s image.

        Without ``output_node``: the first saved image (a preview is a fallback, not a result).
        """
        images: list[bytes] = []
        self.run_all([graph], output_node, lambda _k, png: images.append(png), still_wanted)
        return images[0]

    def run_all(
        self,
        graphs: list[dict[str, Any]],
        output_node: str,
        on_image: Callable[[int, bytes], None],
        still_wanted: Callable[[], bool] = lambda: True,
    ) -> None:
        """Queue every graph at once, then hand each image to ``on_image(k, png)`` as it comes.

        ``still_wanted`` is asked at every poll. Once it says no (Cancelled), or anything fails,
        ``on_image`` included, the graphs not done are withdrawn: nothing keeps running on the
        server for a result nobody will take.
        """
        pending: dict[str, int] = {}
        try:
            for k, graph in enumerate(graphs):
                pending[self._queue(graph)] = k
            self._collect(pending, output_node, on_image, still_wanted)
        except BaseException:
            if pending:
                self._withdraw(list(pending))
            raise

    def _queue(self, graph: dict[str, Any]) -> str:
        body = {"prompt": graph, "client_id": uuid.uuid4().hex, **self._extra}
        queued = self._http.post("/prompt", json=body)
        if queued.status_code != 200:
            raise ComfyError(f"graph refused: {_refusal(queued)}")
        return str(queued.json()["prompt_id"])

    def _collect(
        self,
        pending: dict[str, int],
        output_node: str,
        on_image: Callable[[int, bytes], None],
        still_wanted: Callable[[], bool],
    ) -> None:
        """Poll until every pending prompt is done; ``pending`` shrinks as images come."""
        started: dict[str, float] = {}
        while pending:
            for prompt_id in list(pending):
                entry: dict[str, Any] | None = (
                    self._http.get(f"/history/{prompt_id}").json().get(prompt_id)
                )
                if entry and entry.get("status", {}).get("status_str") == "error":
                    raise ComfyError(f"ComfyUI failed: {_execution_error(entry['status'])}")
                if entry and entry.get("outputs"):
                    image = self._image(entry["outputs"], output_node)
                    on_image(pending.pop(prompt_id), image)
            if not pending:
                return
            if not still_wanted():
                raise Cancelled(f"{len(pending)} prompt(s) withdrawn")
            self._check_deadline(pending, started)
            time.sleep(COMFY_POLL_S)

    def _check_deadline(self, pending: dict[str, int], started: dict[str, float]) -> None:
        # The clock starts when a prompt runs, not when it is queued: a run behind another one
        # (or behind someone else's) waits its turn without timing out.
        now = time.monotonic()
        for job in self._http.get("/queue").json().get("queue_running", []):
            if job[1] in pending:
                started.setdefault(job[1], now)
        late = [p for p in pending if now - started.get(p, now) > COMFY_JOB_TIMEOUT_S]
        if late:
            raise ComfyError(f"no result after {COMFY_JOB_TIMEOUT_S:.0f} s (prompt {late[0]})")

    def _image(self, outputs: dict[str, Any], output_node: str) -> bytes:
        view = self._http.get("/view", params=_pick_image(outputs, output_node))
        view.raise_for_status()
        return view.content

    def _withdraw(self, prompt_ids: list[str]) -> None:
        """Take the jobs off the queue, or stop those that run; other jobs are someone else's."""
        try:
            self._http.post("/queue", json={"delete": prompt_ids})
            for job in self._http.get("/queue").json().get("queue_running", []):
                if job[1] in prompt_ids:
                    # A server older than targeted interrupts stops whatever runs: this very job.
                    self._http.post("/interrupt", json={"prompt_id": job[1]})
        except httpx.HTTPError as e:  # the failure being raised matters more than this one
            logger.warning("could not withdraw %d prompt(s) from ComfyUI: %s", len(prompt_ids), e)


def _basename(name: str) -> str:
    # Windows servers list subfolders with backslashes.
    return name.replace("\\", "/").rsplit("/", 1)[-1]


def _choices(spec: dict[str, Any], name_input: str) -> list[str] | None:
    """The values an input offers (a file list, an enum); None for a free value."""
    entry = {**spec.get("optional", {}), **spec.get("required", {})}.get(name_input)
    if not entry:
        return None
    first = entry[0]
    if first == "COMBO" and len(entry) > 1 and isinstance(entry[1], dict):  # ComfyUI 0.39 nodes
        first = entry[1].get("options")
    return [str(choice) for choice in first] if isinstance(first, list) else None


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
