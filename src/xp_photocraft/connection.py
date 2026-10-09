"""The saved ComfyUI connection: one URL in a small JSON file, outside any repository."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from urllib.parse import urlsplit

from xp_photocraft.config import DEFAULT_COMFY_URL

logger = logging.getLogger(__name__)


class InvalidServerError(ValueError):
    """The text given is not an http(s) URL with a host."""


def normalize(url: str) -> str:
    """Return ``url`` as ``scheme://host[:port][/path]``; ``http://`` is assumed when missing."""
    text = url.strip()
    if "://" not in text:
        text = f"http://{text}"
    parts = urlsplit(text)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise InvalidServerError("expected an address like http://127.0.0.1:8188")
    return text.rstrip("/")


def load(path: Path) -> str:
    """Return the saved ComfyUI URL, or ComfyUI's own default when none is saved."""
    if not path.is_file():
        return DEFAULT_COMFY_URL
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("unreadable connection file %s, using the default", path)
        return DEFAULT_COMFY_URL
    url = data.get("comfy_url") if isinstance(data, dict) else None
    return url if isinstance(url, str) and url else DEFAULT_COMFY_URL


def save(path: Path, url: str) -> None:
    """Save ``url`` as the connection every command uses."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"comfy_url": url}, indent=2) + "\n", encoding="utf-8")
