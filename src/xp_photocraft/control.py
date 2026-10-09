"""PhotoCraft's control protocol: JSON lines over loopback TCP, one bearer token.

The only module that opens a socket to PhotoCraft (docs/control-protocol.md upstream).
"""

from __future__ import annotations

import json
import socket
from pathlib import Path
from typing import Any

from xp_photocraft.config import CONTROL_HOST, CONTROL_TIMEOUT_S


class ControlError(RuntimeError):
    """PhotoCraft answered a request with ``ok: false``, or the link broke."""


class Control:
    """One authenticated connection to a running ``photocraft --control <port>``."""

    def __init__(self, port: int, token_file: Path) -> None:
        if not token_file.is_file():
            raise ControlError(
                f"no control token at {token_file}: is PhotoCraft running with --control?"
            )
        try:
            self._sock = socket.create_connection((CONTROL_HOST, port), timeout=CONTROL_TIMEOUT_S)
        except OSError as e:
            raise ControlError(f"PhotoCraft does not answer on {CONTROL_HOST}:{port}: {e}") from e
        self._lines = self._sock.makefile("r", encoding="utf-8")
        self._next_id = 0
        self.call("auth", {"token": token_file.read_text(encoding="utf-8").strip()})

    def call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        """Send one request and return its ``result``; raise ControlError on ``ok: false``."""
        self._next_id += 1
        line = json.dumps({"id": self._next_id, "method": method, "params": params or {}})
        try:
            self._sock.sendall(line.encode("utf-8") + b"\n")
            reply = self._read_reply(self._next_id)
        except OSError as e:
            raise ControlError(f"{method}: connection lost ({e}); the edit may have run") from e
        if not reply.get("ok"):
            raise ControlError(f"{method}: {reply.get('error')}")
        return reply.get("result")

    def cmd(self, command: str, params: dict[str, Any] | None = None) -> Any:
        """Run one engine command by id (``engine.execute``)."""
        return self.call("engine.execute", {"command": command, "params": params or {}})

    def close(self) -> None:
        """Close the connection."""
        self._sock.close()

    def _read_reply(self, request_id: int) -> dict[str, Any]:
        while True:
            line = self._lines.readline()
            if not line:
                raise OSError("PhotoCraft closed the connection")
            reply: dict[str, Any] = json.loads(line)
            # Lines with another id are stale replies to requests that timed out.
            if reply.get("id") == request_id:
                return reply
