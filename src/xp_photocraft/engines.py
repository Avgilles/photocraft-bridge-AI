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
import math
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from PIL import Image

from xp_photocraft import params
from xp_photocraft.comfy import Cancelled, Comfy
from xp_photocraft.config import (
    GEN_MAX_MP,
    GEN_MIN_MP,
    REQUEST_FILE,
    RUNNER_CONTRACT,
    RUNNER_TIMEOUT_S,
)

REQUIRED_TAGS = ("pc:image", "pc:prompt")


class Engine(Protocol):
    """What the round trip needs: the region and mask PNGs in, one PNG per seed out.

    Each image goes to ``on_image(k, png)`` as soon as it exists (``k``: its seed's index), so a
    variation lands while the others still run. ``still_wanted`` answers False once the artist
    cancelled (deleted the placeholder): the engine stops what it can and raises
    ``comfy.Cancelled``.
    """

    def generate(
        self,
        region: Path,
        mask: Path,
        prompt: str,
        seeds: list[int],
        mode: str,
        on_image: Callable[[int, bytes], None],
        still_wanted: Callable[[], bool] = ...,
    ) -> None: ...


class EngineError(RuntimeError):
    """A workflow cannot run: an untagged graph, or an external command that failed."""


class ComfyGraph:
    """An API-format ComfyUI workflow whose nodes are found by their ``pc:*`` titles.

    ``pc:image`` is the LoadImage that receives the region; ``pc:prompt`` gets the prompt in its
    ``prompt`` or ``text`` input, through ``template`` (``{prompt}`` is replaced). Optional:
    ``pc:mask`` (a LoadImage or LoadImageMask; white = repaint), ``pc:seed`` (``seed`` or
    ``noise_seed``; else the ``pc:prompt`` node's own), ``pc:output`` (the image to keep; else
    the first saved one), ``pc:scale`` (``megapixels`` or ``resolution``: the region's own size,
    clamped). One title can carry several tags, space-separated. ``settings[k]`` sets inputs of
    variation ``k`` (``<node>.<input>``: value, see ``params``).
    """

    def __init__(
        self,
        comfy: Comfy,
        graph: dict[str, Any],
        template: str = "{prompt}",
        settings: list[dict[str, Any]] | None = None,
    ) -> None:
        missing = missing_tags(graph)
        if missing:
            raise EngineError(f"the workflow has no node titled {' or '.join(missing)}")
        nodes = _tagged(graph)
        # A graph carries its own wording when its pc:prompt text holds {prompt} (typed in ComfyUI
        # before Export (API)): a file dropped in the workflows folder needs nothing else.
        inputs = nodes["pc:prompt"]["inputs"]
        own = str(inputs.get("prompt", inputs.get("text", "")))
        if template == "{prompt}" and "{prompt}" in own:
            template = own
        self._comfy, self._graph, self._template = comfy, graph, template
        self._settings = settings or []

    def generate(
        self,
        region: Path,
        mask: Path,
        prompt: str,
        seeds: list[int],
        mode: str,
        on_image: Callable[[int, bytes], None],
        still_wanted: Callable[[], bool] = lambda: True,
    ) -> None:
        """Run one filled copy of the graph per seed, all queued at once (one upload)."""
        tagged = _tagged(self._graph)
        image = self._comfy.upload(region)
        mask_name = self._comfy.upload(mask) if "pc:mask" in tagged else ""
        megapixels = generation_megapixels(region) if "pc:scale" in tagged else 0.0
        graphs = [self._filled(image, mask_name, megapixels, prompt, seed) for seed in seeds]
        for graph, settings in zip(graphs, self._settings, strict=False):
            params.apply(graph, settings)
        output = next((i for i, n in self._graph.items() if n is tagged.get("pc:output")), "")
        self._comfy.run_all(graphs, output, on_image, still_wanted)

    def _filled(
        self, image: str, mask: str, megapixels: float, prompt: str, seed: int
    ) -> dict[str, Any]:
        """A copy of the graph with the tagged nodes set for one seed."""
        graph = copy.deepcopy(self._graph)
        nodes = _tagged(graph)
        nodes["pc:image"]["inputs"]["image"] = image
        if mask:
            nodes["pc:mask"]["inputs"]["image"] = mask
        if "pc:scale" in nodes:
            if "resolution" in nodes["pc:scale"]["inputs"]:
                # Qwen Image 2.1's encoder: the side of a square of that area, multiple of 32.
                nodes["pc:scale"]["inputs"]["resolution"] = (
                    round(math.sqrt(megapixels * 1e6) / 32) * 32
                )
            else:
                _set(nodes, "pc:scale", ("megapixels",), megapixels)
        _set(nodes, "pc:prompt", ("prompt", "text"), self._template.replace("{prompt}", prompt))
        # A node titled pc:seed; else the prompt node's own seed (API nodes such as Nano Banana).
        seeded = "pc:seed" if "pc:seed" in nodes else "pc:prompt"
        if {"seed", "noise_seed"} & nodes[seeded]["inputs"].keys():
            _set(nodes, seeded, ("seed", "noise_seed"), seed)
        return graph


def missing_tags(graph: dict[str, Any]) -> list[str]:
    """The ``pc:*`` titles every workflow needs that ``graph`` lacks."""
    tagged = _tagged(graph)
    return [tag for tag in REQUIRED_TAGS if tag not in tagged]


def generation_megapixels(region: Path) -> float:
    """The size to generate ``region`` at: its own, clamped to the built-in graph's range."""
    with Image.open(region) as image:
        megapixels = image.width * image.height / 1e6
    return round(min(GEN_MAX_MP, max(GEN_MIN_MP, megapixels)), 3)


def _tagged(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    # A title may carry several tags ("pc:prompt pc:scale"): one node, several roles.
    return {
        tag: node
        for node in graph.values()
        if isinstance(node, dict)
        for tag in str(node.get("_meta", {}).get("title")).split()
    }


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

    def generate(
        self,
        region: Path,
        mask: Path,
        prompt: str,
        seeds: list[int],
        mode: str,
        on_image: Callable[[int, bytes], None],
        still_wanted: Callable[[], bool] = lambda: True,
    ) -> None:
        """Run the command once per seed, in turn; each PNG it prints goes to ``on_image``."""
        for k, seed in enumerate(seeds):
            # ponytail: a running command goes to its end once cancelled, only the next ones are
            # dropped; stop it through Popen and still_wanted if commands get long.
            if not still_wanted():
                raise Cancelled(f"{len(seeds) - k} variation(s) not run")
            on_image(k, self._run(region, mask, prompt, seed, mode))

    def _run(self, region: Path, mask: Path, prompt: str, seed: int, mode: str) -> bytes:
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
