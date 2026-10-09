"""The user's workflows and the one each action runs, from ``workflows.json``.

The built-in ``qwen-edit`` is always there. The file declares external commands (each speaks
``xp-photocraft/runner@1``, see ``engines``) and assigns one workflow per action::

    {
      "workflows": {"my-model": {"label": "My model", "command": ["python", "C:/tools/run.py"]}},
      "assign": {"fill": "my-model"}
    }
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from xp_photocraft.config import ACTIONS, BUILTIN_LABEL, BUILTIN_WORKFLOW


class Workflow(BaseModel):
    """An external workflow: a label for the UI and the command that runs it."""

    model_config = ConfigDict(extra="forbid")

    label: str
    command: list[str] = Field(min_length=1)


class Registry(BaseModel):
    """The declared workflows and the action → workflow assignment."""

    model_config = ConfigDict(extra="forbid")

    workflows: dict[str, Workflow] = {}
    assign: dict[str, str] = {}


class WorkflowsError(ValueError):
    """``workflows.json`` is unreadable or names a workflow that does not exist."""


def load(path: Path) -> Registry:
    """Return the registry saved in ``path``; empty (built-in only) when there is none."""
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
    registry = load(path)
    registry.assign[action] = pick(registry, action, workflow_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(registry.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return registry
