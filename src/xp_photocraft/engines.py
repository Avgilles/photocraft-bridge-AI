"""Engines: a region, its mask and a prompt in, an image out. One per kind of workflow.

``ComfyGraph`` runs any API-format ComfyUI workflow (the built-in one included) on a ComfyUI
server; its nodes are found by title (``pc:image``, ``pc:prompt``, optionally ``pc:mask``,
``pc:seed``, ``pc:output``). ``Runner`` is any external command speaking ``xp-photocraft/runner@1``:
the bridge writes ``request.json`` in the work dir (``image``, ``mask``, ``prompt``, ``seed``,
``mode``) and passes its path as the last argument; the command prints one JSON line
``{"image": "<png>"}`` on stdout, or exits non-zero with its error as the last line of stderr.
"""

from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path
from typing import Any, Protocol

from xp_photocraft.comfy import Comfy
from xp_photocraft.config import REQUEST_FILE, RUNNER_CONTRACT, RUNNER_TIMEOUT_S

REQUIRED_TAGS = ("pc:image", "pc:prompt")


class Engine(Protocol):
    """What the round trip needs: the region and mask PNGs in, the image's PNG bytes out."""

    def generate(self, region: Path, mask: Path, prompt: str, seed: int, mode: str) -> bytes: ...


class EngineError(RuntimeError):
    """A workflow cannot run: an untagged graph, or an external command that failed."""


class ComfyGraph:
    """An API-format ComfyUI workflow whose nodes are found by their ``pc:*`` titles.

    ``pc:image`` is the LoadImage that receives the region; ``pc:prompt`` gets the prompt in its
    ``prompt`` or ``text`` input, through ``template`` (``{prompt}`` is replaced). Optional:
    ``pc:mask`` (a LoadImage or LoadImageMask; white = repaint), ``pc:seed`` (``seed`` or
    ``noise_seed``; else the ``pc:prompt`` node's own), ``pc:output`` (the image to keep; else
    the first saved one).
    """

    def __init__(self, comfy: Comfy, graph: dict[str, Any], template: str = "{prompt}") -> None:
        missing = [tag for tag in REQUIRED_TAGS if tag not in _tagged(graph)]
        if missing:
            raise EngineError(f"the workflow has no node titled {' or '.join(missing)}")
        self._comfy, self._graph, self._template = comfy, graph, template

    def generate(self, region: Path, mask: Path, prompt: str, seed: int, mode: str) -> bytes:
        """Fill the tagged nodes of a copy of the graph, run it, return its image."""
        graph = copy.deepcopy(self._graph)
        nodes = _tagged(graph)
        nodes["pc:image"]["inputs"]["image"] = self._comfy.upload(region)
        if "pc:mask" in nodes:
            nodes["pc:mask"]["inputs"]["image"] = self._comfy.upload(mask)
        _set(nodes, "pc:prompt", ("prompt", "text"), self._template.replace("{prompt}", prompt))
        # A node titled pc:seed; else the prompt node's own seed (API nodes such as Nano Banana).
        seeded = "pc:seed" if "pc:seed" in nodes else "pc:prompt"
        if {"seed", "noise_seed"} & nodes[seeded]["inputs"].keys():
            _set(nodes, seeded, ("seed", "noise_seed"), seed)
        output = next((i for i, n in graph.items() if n is nodes.get("pc:output")), "")
        return self._comfy.run(graph, output)


def _tagged(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(n.get("_meta", {}).get("title")): n for n in graph.values() if isinstance(n, dict)}


def _set(nodes: dict[str, dict[str, Any]], tag: str, names: tuple[str, ...], value: object) -> None:
    inputs = nodes[tag]["inputs"]
    name = next((n for n in names if n in inputs), None)
    if name is None:
        raise EngineError(f"{tag} has no {' or '.join(names)} input")
    inputs[name] = value


class Runner:
    """An external command speaking ``xp-photocraft/runner@1``."""

    def __init__(self, command: list[str], work: Path, timeout: float = RUNNER_TIMEOUT_S) -> None:
        self._command, self._work, self._timeout = command, work, timeout

    def generate(self, region: Path, mask: Path, prompt: str, seed: int, mode: str) -> bytes:
        """Write the request, run the command on it, return the PNG it printed."""
        request = self._work / REQUEST_FILE
        request.write_text(
            json.dumps(
                {
                    "contract": RUNNER_CONTRACT,
                    "image": str(region.resolve()),
                    "mask": str(mask.resolve()),
                    "prompt": prompt,
                    "seed": seed,
                    "mode": mode,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        try:
            done = subprocess.run(
                [*self._command, str(request)],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=self._timeout,
            )
        except subprocess.TimeoutExpired as e:
            raise EngineError(f"workflow command: no result after {self._timeout:.0f} s") from e
        except OSError as e:
            raise EngineError(f"workflow command could not start: {e.strerror}") from e
        if done.returncode != 0:
            raise EngineError(
                _last_line(done.stderr) or f"workflow command exited {done.returncode}"
            )
        return self._image(done.stdout).read_bytes()

    def _image(self, stdout: str) -> Path:
        try:
            image = json.loads(_last_line(stdout))["image"]
        except (ValueError, KeyError, TypeError) as e:
            raise EngineError("workflow command printed no image") from e
        path = self._work / str(image)  # a relative path is relative to the work dir
        if not path.is_file():
            raise EngineError("workflow command's image is missing")
        return path


def _last_line(text: str) -> str:
    return next((line.strip() for line in reversed(text.splitlines()) if line.strip()), "")
