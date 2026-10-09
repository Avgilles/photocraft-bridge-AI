"""The saved connection and the `connect` command, with ComfyUI faked."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from click.testing import CliRunner

from xp_photocraft import cli, connection
from xp_photocraft.comfy import ComfyError
from xp_photocraft.config import DEFAULT_COMFY_URL


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("192.168.1.20:8188", "http://192.168.1.20:8188"),
        ("  http://gpu-box:8188/ ", "http://gpu-box:8188"),
        ("https://comfy.example/api", "https://comfy.example/api"),
    ],
)
def test_normalize_adds_scheme_and_trims(given: str, expected: str) -> None:
    assert connection.normalize(given) == expected


@pytest.mark.parametrize("given", ["", "ftp://host", "http://"])
def test_normalize_rejects_non_http_urls(given: str) -> None:
    with pytest.raises(connection.InvalidServerError):
        connection.normalize(given)


def test_load_falls_back_to_default_when_missing_or_broken(tmp_path: Path) -> None:
    path = tmp_path / "connection.json"
    assert connection.load(path) == DEFAULT_COMFY_URL
    path.write_text("{not json", encoding="utf-8")
    assert connection.load(path) == DEFAULT_COMFY_URL
    connection.save(path, "http://gpu-box:8188")
    assert connection.load(path) == "http://gpu-box:8188"


class _FakeComfy:
    """A ComfyUI without the built-in workflow's models: someone using only their own graphs."""

    reachable = True

    def __init__(self, base_url: str, timeout: float = 0, api_key: str = "") -> None:
        self.base_url = base_url

    def ping(self) -> None:
        if not self.reachable:
            raise httpx.ConnectError(f"cannot reach {self.base_url}")

    def find_models(self) -> object:
        raise ComfyError("models not on the ComfyUI server: qwen_image_edit_2511_fp8mixed")


@pytest.mark.parametrize("reachable", [True, False])
def test_connect_saves_any_reachable_comfyui(
    reachable: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(_FakeComfy, "reachable", reachable)
    monkeypatch.setattr(cli, "Comfy", _FakeComfy)

    result = CliRunner().invoke(cli.cli, ["connect", "10.0.0.7:8188"])

    saved = tmp_path / "xp-photocraft" / "connection.json"
    assert result.exit_code == (0 if reachable else 1)
    assert saved.is_file() is reachable  # saved even without the built-in models
    assert "10.0.0.7" not in result.stderr  # the status line shown on screen hides the address


def _status_error() -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "http://10.0.0.7:8188/upload/image")
    try:
        httpx.Response(500, request=request).raise_for_status()
    except httpx.HTTPStatusError as e:
        return e
    raise AssertionError("a 500 is an error")


class _FailingComfy(_FakeComfy):
    """A ComfyUI that fails over HTTP mid-run (the tunnel died, the server crashed)."""

    error: Exception = httpx.ConnectError("[WinError 10061] No connection could be made")

    def find_models(self) -> object:
        raise self.error


@pytest.mark.parametrize(
    ("error", "shown"),
    [
        (httpx.ConnectError("[WinError 10061] No connection could be made"), "server unreachable"),
        (httpx.ReadTimeout("timed out"), "server unreachable"),
        (_status_error(), "answered HTTP 500"),
    ],
)
def test_fill_says_what_comfyui_did_without_its_address(
    error: Exception, shown: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(_FailingComfy, "error", error)
    monkeypatch.setattr(cli, "Comfy", _FailingComfy)

    result = CliRunner().invoke(cli.cli, ["fill", "--prompt", "a plate"])

    assert result.exit_code == 1
    # The last line is PhotoCraft's status bar: one line, in words, no URL (httpx puts it in some).
    assert result.stderr.strip().splitlines()[-1] == f"xp-photocraft fill: ComfyUI {shown}"
    assert "10.0.0.7" not in result.stdout + result.stderr
