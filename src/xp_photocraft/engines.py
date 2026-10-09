"""Engines: a region, its mask and a prompt in, an image out. One per kind of workflow.

``QwenComfy`` is the built-in workflow on a ComfyUI server. ``Runner`` is any external command
speaking ``xp-photocraft/runner@1``: the bridge writes ``request.json`` in the work dir (``image``,
``mask``, ``prompt``, ``seed``, ``mode``) and passes its path as the last argument; the command
prints one JSON line ``{"image": "<png>"}`` on stdout, or exits non-zero with its error as the last
line of stderr.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Protocol

from xp_photocraft import workflows
from xp_photocraft.config import REQUEST_FILE, RUNNER_CONTRACT, RUNNER_TIMEOUT_S


class Engine(Protocol):
    """What the round trip needs: the region and mask PNGs in, the image's PNG bytes out."""

    def generate(self, region: Path, mask: Path, prompt: str, seed: int, mode: str) -> bytes: ...


class ComfyClient(Protocol):
    """The ComfyUI calls the built-in workflow makes (a seam for tests)."""

    def find_models(self, wanted: workflows.Models) -> workflows.Models: ...

    def upload(self, file: Path) -> str: ...

    def run(self, graph: dict[str, object]) -> bytes: ...


class EngineError(RuntimeError):
    """An external workflow command failed or printed no image."""


class QwenComfy:
    """The built-in workflow: Qwen Image Edit 2511 inpaint on a ComfyUI server."""

    def __init__(self, comfy: ComfyClient) -> None:
        self._comfy = comfy

    def generate(self, region: Path, mask: Path, prompt: str, seed: int, mode: str) -> bytes:
        """Upload the region and mask, run the inpaint graph, return its image."""
        models = self._comfy.find_models(workflows.Models())
        graph = workflows.inpaint(
            self._comfy.upload(region), self._comfy.upload(mask), prompt, seed, models
        )
        return self._comfy.run(graph)


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
