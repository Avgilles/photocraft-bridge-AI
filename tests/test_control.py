"""The control client reconnects a connection PhotoCraft would have dropped for idling."""

from __future__ import annotations

import json
import socket
import threading
import time
from pathlib import Path

import pytest

from xp_photocraft import control


def _fake_photocraft(server: socket.socket, accepted: list[int]) -> None:
    """Answer ok to every JSON line, on as many connections as come."""
    while True:
        try:
            conn, _ = server.accept()
        except OSError:
            return
        accepted.append(1)
        with conn, conn.makefile("rw", encoding="utf-8") as lines:
            for line in lines:
                lines.write(
                    json.dumps({"id": json.loads(line)["id"], "ok": True, "result": {}}) + "\n"
                )
                lines.flush()


@pytest.mark.parametrize(("idle_limit", "connections"), [(3600.0, 1), (-1.0, 2)])
def test_call_reconnects_only_after_idling(
    idle_limit: float, connections: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server = socket.create_server(("127.0.0.1", 0))
    accepted: list[int] = []
    threading.Thread(target=_fake_photocraft, args=(server, accepted), daemon=True).start()
    token = tmp_path / "control.token"
    token.write_text("t", encoding="utf-8")
    monkeypatch.setattr(control, "CONTROL_IDLE_RECONNECT_S", idle_limit)

    pc = control.Control(server.getsockname()[1], token)
    pc.cmd("document.inspect")
    pc.close()
    server.close()

    assert len(accepted) == connections


def test_exclusive_lets_one_run_edit_photocraft_at_a_time(tmp_path: Path) -> None:
    order: list[str] = []
    inside = threading.Event()

    def first() -> None:
        with control.exclusive(tmp_path):
            inside.set()
            time.sleep(0.3)  # the second run asks meanwhile
            order.append("first done")

    thread = threading.Thread(target=first)
    thread.start()
    inside.wait()
    with control.exclusive(tmp_path):
        order.append("second in")
    thread.join()

    assert order == ["first done", "second in"]
