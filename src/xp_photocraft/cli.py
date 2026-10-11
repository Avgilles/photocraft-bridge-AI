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
    APP_DIR,
    BUILTIN_GRAPH,
    BUILTIN_WORKFLOW,
    CONNECT_TIMEOUT_S,
    CONNECTION_FILE,
    DEFAULT_CONTROL_PORT,
    PORTABLE_DATA_DIR,
    PORTABLE_MARKER,
    TOKEN_FILENAME,
    WORK_DIR,
    WORKFLOWS_DIR,
    WORKFLOWS_FILE,
)
from xp_photocraft.control import Control, ControlError
from xp_photocraft.engines import ComfyGraph, Engine, EngineError, Runner
from xp_photocraft.placeholder import PlacementError

# A comfy.org API key, for graphs with partner nodes (Nano Banana, ...) on your own ComfyUI.
API_KEY_ENV = "XP_PHOTOCRAFT_COMFY_API_KEY"
# Or in the data folder's .env file (KEY=value lines; the release ships a .env.example).
DOTENV_FILE = ".env"


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
    """``connect@1``: whether a ComfyUI server answered, and was saved."""

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
    server: str = ""
    # Where to drop exported graphs (the UI opens it; never shown).
    folder: str = ""
    error: str = ""


class DoctorResult(BaseModel):
    """``doctor@1``: one line per check."""

    contract: str = "doctor@1"
    ok: bool
    checks: dict[str, str]


def _data_dir() -> Path:
    """``data`` next to a portable executable; else the user's data folder."""
    # The single-file build; from a virtualenv this is its python, which carries no marker.
    beside = Path(sys.executable).resolve().parent
    if (beside / PORTABLE_MARKER).is_file():
        return beside / PORTABLE_DATA_DIR
    # %LOCALAPPDATA% on Windows; elsewhere the XDG data folder (~/.local/share, macOS included).
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_DATA_HOME")
    return (Path(base) if base else Path.home() / ".local" / "share") / APP_DIR


def _default_work() -> Path:
    return _data_dir() / WORK_DIR


def _workflows_file() -> Path:
    return _data_dir() / WORKFLOWS_FILE


def _api_key() -> str:
    """The comfy.org API key: the environment variable, else the data folder's .env file."""
    if os.environ.get(API_KEY_ENV):
        return os.environ[API_KEY_ENV]
    return _dotenv(_data_dir() / DOTENV_FILE).get(API_KEY_ENV, "")


def _dotenv(path: Path) -> dict[str, str]:
    """KEY=value lines of a .env file (comments and blanks skipped, quotes stripped); {} if none."""
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip("\"'")
    return values


def _server(server: str | None) -> str:
    return server or connection.load(_data_dir() / CONNECTION_FILE)


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


Action = Callable[[Control, Engine, int, Path, str], roundtrip.Rect]


def _engine(reg: registry.Registry, workflow_id: str, server: str | None, root: Path) -> Engine:
    """Build the workflow's engine; a ComfyUI graph gets this server's model files first."""
    added = reg.workflows.get(workflow_id)
    if added and added.command:
        return Runner(added.command, root)
    comfy = Comfy(_server(server), api_key=_api_key())
    if added is None:  # the built-in graph shipped in the package
        graph = registry.load_graph(Path(__file__).with_name(BUILTIN_GRAPH))
    else:
        graph = registry.load_graph(_workflows_file().parent / added.graph)
    comfy.resolve_models(graph)
    return ComfyGraph(comfy, graph, added.prompt if added else "{prompt}")


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
        reg = registry.load(_workflows_file())
        workflow = registry.pick(reg, mode, workflow)
        engine = _engine(reg, workflow, server, root)
        rect = action(Control(port, root / TOKEN_FILENAME), engine, seed, root, workflow)
    except (
        ControlError,
        ComfyError,
        EngineError,
        registry.WorkflowsError,
        roundtrip.NoSelectionError,
        PlacementError,
        httpx.HTTPError,
    ) as e:
        error = _http_brief(e) if isinstance(e, httpx.HTTPError) else str(e)
        click.echo(f"xp-photocraft {mode}: {error}", err=True)
        _emit(FillResult(ok=False, mode=mode, workflow=workflow, seed=seed, error=error))
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

    def action(pc: Control, engine: Engine, seed: int, root: Path, wf: str) -> roundtrip.Rect:
        return roundtrip.fill_selection(pc, engine, prompt, seed, root, layer, wf)

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

    def action(pc: Control, engine: Engine, seed: int, root: Path, wf: str) -> roundtrip.Rect:
        return roundtrip.remove_selection(pc, engine, seed, root, layer, wf)

    _run("remove", layer, action, seed, port, work, server, workflow)


@cli.command()
@click.argument("url")
def connect(url: str) -> None:
    """Test a ComfyUI server (any models, any nodes) and save it as the connection."""
    try:
        server = connection.normalize(url)
        comfy = Comfy(server, timeout=CONNECT_TIMEOUT_S)
        comfy.ping()
    except (connection.InvalidServerError, ComfyError, httpx.HTTPError, KeyError, ValueError) as e:
        click.echo(f"ComfyUI not connected: {_brief(e)}", err=True)
        _emit(ConnectResult(ok=False, error=_brief(e)))
        sys.exit(1)
    connection.save(_data_dir() / CONNECTION_FILE, server)
    # Your own graphs may need other models: the built-in ones are reported, not required.
    builtin = "OK" if _check(comfy.find_models) == "ok" else "missing (see doctor)"
    click.echo(f"ComfyUI connected - built-in Qwen models {builtin}", err=True)
    _emit(ConnectResult(ok=True, server=server))


def _brief(e: Exception) -> str:
    """Say what went wrong without the server's address (it ends up on screen)."""
    if isinstance(e, (connection.InvalidServerError, ComfyError)):
        return str(e)
    if isinstance(e, (httpx.ConnectError, httpx.TimeoutException)):
        return "server unreachable"
    return "not a ComfyUI server"


def _http_brief(e: httpx.HTTPError) -> str:
    """An HTTP failure in a few words: httpx puts the server's URL in some of its messages."""
    if isinstance(e, (httpx.NetworkError, httpx.TimeoutException)):
        return "ComfyUI server unreachable"
    if isinstance(e, httpx.HTTPStatusError):
        return f"ComfyUI answered HTTP {e.response.status_code}"
    return f"ComfyUI request failed ({type(e).__name__})"


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
    folder = _workflows_file().parent / WORKFLOWS_DIR
    folder.mkdir(parents=True, exist_ok=True)  # ready for the first file dropped in
    try:
        reg = get(_workflows_file())
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
            server=_server(None),
            folder=str(folder),
        )
    )


@cli.command()
@_with_common
def doctor(port: int, work: Path | None, server: str | None) -> None:
    """Check the PhotoCraft control link, the ComfyUI server, the workflows and their models."""
    root = work or _default_work()
    comfy = Comfy(_server(server))
    checks = {"work-dir": "ok" if root.is_dir() else f"missing: {root}"}
    checks["photocraft-control"] = _check(lambda: Control(port, root / TOKEN_FILENAME).close())
    checks["comfyui"] = _check(comfy.ping)
    try:
        assigned = list(registry.assignment(registry.load(_workflows_file())).values())
        checks["workflows"] = "ok"
    except registry.WorkflowsError as e:
        assigned, checks["workflows"] = [BUILTIN_WORKFLOW], str(e)
    if BUILTIN_WORKFLOW in assigned:  # your own graphs bring their own models
        checks["builtin-models"] = _check(comfy.find_models)
    ok = all(v == "ok" for v in checks.values())
    for name, state in checks.items():
        click.echo(f"{'ok ' if state == 'ok' else 'FAIL'} {name}: {state}", err=True)
    _emit(DoctorResult(ok=ok, checks=checks))
    sys.exit(0 if ok else 1)


def _check(probe: Callable[[], object]) -> str:
    """Run one check: "ok", or what went wrong."""
    try:
        probe()
    except httpx.HTTPError as e:
        return _http_brief(e)
    except (ControlError, ComfyError, registry.WorkflowsError, KeyError) as e:
        return str(e)
    except ValueError:
        return "not a ComfyUI server"
    return "ok"


def main() -> None:
    """Console entry point for the xp-photocraft command."""
    cli()
