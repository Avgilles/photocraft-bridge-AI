"""xp-photocraft CLI: ``fill`` / ``remove`` the selection of a running PhotoCraft, ``doctor``.

One JSON contract line on stdout (``fill@1`` / ``doctor@1``), the human report on stderr.
"""

from __future__ import annotations

import os
import random
import sys
import time
from collections.abc import Callable
from pathlib import Path

import click
import httpx
from pydantic import BaseModel

from xp_photocraft import roundtrip
from xp_photocraft.comfy import Comfy, ComfyError
from xp_photocraft.config import (
    DEFAULT_COMFY_URL,
    DEFAULT_CONTROL_PORT,
    TOKEN_FILENAME,
    work_dir,
)
from xp_photocraft.control import Control, ControlError
from xp_photocraft.workflows import Models


class FillResult(BaseModel):
    """``fill@1``: what was placed, where, from which seed."""

    contract: str = "fill@1"
    ok: bool
    mode: str
    layer: str = ""
    bounds: list[int] = []
    seed: int = 0
    seconds: float = 0.0
    error: str = ""


class DoctorResult(BaseModel):
    """``doctor@1``: one line per check."""

    contract: str = "doctor@1"
    ok: bool
    checks: dict[str, str]


def _default_work() -> Path:
    return work_dir(Path(os.environ.get("LOCALAPPDATA", Path.home())))


def _emit(contract: BaseModel) -> None:
    # Bytes, not print(): print() writes CRLF on Windows and breaks a line contract.
    sys.stdout.buffer.write(contract.model_dump_json().encode("utf-8") + b"\n")
    sys.stdout.buffer.flush()


# Each setting also reads an environment variable, so PhotoCraft's task bar (which runs this
# CLI with no options) follows the same machine-wide choice as a shell.
_common = [
    click.option(
        "--port",
        envvar="PHOTOCRAFT_CONTROL_PORT",
        default=DEFAULT_CONTROL_PORT,
        show_default=True,
        help="PhotoCraft --control port [env PHOTOCRAFT_CONTROL_PORT].",
    ),
    click.option(
        "--work",
        envvar="XP_PHOTOCRAFT_WORK",
        type=click.Path(path_type=Path),
        default=None,
        help="Automation root shared with PhotoCraft [env XP_PHOTOCRAFT_WORK].",
    ),
    click.option(
        "--server",
        envvar="XP_PHOTOCRAFT_COMFY_URL",
        default=DEFAULT_COMFY_URL,
        show_default=True,
        help="ComfyUI base URL, local or remote [env XP_PHOTOCRAFT_COMFY_URL].",
    ),
]


def _with_common(f):  # type: ignore[no-untyped-def]
    for option in reversed(_common):
        f = option(f)
    return f


Action = Callable[[Control, Comfy, int, Path], roundtrip.Rect]


def _run(
    mode: str,
    layer: str,
    action: Action,
    seed: int | None,
    port: int,
    work: Path | None,
    server: str,
) -> None:
    root = work or _default_work()
    seed = random.randrange(2**31) if seed is None else seed
    started = time.perf_counter()
    try:
        rect = action(Control(port, root / TOKEN_FILENAME), Comfy(server), seed, root)
    except (ControlError, ComfyError, roundtrip.NoSelectionError, httpx.HTTPError) as e:
        click.echo(f"xp-photocraft {mode}: {e}", err=True)
        _emit(FillResult(ok=False, mode=mode, seed=seed, error=str(e)))
        sys.exit(1)
    seconds = round(time.perf_counter() - started, 2)
    click.echo(
        f"xp-photocraft {mode}: layer {layer!r} at {rect} in {seconds} s (seed {seed})", err=True
    )
    _emit(
        FillResult(
            ok=True,
            mode=mode,
            layer=layer,
            bounds=[rect.x, rect.y, rect.width, rect.height],
            seed=seed,
            seconds=seconds,
        )
    )


@click.group()
@click.version_option(package_name="xp-photocraft")
def cli() -> None:
    """xp-photocraft: ComfyUI actions on the selection of a running PhotoCraft."""


@cli.command()
@click.option("--prompt", required=True, help="What to paint inside the selection.")
@click.option("--seed", type=int, default=None, help="Fixed seed (random by default).")
@_with_common
def fill(prompt: str, seed: int | None, port: int, work: Path | None, server: str) -> None:
    """Generative Fill: repaint the selection from a prompt, as a new masked layer."""
    layer = "Generative Fill"

    def action(pc: Control, comfy: Comfy, seed: int, root: Path) -> roundtrip.Rect:
        return roundtrip.fill_selection(pc, comfy, prompt, seed, root, layer)

    _run("fill", layer, action, seed, port, work, server)


@cli.command()
@click.option("--seed", type=int, default=None, help="Fixed seed (random by default).")
@_with_common
def remove(seed: int | None, port: int, work: Path | None, server: str) -> None:
    """Remove (AI): erase what is selected and rebuild the background, as a new masked layer."""
    layer = "Remove (AI)"

    def action(pc: Control, comfy: Comfy, seed: int, root: Path) -> roundtrip.Rect:
        return roundtrip.remove_selection(pc, comfy, seed, root, layer)

    _run("remove", layer, action, seed, port, work, server)


@cli.command()
@_with_common
def doctor(port: int, work: Path | None, server: str) -> None:
    """Check the PhotoCraft control link, the ComfyUI server and its models."""
    root = work or _default_work()
    checks = {"work-dir": "ok" if root.is_dir() else f"missing: {root}"}
    try:
        Control(port, root / TOKEN_FILENAME).close()
        checks["photocraft-control"] = "ok"
    except ControlError as e:
        checks["photocraft-control"] = str(e)
    try:
        Comfy(server).find_models(Models())
        checks["comfy-models"] = "ok"
    except (ComfyError, httpx.HTTPError, KeyError, ValueError) as e:
        checks["comfy-models"] = f"{server}: {e}"
    ok = all(v == "ok" for v in checks.values())
    for name, state in checks.items():
        click.echo(f"{'ok ' if state == 'ok' else 'FAIL'} {name}: {state}", err=True)
    _emit(DoctorResult(ok=ok, checks=checks))
    sys.exit(0 if ok else 1)


def main() -> None:
    """Console entry point for the xp-photocraft command."""
    cli()
