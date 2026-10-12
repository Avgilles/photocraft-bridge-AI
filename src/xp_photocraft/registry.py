"""The user's workflows and the one each action runs, from ``workflows.json``.

The built-in ``qwen-edit`` is always there, and so is every workflow of the ``workflows`` folder
beside the file: a folder holding ``workflow.json`` (a graph exported with *Export (API)*, whose
nodes carry ``pc:*`` titles, see ``engines.ComfyGraph``) and optionally ``app.json`` (the same
graph saved from ComfyUI's App Builder: the settings it shows). The folder's name is the
workflow's name and id; a folder above it, if any, is its category (one level)::

    workflows/
      Local/Qwen Edit 2511 (ComfyUI)/workflow.json
      Cloud/Nano Banana 2.1 (comfy.org)/workflow.json, app.json
      Flux Fill/workflow.json
      Old export.json            <- a 0.1 catalog: a loose export, no category

The file assigns one workflow per action, keeps favorites and the recent ones, and may add
workflows by hand: a graph elsewhere, or an external command speaking
``xp-photocraft/runner@1``::

    {
      "workflows": {"my-cloud": {"label": "My cloud model", "command": ["python", "run.py"]}},
      "assign": {"fill": "Flux Fill"},
      "favorites": ["Flux Fill"],
      "recent": ["Flux Fill", "qwen-edit"]
    }
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from xp_photocraft.config import (
    ACTIONS,
    APP_FILE,
    BUILTIN_LABEL,
    BUILTIN_WORKFLOW,
    RECENT_MAX,
    WORKFLOW_FILE,
    WORKFLOWS_DIR,
)


class Workflow(BaseModel):
    """An added workflow: a ComfyUI graph file, or an external command."""

    model_config = ConfigDict(extra="forbid")

    label: str
    # An API-format graph; a relative path is relative to workflows.json.
    graph: str = ""
    command: list[str] = []
    # What the graph's pc:prompt node receives; "{prompt}" is the user's prompt.
    prompt: str = "{prompt}"
    # Its folder's parent in the workflows folder (a menu of its own), "" for none.
    category: str = ""
    # Its App Builder save, relative to workflows.json; "" for none.
    app: str = ""

    @model_validator(mode="after")
    def _graph_or_command(self) -> Workflow:
        if bool(self.graph) == bool(self.command):
            raise ValueError("give a graph or a command (one of them)")
        return self


class Registry(BaseModel):
    """The added workflows and the action → workflow assignment."""

    model_config = ConfigDict(extra="forbid")

    workflows: dict[str, Workflow] = {}
    assign: dict[str, str] = {}
    favorites: list[str] = []
    recent: list[str] = []
    # The settings each workflow last ran with: {"set": {id: text}, "vary": {id: text}}.
    settings: dict[str, dict[str, dict[str, str]]] = {}


class WorkflowsError(ValueError):
    """``workflows.json`` or a graph it names is unreadable, or names an unknown workflow."""


def load(path: Path) -> Registry:
    """Return ``path``'s registry plus every workflow of the ``workflows`` folder beside it.

    An entry of ``workflows.json`` with the same id wins. The workflow named after the built-in
    one (``Qwen Edit 2511 (ComfyUI)``, shipped with a release) *is* the built-in one: same id, one
    menu entry, and editing it changes the default.
    """
    registry = _read(path)
    for workflow_id, workflow in _catalog(path.parent / WORKFLOWS_DIR).items():
        registry.workflows.setdefault(workflow_id, workflow)
    return registry


def _catalog(root: Path) -> dict[str, Workflow]:
    """The workflows folder's workflows by id, sorted by name; a folder beats a loose file."""
    found: dict[str, Workflow] = {}
    for graph in sorted(root.glob("*.json")):
        found[_id(graph.stem)] = Workflow(label=graph.stem, graph=_relative(root, graph))
    for graph in sorted([*root.glob(f"*/{WORKFLOW_FILE}"), *root.glob(f"*/*/{WORKFLOW_FILE}")]):
        folder = graph.parent
        app = folder / APP_FILE
        found[_id(folder.name)] = Workflow(
            label=folder.name,
            graph=_relative(root, graph),
            category=folder.parent.name if folder.parent != root else "",
            app=_relative(root, app) if app.is_file() else "",
        )
    return dict(sorted(found.items(), key=lambda item: item[1].label.lower()))


def _id(label: str) -> str:
    return BUILTIN_WORKFLOW if label == BUILTIN_LABEL else label


def _relative(root: Path, file: Path) -> str:
    # Relative to workflows.json, which sits beside the workflows folder.
    return f"{WORKFLOWS_DIR}/{file.relative_to(root).as_posix()}"


def _read(path: Path) -> Registry:
    if not path.is_file():
        return Registry()
    try:
        return Registry.model_validate_json(path.read_text(encoding="utf-8"))
    except OSError as e:
        raise WorkflowsError(f"cannot read {path.name}: {e.strerror}") from e
    except ValidationError as e:
        # One line: the task bar shows the last line of the report.
        first = e.errors()[0]
        where = ".".join(str(part) for part in first["loc"])
        raise WorkflowsError(f"{path.name}: {where + ': ' if where else ''}{first['msg']}") from e


def load_graph(path: Path) -> dict[str, Any]:
    """Return the API-format graph in ``path`` (relative paths are resolved by the caller)."""
    try:
        graph = json.loads(path.read_text(encoding="utf-8"))
    except OSError as e:
        raise WorkflowsError(f"cannot read {path.name}: {e.strerror}") from e
    except ValueError as e:
        raise WorkflowsError(f"{path.name} is not JSON") from e
    if not isinstance(graph, dict) or isinstance(graph.get("nodes"), list):
        raise WorkflowsError(f"{path.name} is not an API workflow: save it with Export (API)")
    return graph


def labels(registry: Registry) -> dict[str, str]:
    """Return every workflow's label by id, the built-in first."""
    return {BUILTIN_WORKFLOW: BUILTIN_LABEL} | {k: w.label for k, w in registry.workflows.items()}


def assignment(registry: Registry) -> dict[str, str]:
    """Return the workflow id each action runs."""
    return {action: registry.assign.get(action, BUILTIN_WORKFLOW) for action in ACTIONS}


def pick(registry: Registry, action: str, override: str) -> str:
    """Return the workflow id for ``action``: ``override`` if given, else the assigned one."""
    workflow_id = override or assignment(registry)[action]
    if workflow_id not in labels(registry):
        raise WorkflowsError(f"unknown workflow {workflow_id!r}")
    return workflow_id


def assign(path: Path, action: str, workflow_id: str) -> Registry:
    """Make ``action`` run ``workflow_id`` from now on, and save it."""
    saved = _read(path)  # the folder's workflows stay in the folder
    saved.assign[action] = pick(load(path), action, workflow_id)
    _write(path, saved)
    return load(path)


def favorite(path: Path, workflow_id: str, on: bool) -> Registry:
    """Star ``workflow_id`` (``on``) or unstar it, and save it."""
    saved = _read(path)
    pick(load(path), ACTIONS[0], workflow_id)  # a known workflow, or WorkflowsError
    others = [f for f in saved.favorites if f != workflow_id]
    saved.favorites = [*others, workflow_id] if on else others
    _write(path, saved)
    return load(path)


def remember(path: Path, workflow_id: str) -> None:
    """Put ``workflow_id`` first among the recent workflows, and save it."""
    saved = _read(path)
    others = [r for r in saved.recent if r != workflow_id]
    saved.recent = [workflow_id, *others][:RECENT_MAX]
    _write(path, saved)


def remember_settings(
    path: Path, workflow_id: str, fixed: dict[str, str], varied: dict[str, str]
) -> None:
    """Keep the settings ``workflow_id`` was given (``--set``, ``--vary``), for next time."""
    saved = _read(path)
    saved.settings[workflow_id] = {"set": fixed, "vary": varied}
    _write(path, saved)


def import_workflow(
    path: Path, source: Path, category: str = "", name: str = "", replace: bool = False
) -> str:
    """Copy an exported workflow into the catalog, as a folder of its own; return its id.

    ``source`` is an API export (``Flux Fill.json``, with ``Flux Fill.app.json`` beside it if
    there is one) or a workflow folder. A name already in the catalog is refused unless
    ``replace``: the old copy goes, whatever its category. The caller checks the graph's tags
    and models; this only checks it is an API workflow.
    """
    files = _workflow_files(source)
    label = (name or (source.name if source.is_dir() else source.stem)).strip()
    for part in (label, category):
        if part in (".", "..") or any(c in part for c in '\\/:*?"<>|'):
            raise WorkflowsError(f"{part!r} cannot be a folder name")
    if not label:
        raise WorkflowsError("a workflow needs a name")
    root = path.parent / WORKFLOWS_DIR
    existing = _catalog(root).get(_id(label))
    if existing and not replace:
        raise WorkflowsError(f"{label!r} is already in the catalog")
    if existing:  # the old copy goes, a folder or a 0.1 loose file
        old = path.parent / existing.graph
        if old.name == WORKFLOW_FILE:
            shutil.rmtree(old.parent)
        else:
            old.unlink()
    target = root / category / label if category else root / label
    target.mkdir(parents=True, exist_ok=True)
    for name_in_folder, content in files.items():
        (target / name_in_folder).write_bytes(content)
    return _id(label)


def _workflow_files(source: Path) -> dict[str, bytes]:
    """The files an imported workflow's folder gets, read before anything is replaced."""
    if source.is_dir():
        load_graph(source / WORKFLOW_FILE)
        return {f.name: f.read_bytes() for f in source.iterdir() if f.is_file()}
    load_graph(source)
    files = {WORKFLOW_FILE: source.read_bytes()}
    app = source.with_name(f"{source.stem}.app.json")
    if app.is_file():
        files[APP_FILE] = app.read_bytes()
    return files


def _write(path: Path, saved: Registry) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # exclude_defaults: the file keeps the shape the user wrote.
    path.write_text(saved.model_dump_json(indent=2, exclude_defaults=True) + "\n", "utf-8")
