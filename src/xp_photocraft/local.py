"""The bridge's local state: its data folder, the saved server, the comfy.org key, a graph.

Read where it is used, never at import: a portable release keeps it in ``data`` beside the
executable, a source install in the user's data folder.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import httpx

from xp_photocraft import connection, registry
from xp_photocraft.config import (
    APP_DIR,
    BUILTIN_GRAPH,
    CONNECTION_FILE,
    PORTABLE_DATA_DIR,
    PORTABLE_MARKER,
    WORK_DIR,
    WORKFLOWS_FILE,
)

# A comfy.org API key, for graphs with partner nodes (Nano Banana, ...) on your own ComfyUI.
API_KEY_ENV = "XP_PHOTOCRAFT_COMFY_API_KEY"
# Or in the data folder's .env file (KEY=value lines; the release ships a .env.example).
DOTENV_FILE = ".env"


def data_dir() -> Path:
    """``data`` next to a portable executable; else the user's data folder."""
    # The single-file build; from a virtualenv this is its python, which carries no marker.
    beside = Path(sys.executable).resolve().parent
    if (beside / PORTABLE_MARKER).is_file():
        return beside / PORTABLE_DATA_DIR
    # %LOCALAPPDATA% on Windows; elsewhere the XDG data folder (~/.local/share, macOS included).
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_DATA_HOME")
    return (Path(base) if base else Path.home() / ".local" / "share") / APP_DIR


def default_work() -> Path:
    """The work dir PhotoCraft gets as its automation roots."""
    return data_dir() / WORK_DIR


def workflows_file() -> Path:
    """``workflows.json``, beside the workflows folder."""
    return data_dir() / WORKFLOWS_FILE


def api_key() -> str:
    """The comfy.org API key: the environment variable, else the data folder's .env file."""
    if os.environ.get(API_KEY_ENV):
        return os.environ[API_KEY_ENV]
    return _dotenv(data_dir() / DOTENV_FILE).get(API_KEY_ENV, "")


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


def server(override: str | None) -> str:
    """``override``, else the connection saved by ``connect``, else ComfyUI's own default."""
    return override or connection.load(data_dir() / CONNECTION_FILE)


def workflow_graph(reg: registry.Registry, workflow_id: str) -> dict[str, Any] | None:
    """The workflow's API graph; None for an external command."""
    added = reg.workflows.get(workflow_id)
    if added and added.command:
        return None
    if added is None:  # the built-in graph shipped in the package
        return registry.load_graph(Path(__file__).with_name(BUILTIN_GRAPH))
    return registry.load_graph(workflows_file().parent / added.graph)


def http_brief(e: httpx.HTTPError) -> str:
    """An HTTP failure in a few words: httpx puts the server's URL in some of its messages."""
    if isinstance(e, (httpx.NetworkError, httpx.TimeoutException)):
        return "ComfyUI server unreachable"
    if isinstance(e, httpx.HTTPStatusError):
        return f"ComfyUI answered HTTP {e.response.status_code}"
    return f"ComfyUI request failed ({type(e).__name__})"
