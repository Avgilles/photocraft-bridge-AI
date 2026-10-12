"""xp-photocraft CLI: `fill` / `remove` the selection of a running PhotoCraft, `rerun` a variation,
`connect`, `doctor`, `workflows` / `assign` / `favorite` / `import` / `params`.

One JSON contract line on stdout (``fill@1`` / ``connect@1`` / ``doctor@1`` / ``workflows@1`` /
``import@1`` / ``params@1``), the human report on stderr. PhotoCraft's task bar shows the report's
last line in its status bar: it never carries the server's address.
"""

from __future__ import annotations

import random
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

import click
import httpx

from xp_photocraft import __version__, catalog, connection, params, registry, roundtrip
from xp_photocraft.comfy import Cancelled, Comfy, ComfyError
from xp_photocraft.config import (
    BUILTIN_WORKFLOW,
    CONNECT_TIMEOUT_S,
    CONNECTION_FILE,
    DEFAULT_CONTROL_PORT,
    MAX_VARIATIONS,
    TOKEN_FILENAME,
)
from xp_photocraft.contracts import (
    ConnectResult,
    DoctorResult,
    FillResult,
    VariationResult,
    emit,
)
from xp_photocraft.control import Control, ControlError
from xp_photocraft.engines import ComfyGraph, Engine, EngineError, Runner
from xp_photocraft.local import (
    api_key,
    data_dir,
    default_work,
    http_brief,
    workflow_graph,
    workflows_file,
)
from xp_photocraft.local import server as comfy_url
from xp_photocraft.placeholder import PlacementError

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

_set_option = click.option(
    "--set",
    "fixed",
    multiple=True,
    help="A workflow setting, id=value (see `params`); repeatable.",
)

_vary_option = click.option(
    "--vary",
    "varied",
    multiple=True,
    help="A setting spread over the variations: id=a..b (numbers) or id=a|b|c; repeatable.",
)

_variations_option = click.option(
    "--variations",
    type=click.IntRange(1, MAX_VARIATIONS),
    default=1,
    show_default=True,
    help="Results to make, one seed each, in a group to pick from (each one is billed for a "
    "partner node such as Nano Banana).",
)


_F = TypeVar("_F", bound=Callable[..., Any])


def _with_common(f: _F) -> _F:
    for option in reversed(_common):
        f = option(f)
    return f


Action = Callable[[Control, Engine, list[int], Path, str, list[dict[str, Any]]], roundtrip.Outcome]

# What a run reports on one line, then stops for (a cancel is not a failure: exit 0).
_RUN_ERRORS = (
    Cancelled,
    ControlError,
    ComfyError,
    EngineError,
    registry.WorkflowsError,
    roundtrip.NoSelectionError,
    roundtrip.RunGoneError,
    PlacementError,
    params.SettingsError,
    httpx.HTTPError,
)


@dataclass(frozen=True)
class _Request:
    """What a fill or a remove asks for, from its options."""

    mode: str
    layer: str
    seed: int | None
    variations: int
    fixed: tuple[str, ...]
    varied: tuple[str, ...]
    workflow: str
    port: int
    work: Path | None
    server: str | None


def _engine(
    reg: registry.Registry,
    workflow_id: str,
    server: str | None,
    root: Path,
    settings: list[dict[str, Any]] | None = None,
) -> Engine:
    """Build the workflow's engine; a ComfyUI graph gets this server's model files first."""
    added = reg.workflows.get(workflow_id)
    graph = workflow_graph(reg, workflow_id)
    if added and graph is None:
        return Runner(added.command, root)
    assert graph is not None
    comfy = Comfy(comfy_url(server), api_key=api_key())
    comfy.resolve_models(graph)
    return ComfyGraph(comfy, graph, added.prompt if added else "{prompt}", settings)


def _settings(
    reg: registry.Registry, workflow: str, fixed: dict[str, str], varied: dict[str, str], n: int
) -> list[dict[str, Any]]:
    """Each variation's settings, typed like the workflow's own values."""
    if not fixed and not varied:
        return [{} for _ in range(n)]
    graph = workflow_graph(reg, workflow)
    if graph is None:
        raise params.SettingsError("a workflow run by a command takes no settings")
    return params.settings_for(graph, fixed, varied, n)


def _run(request: _Request, action: Action) -> None:
    root = request.work or default_work()
    seed = random.randrange(2**31) if request.seed is None else request.seed
    seeds = [(seed + k) % 2**31 for k in range(request.variations)]
    workflow = request.workflow
    started = time.perf_counter()
    try:
        reg = registry.load(workflows_file())
        workflow = registry.pick(reg, request.mode, workflow)
        fixed, varied = params.parse_pairs(request.fixed), params.parse_pairs(request.varied)
        settings = _settings(reg, workflow, fixed, varied, len(seeds))
        engine = _engine(reg, workflow, request.server, root, settings)
        _remember(workflow, fixed, varied)
        pc = Control(request.port, root / TOKEN_FILENAME)
        outcome = action(pc, engine, seeds, root, workflow, settings)
    except _RUN_ERRORS as e:
        sys.exit(_failed(request.mode, workflow, seed, e))
    seconds = round(time.perf_counter() - started, 2)
    _report_placed(request.mode, request.layer, workflow, seed, seconds, outcome)


def _failed(mode: str, workflow: str, seed: int, e: BaseException) -> int:
    """Report a run that stopped, on one line; return its exit status (0 for a cancel)."""
    if isinstance(e, Cancelled):
        error = "cancelled (placeholder gone), generation stopped"
        click.echo(f"xp-photocraft {mode}: {error}", err=True)
        result = FillResult(
            ok=False, cancelled=True, mode=mode, workflow=workflow, seed=seed, error=error
        )
        emit(result)
        return 0  # PhotoCraft's task bar shows it as news, not as a failure
    error = http_brief(e) if isinstance(e, httpx.HTTPError) else str(e)
    click.echo(f"xp-photocraft {mode}: {error}", err=True)
    emit(FillResult(ok=False, mode=mode, workflow=workflow, seed=seed, error=error))
    return 1


def _report_placed(
    mode: str, layer: str, workflow: str, seed: int, seconds: float, outcome: roundtrip.Outcome
) -> None:
    rect = outcome.rect
    count = len(outcome.variations)
    placed = f"{count} variation{'s' if count > 1 else ''} of" if outcome.group else "layer"
    click.echo(
        f"xp-photocraft {mode}: {placed} {layer!r} at {rect} in {seconds} s "
        f"({workflow}, seed {seed})",
        err=True,
    )
    emit(
        FillResult(
            ok=True,
            mode=mode,
            workflow=workflow,
            layer=layer,
            bounds=[rect.x, rect.y, rect.width, rect.height],
            seed=seed,
            seconds=seconds,
            run=outcome.run,
            group=outcome.group,
            variations=[VariationResult(layer=v.layer, seed=v.seed) for v in outcome.variations],
        )
    )


def _remember(workflow: str, fixed: dict[str, str], varied: dict[str, str]) -> None:
    """List ``workflow`` first among the recent ones, keep the settings it was given; a run
    never fails for it."""
    try:
        registry.remember(workflows_file(), workflow)
        if fixed or varied:
            registry.remember_settings(workflows_file(), workflow, fixed, varied)
    except (OSError, registry.WorkflowsError) as e:
        click.echo(f"xp-photocraft: recent workflows not saved ({e})", err=True)


@click.group()
@click.version_option(version=__version__, prog_name="xp-photocraft")
def cli() -> None:
    """xp-photocraft: ComfyUI actions on the selection of a running PhotoCraft."""


for _command in catalog.COMMANDS:
    cli.add_command(_command)


@cli.command()
@click.option("--prompt", required=True, help="What to paint inside the selection.")
@click.option("--seed", type=int, default=None, help="Fixed seed (random by default).")
@_variations_option
@_set_option
@_vary_option
@_workflow_option
@_with_common
def fill(
    prompt: str,
    seed: int | None,
    variations: int,
    fixed: tuple[str, ...],
    varied: tuple[str, ...],
    workflow: str,
    port: int,
    work: Path | None,
    server: str | None,
) -> None:
    """Generative Fill: repaint the selection from a prompt, as a new masked layer."""
    layer = "Generative Fill"

    def action(
        pc: Control,
        engine: Engine,
        seeds: list[int],
        root: Path,
        wf: str,
        settings: list[dict[str, Any]],
    ) -> roundtrip.Outcome:
        return roundtrip.fill_selection(pc, engine, prompt, seeds, root, layer, wf, settings)

    request = _Request("fill", layer, seed, variations, fixed, varied, workflow, port, work, server)
    _run(request, action)


@cli.command()
@click.option("--seed", type=int, default=None, help="Fixed seed (random by default).")
@_variations_option
@_set_option
@_vary_option
@_workflow_option
@_with_common
def remove(
    seed: int | None,
    variations: int,
    fixed: tuple[str, ...],
    varied: tuple[str, ...],
    workflow: str,
    port: int,
    work: Path | None,
    server: str | None,
) -> None:
    """Remove (AI): erase what is selected and rebuild the background, as a new masked layer."""
    layer = "Remove (AI)"

    def action(
        pc: Control,
        engine: Engine,
        seeds: list[int],
        root: Path,
        wf: str,
        settings: list[dict[str, Any]],
    ) -> roundtrip.Outcome:
        return roundtrip.remove_selection(pc, engine, seeds, root, layer, wf, settings)

    request = _Request(
        "remove", layer, seed, variations, fixed, varied, workflow, port, work, server
    )
    _run(request, action)


@cli.command()
@click.option("--run", "run_id", required=True, help="The run, as the variation's layer names it.")
@click.option("--seed", type=int, required=True, help="The variation's seed.")
@click.option("--group", type=int, required=True, help="The group of variations (a layer id).")
@click.option("--prompt", default=None, help="A new prompt (default: the run's).")
@_set_option
@_with_common
def rerun(
    run_id: str,
    seed: int,
    group: int,
    prompt: str | None,
    fixed: tuple[str, ...],
    port: int,
    work: Path | None,
    server: str | None,
) -> None:
    """Run a variation again into its group: its seed and settings, maybe a new prompt or setting.

    It uses the run's own region and mask, kept beside a saved document (or, for a document
    never saved, among the newest runs of the work dir).
    """
    root = work or default_work()
    mode, layer, workflow = "fill", "Generative Fill", ""
    started = time.perf_counter()
    try:
        pc = Control(port, root / TOKEN_FILENAME)
        earlier = roundtrip.find_run(pc, root, run_id, group)
        meta = earlier.meta
        mode, layer, workflow = str(meta["mode"]), str(meta["layer"]), str(meta["workflow"])
        reg = registry.load(workflows_file())
        workflow = registry.pick(reg, mode, workflow)
        own = _settings(reg, workflow, params.parse_pairs(fixed), {}, 1)[0]
        settings = earlier.settings(seed) | own
        engine = _engine(reg, workflow, server, root, [settings])
        new_prompt = str(meta["prompt"]) if prompt is None else prompt
        outcome = roundtrip.rerun_variation(pc, engine, root, earlier, seed, new_prompt, settings)
    except _RUN_ERRORS as e:
        sys.exit(_failed(mode, workflow, seed, e))
    _report_placed(mode, layer, workflow, seed, round(time.perf_counter() - started, 2), outcome)


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
        emit(ConnectResult(ok=False, error=_brief(e)))
        sys.exit(1)
    connection.save(data_dir() / CONNECTION_FILE, server)
    # Your own graphs may need other models: the built-in ones are reported, not required.
    builtin = "OK" if _check(comfy.find_models) == "ok" else "missing (see doctor)"
    click.echo(f"ComfyUI connected - built-in Qwen models {builtin}", err=True)
    emit(ConnectResult(ok=True, server=server))


def _brief(e: Exception) -> str:
    """Say what went wrong without the server's address (it ends up on screen)."""
    if isinstance(e, (connection.InvalidServerError, ComfyError)):
        return str(e)
    if isinstance(e, (httpx.ConnectError, httpx.TimeoutException)):
        return "server unreachable"
    return "not a ComfyUI server"


@cli.command()
@_with_common
def doctor(port: int, work: Path | None, server: str | None) -> None:
    """Check the PhotoCraft control link, the ComfyUI server, the workflows and their models."""
    root = work or default_work()
    comfy = Comfy(comfy_url(server))
    checks = {"work-dir": "ok" if root.is_dir() else f"missing: {root}"}
    checks["photocraft-control"] = _check(lambda: Control(port, root / TOKEN_FILENAME).close())
    checks["comfyui"] = _check(comfy.ping)
    try:
        assigned = list(registry.assignment(registry.load(workflows_file())).values())
        checks["workflows"] = "ok"
    except registry.WorkflowsError as e:
        assigned, checks["workflows"] = [BUILTIN_WORKFLOW], str(e)
    if BUILTIN_WORKFLOW in assigned:  # your own graphs bring their own models
        checks["builtin-models"] = _check(comfy.find_models)
    ok = all(v == "ok" for v in checks.values())
    for name, state in checks.items():
        click.echo(f"{'ok ' if state == 'ok' else 'FAIL'} {name}: {state}", err=True)
    emit(DoctorResult(ok=ok, checks=checks))
    sys.exit(0 if ok else 1)


def _check(probe: Callable[[], object]) -> str:
    """Run one check: "ok", or what went wrong."""
    try:
        probe()
    except httpx.HTTPError as e:
        return http_brief(e)
    except (ControlError, ComfyError, registry.WorkflowsError, KeyError) as e:
        return str(e)
    except ValueError:
        return "not a ComfyUI server"
    return "ok"


def main() -> None:
    """Console entry point for the xp-photocraft command."""
    cli()
