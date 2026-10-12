"""The catalog's commands: `workflows`, `assign`, `favorite`, `import`, `params`.

Each prints one contract line (``workflows@1``, ``import@1``, ``params@1``); PhotoCraft XP's menu
and task bar are built from them.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import click
import httpx

from xp_photocraft import params, registry
from xp_photocraft.comfy import Comfy
from xp_photocraft.config import ACTIONS, CONNECT_TIMEOUT_S, WORKFLOW_FILE, WORKFLOWS_DIR
from xp_photocraft.contracts import (
    ImportResult,
    ParamsResult,
    WorkflowChoice,
    WorkflowsResult,
    emit,
)
from xp_photocraft.engines import missing_tags
from xp_photocraft.local import http_brief, server, workflow_graph, workflows_file


@click.command("workflows")
def list_workflows() -> None:
    """List the workflows and the one each action runs."""
    _emit_workflows(registry.load)


@click.command()
@click.argument("action", type=click.Choice(ACTIONS))
@click.argument("workflow")
def assign(action: str, workflow: str) -> None:
    """Make ACTION (fill, remove) run WORKFLOW from now on."""
    _emit_workflows(lambda path: registry.assign(path, action, workflow))


@click.command()
@click.argument("workflow")
@click.option("--off", is_flag=True, help="Unstar it instead.")
def favorite(workflow: str, off: bool) -> None:
    """Star WORKFLOW: menus list the starred ones first."""
    _emit_workflows(lambda path: registry.favorite(path, workflow, not off))


@click.command("import")
@click.argument("source", type=click.Path(exists=True, path_type=Path))
@click.option("--category", default="", help="The menu it goes in (a folder; none by default).")
@click.option("--name", default="", help="Its name in the menus (default: the file's name).")
@click.option("--replace", is_flag=True, help="Replace a workflow of the same name.")
def import_workflow(source: Path, category: str, name: str, replace: bool) -> None:
    """Add SOURCE to the catalog: a graph saved with Export (API), or a workflow folder.

    A ``<name>.app.json`` beside the export (saved from ComfyUI's App Builder) comes along.
    """
    try:
        graph_file = source / WORKFLOW_FILE if source.is_dir() else source
        missing = missing_tags(registry.load_graph(graph_file))
        if missing:
            raise registry.WorkflowsError(
                f"no node titled {' or '.join(missing)}: title them in ComfyUI, then export again"
            )
        workflow_id = registry.import_workflow(workflows_file(), source, category, name, replace)
    except registry.WorkflowsError as e:
        exists = "already in the catalog" in str(e)
        click.echo(f"xp-photocraft import: {e}", err=True)
        emit(ImportResult(ok=False, exists=exists, error=str(e)))
        sys.exit(1)
    warnings = _server_lacks(registry.load_graph(graph_file))
    for warning in warnings:
        click.echo(f"xp-photocraft import: {warning}", err=True)
    click.echo(f"xp-photocraft import: {workflow_id!r} added", err=True)
    emit(ImportResult(ok=True, id=workflow_id, warnings=warnings))


@click.command("params")
@click.argument("workflow")
def list_params(workflow: str) -> None:
    """The settings WORKFLOW's app shows (its App Builder save), and those it last ran with."""
    try:
        reg = registry.load(workflows_file())
        registry.pick(reg, ACTIONS[0], workflow)  # a known workflow, or WorkflowsError
        added, graph = reg.workflows.get(workflow), workflow_graph(reg, workflow)
        if added is None or not added.app or graph is None:
            emit(ParamsResult(ok=True, workflow=workflow))
            return
        app = json.loads((workflows_file().parent / added.app).read_text(encoding="utf-8"))
    except (registry.WorkflowsError, OSError, ValueError) as e:
        click.echo(f"xp-photocraft params: {e}", err=True)
        emit(ParamsResult(ok=False, workflow=workflow, error=str(e)))
        sys.exit(1)
    spec = _SpecOrNothing(Comfy(server(None), timeout=CONNECT_TIMEOUT_S))
    found, warnings = params.app_params(app, graph, spec)
    last = reg.settings.get(workflow, {})
    emit(
        ParamsResult(
            ok=True,
            workflow=workflow,
            params=[p.as_dict() for p in found],
            set=last.get("set", {}),
            vary=last.get("vary", {}),
            warnings=warnings + spec.warnings,
        )
    )


COMMANDS = [list_workflows, assign, favorite, import_workflow, list_params]


class _SpecOrNothing:
    """A node's input spec from the server, or None once the server failed (asked once)."""

    def __init__(self, comfy: Comfy) -> None:
        self._comfy, self._down, self.warnings = comfy, False, []  # type: ignore[var-annotated]

    def __call__(self, class_type: str) -> dict[str, Any] | None:
        if self._down:
            return None
        try:
            return self._comfy.spec(class_type)
        except (httpx.HTTPError, ValueError, KeyError) as e:
            self._down = True
            brief = http_brief(e) if isinstance(e, httpx.HTTPError) else "not a ComfyUI server"
            self.warnings.append(f"settings without ranges or choices: {brief}")
            return None


def _server_lacks(graph: dict[str, Any]) -> list[str]:
    """What the saved server lacks to run ``graph``; a warning, never a refusal."""
    try:
        return Comfy(server(None), timeout=CONNECT_TIMEOUT_S).missing(graph)
    except (httpx.HTTPError, ValueError, KeyError) as e:
        brief = http_brief(e) if isinstance(e, httpx.HTTPError) else "not a ComfyUI server"
        return [f"models not checked: {brief}"]


def _emit_workflows(get: Callable[[Path], registry.Registry]) -> None:
    folder = workflows_file().parent / WORKFLOWS_DIR
    folder.mkdir(parents=True, exist_ok=True)  # ready for the first file dropped in
    try:
        reg = get(workflows_file())
    except registry.WorkflowsError as e:
        click.echo(f"xp-photocraft workflows: {e}", err=True)
        emit(WorkflowsResult(ok=False, error=str(e)))
        sys.exit(1)
    labels, assigned = registry.labels(reg), registry.assignment(reg)
    for action, workflow_id in assigned.items():
        click.echo(f"{action} -> {workflow_id} ({labels[workflow_id]})", err=True)
    known = set(labels)
    emit(
        WorkflowsResult(
            ok=True,
            workflows=[_choice(reg, k, v) for k, v in labels.items()],
            assign=assigned,
            favorites=[f for f in reg.favorites if f in known],
            recent=[r for r in reg.recent if r in known],
            server=server(None),
            folder=str(folder),
        )
    )


def _choice(reg: registry.Registry, workflow_id: str, label: str) -> WorkflowChoice:
    workflow = reg.workflows.get(workflow_id)
    return WorkflowChoice(
        id=workflow_id,
        label=label,
        category=workflow.category if workflow else "",
        settings=bool(workflow and workflow.app),
    )
