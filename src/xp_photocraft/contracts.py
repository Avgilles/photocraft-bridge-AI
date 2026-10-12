"""The JSON lines the CLI prints on stdout, one per command: what PhotoCraft XP reads.

Each carries its ``contract`` name and version; a field is only ever added, with a default, so an
older PhotoCraft XP keeps reading a newer bridge.
"""

from __future__ import annotations

import sys

from pydantic import BaseModel


class VariationResult(BaseModel):
    """One placed result: its layer id and its seed."""

    layer: int
    seed: int


class FillResult(BaseModel):
    """``fill@1``: what was placed, where, from which seed(s).

    ``cancelled``: the artist deleted the placeholder (or closed its document), so nothing was
    placed (``ok`` false); not a failure, the exit status is 0. A run of variations names its
    ``group`` (a layer id, 0 for a single layer) and lists them; ``seed`` is the first one's.
    """

    contract: str = "fill@1"
    ok: bool
    cancelled: bool = False
    mode: str
    workflow: str = ""
    layer: str = ""
    bounds: list[int] = []
    seed: int = 0
    seconds: float = 0.0
    run: str = ""
    group: int = 0
    variations: list[VariationResult] = []
    error: str = ""


class ConnectResult(BaseModel):
    """``connect@1``: whether a ComfyUI server answered, and was saved."""

    contract: str = "connect@1"
    ok: bool
    server: str = ""
    error: str = ""


class WorkflowChoice(BaseModel):
    """One workflow the UI can offer, and the menu it goes in ("" for none)."""

    id: str
    label: str
    category: str = ""


class WorkflowsResult(BaseModel):
    """``workflows@1``: every workflow, the one each action runs, the starred and recent ones."""

    contract: str = "workflows@1"
    ok: bool
    workflows: list[WorkflowChoice] = []
    assign: dict[str, str] = {}
    favorites: list[str] = []
    recent: list[str] = []
    server: str = ""
    # Where to drop exported graphs (the UI opens it; never shown).
    folder: str = ""
    error: str = ""


class ImportResult(BaseModel):
    """``import@1``: the workflow added to the catalog, and what the server lacks for it."""

    contract: str = "import@1"
    ok: bool
    id: str = ""
    # The name exists already: run again with --replace once the artist agreed.
    exists: bool = False
    warnings: list[str] = []
    error: str = ""


class DoctorResult(BaseModel):
    """``doctor@1``: one line per check."""

    contract: str = "doctor@1"
    ok: bool
    checks: dict[str, str]


def emit(contract: BaseModel) -> None:
    """Print ``contract`` as the command's one JSON line."""
    # Bytes, not print(): print() writes CRLF on Windows and breaks a line contract.
    sys.stdout.buffer.write(contract.model_dump_json().encode("utf-8") + b"\n")
    sys.stdout.buffer.flush()
