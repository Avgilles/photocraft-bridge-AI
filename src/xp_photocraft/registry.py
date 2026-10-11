"""The user's workflows and the one each action runs, from ``workflows.json``.

The built-in ``qwen-edit`` is always there, and so is every graph dropped in the ``workflows``
folder beside the file (named after its file). The file adds workflows — a ComfyUI graph exported
with *Export (API)* whose nodes carry ``pc:*`` titles (see ``engines.ComfyGraph``), run on the
saved connection; or an external command speaking ``xp-photocraft/runner@1`` — and assigns one
workflow per action::

    {
      "workflows": {
        "flux-fill": {"label": "Flux Fill", "graph": "flux_fill_api.json"},
        "my-cloud": {"label": "My cloud model", "command": ["python", "C:/tools/run.py"]}
      },
      "assign": {"fill": "flux-fill"}
    }
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from xp_photocraft.config import ACTIONS, BUILTIN_LABEL, BUILTIN_WORKFLOW, WORKFLOWS_DIR


class Workflow(BaseModel):
    """An added workflow: a ComfyUI graph file, or an external command."""

    model_config = ConfigDict(extra="forbid")

    label: str
    # An API-format graph; a relative path is relative to workflows.json.
    graph: str = ""
    command: list[str] = []
    # What the graph's pc:prompt node receives; "{prompt}" is the user's prompt.
    prompt: str = "{prompt}"

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


class WorkflowsError(ValueError):
    """``workflows.json`` or a graph it names is unreadable, or names an unknown workflow."""


def load(path: Path) -> Registry:
    """Return ``path``'s registry plus every graph in the ``workflows`` folder beside it.

    A dropped file is a workflow named after it (``Flux Fill.json`` → ``Flux Fill``); an entry
    of ``workflows.json`` with the same id wins. The file named after the built-in workflow
    (``Qwen Edit 2511 (ComfyUI).json``, shipped with a release) *is* the built-in one: same id,
    one menu entry, and editing it changes the default.
    """
    registry = _read(path)
    for graph in sorted((path.parent / WORKFLOWS_DIR).glob("*.json"), key=lambda p: p.stem.lower()):
        workflow_id = BUILTIN_WORKFLOW if graph.stem == BUILTIN_LABEL else graph.stem
        registry.workflows.setdefault(
            workflow_id, Workflow(label=graph.stem, graph=f"{WORKFLOWS_DIR}/{graph.name}")
        )
    return registry


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
    path.parent.mkdir(parents=True, exist_ok=True)
    # exclude_defaults: the file keeps the shape the user wrote.
    path.write_text(saved.model_dump_json(indent=2, exclude_defaults=True) + "\n", "utf-8")
    return load(path)
