"""xp-photocraft CLI: `fill` / `remove` the selection of a running PhotoCraft, `connect`, `doctor`,
`workflows` / `assign`.

One JSON contract line on stdout (``fill@1`` / ``connect@1`` / ``doctor@1`` / ``workflows@1``), the
human report on stderr. PhotoCraft's task bar shows the report's last line in its status bar: it
never carries the server's address.
"""

from __future__ import annotations

import os
import random
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

import click
import httpx
from pydantic import BaseModel

from xp_photocraft import connection, registry, roundtrip
from xp_photocraft.comfy import Comfy, ComfyError
from xp_photocraft.config import (
    ACTIONS,
    BUILTIN_WORKFLOW,
    CONNECT_TIMEOUT_S,
    DEFAULT_CONTROL_PORT,
    TOKEN_FILENAME,
    connection_file,
    work_dir,
    workflows_file,
)
from xp_photocraft.control import Control, ControlError
from xp_photocraft.engines import Engine, EngineError, QwenComfy, Runner
from xp_photocraft.placeholder import PlacementError
from xp_photocraft.workflows import Models


class FillResult(BaseModel):
    """``fill@1``: what was placed, where, from which seed."""

    contract: str = "fill@1"
    ok: bool
    mode: str
    workflow: str = ""
    layer: str = ""
    bounds: list[int] = []
    seed: int = 0
    seconds: float = 0.0
    error: str = ""


class ConnectResult(BaseModel):
    """``connect@1``: whether the server answered with every model, and was saved."""

    contract: str = "connect@1"
    ok: bool
    server: str = ""
    error: str = ""


class WorkflowChoice(BaseModel):
    """One workflow the UI can offer."""

    id: str
    label: str


class WorkflowsResult(BaseModel):
    """``workflows@1``: every workflow, and the one each action runs."""

    contract: str = "workflows@1"
    ok: bool
    workflows: list[WorkflowChoice] = []
    assign: dict[str, str] = {}
    error: str = ""


class DoctorResult(BaseModel):
    """``doctor@1``: one line per check."""

    contract: str = "doctor@1"
    ok: bool
    checks: dict[str, str]


def _local_app_data() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", Path.home()))


def _default_work() -> Path:
    return work_dir(_local_app_data())


def _server(server: str | None) -> str:
    return server or connection.load(connection_file(_local_app_data()))


def _emit(contract: BaseModel) -> None:
    # Bytes, not print(): print() writes CRLF on Windows and breaks a line contract.
    sys.stdout.buffer.write(contract.model_dump_json().encode("utf-8") + b"\n")
    sys.stdout.buffer.flush()


# Port and work dir also read an environment variable; the ComfyUI server defaults to the saved
# connection, so PhotoCraft's task bar (which runs this CLI with no options) follows it too.
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
        default=None,
        help="ComfyUI base URL for this run only (default: the connection saved by `connect`).",
    ),
]

_workflow_option = click.option(
    "--workflow",
    default="",
    help="Workflow id for this run only (default: the one assigned with `assign`).",
)


_F = TypeVar("_F", bound=Callable[..., Any])


def _with_common(f: _F) -> _F:
    for option in reversed(_common):
        f = option(f)
    return f


Action = Callable[[Control, Engine, int, Path], roundtrip.Rect]


def _engine(reg: registry.Registry, workflow_id: str, server: str | None, root: Path) -> Engine:
    if workflow_id == BUILTIN_WORKFLOW:
        return QwenComfy(Comfy(_server(server)))
    return Runner(reg.workflows[workflow_id].command, root)


def _run(
    mode: str,
    layer: str,
    action: Action,
    seed: int | None,
    port: int,
    work: Path | None,
    server: str | None,
    workflow: str,
) -> None:
    root = work or _default_work()
    seed = random.randrange(2**31) if seed is None else seed
    started = time.perf_counter()
    try:
        reg = registry.load(workflows_file(_local_app_data()))
        workflow = registry.pick(reg, mode, workflow)
        engine = _engine(reg, workflow, server, root)
        rect = action(Control(port, root / TOKEN_FILENAME), engine, seed, root)
    except (
        ControlError,
        ComfyError,
        EngineError,
        registry.WorkflowsError,
        roundtrip.NoSelectionError,
        PlacementError,
        httpx.HTTPError,
    ) as e:
        click.echo(f"xp-photocraft {mode}: {e}", err=True)
        _emit(FillResult(ok=False, mode=mode, workflow=workflow, seed=seed, error=str(e)))
        sys.exit(1)
    seconds = round(time.perf_counter() - started, 2)
    click.echo(
        f"xp-photocraft {mode}: layer {layer!r} at {rect} in {seconds} s ({workflow}, seed {seed})",
        err=True,
    )
    _emit(
        FillResult(
            ok=True,
            mode=mode,
            workflow=workflow,
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
@_workflow_option
@_with_common
def fill(
    prompt: str, seed: int | None, workflow: str, port: int, work: Path | None, server: str | None
) -> None:
    """Generative Fill: repaint the selection from a prompt, as a new masked layer."""
    layer = "Generative Fill"

    def action(pc: Control, engine: Engine, seed: int, root: Path) -> roundtrip.Rect:
        return roundtrip.fill_selection(pc, engine, prompt, seed, root, layer)

    _run("fill", layer, action, seed, port, work, server, workflow)


@cli.command()
@click.option("--seed", type=int, default=None, help="Fixed seed (random by default).")
@_workflow_option
@_with_common
def remove(
    seed: int | None, workflow: str, port: int, work: Path | None, server: str | None
) -> None:
    """Remove (AI): erase what is selected and rebuild the background, as a new masked layer."""
    layer = "Remove (AI)"

    def action(pc: Control, engine: Engine, seed: int, root: Path) -> roundtrip.Rect:
        return roundtrip.remove_selection(pc, engine, seed, root, layer)

    _run("remove", layer, action, seed, port, work, server, workflow)


@cli.command()
@click.argument("url")
def connect(url: str) -> None:
    """Test a ComfyUI server (reachable, every model present) and save it as the connection."""
    try:
        server = connection.normalize(url)
        Comfy(server, timeout=CONNECT_TIMEOUT_S).find_models(Models())
    except (connection.InvalidServerError, ComfyError, httpx.HTTPError, KeyError, ValueError) as e:
        click.echo(f"ComfyUI not connected: {_brief(e)}", err=True)
        _emit(ConnectResult(ok=False, error=_brief(e)))
        sys.exit(1)
    connection.save(connection_file(_local_app_data()), server)
    click.echo("ComfyUI connected - models OK", err=True)
    _emit(ConnectResult(ok=True, server=server))


def _brief(e: Exception) -> str:
    """Say what went wrong without the server's address (it ends up on screen)."""
    if isinstance(e, (connection.InvalidServerError, ComfyError)):
        return str(e)
    if isinstance(e, (httpx.ConnectError, httpx.TimeoutException)):
        return "server unreachable"
    return "not a ComfyUI server"


@cli.command("workflows")
def list_workflows() -> None:
    """List the workflows and the one each action runs."""
    _emit_workflows(registry.load)


@cli.command()
@click.argument("action", type=click.Choice(ACTIONS))
@click.argument("workflow")
def assign(action: str, workflow: str) -> None:
    """Make ACTION (fill, remove) run WORKFLOW from now on."""
    _emit_workflows(lambda path: registry.assign(path, action, workflow))


def _emit_workflows(get: Callable[[Path], registry.Registry]) -> None:
    try:
        reg = get(workflows_file(_local_app_data()))
    except registry.WorkflowsError as e:
        click.echo(f"xp-photocraft workflows: {e}", err=True)
        _emit(WorkflowsResult(ok=False, error=str(e)))
        sys.exit(1)
    labels, assigned = registry.labels(reg), registry.assignment(reg)
    for action, workflow_id in assigned.items():
        click.echo(f"{action} -> {workflow_id} ({labels[workflow_id]})", err=True)
    _emit(
        WorkflowsResult(
            ok=True,
            workflows=[WorkflowChoice(id=k, label=v) for k, v in labels.items()],
            assign=assigned,
        )
    )


@cli.command()
@_with_common
def doctor(port: int, work: Path | None, server: str | None) -> None:
    """Check the PhotoCraft control link, the ComfyUI server and its models."""
    root = work or _default_work()
    server = _server(server)
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
