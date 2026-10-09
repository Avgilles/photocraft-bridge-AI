"""Workflows: the registry, the engine each action picks, and the external runner contract."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from xp_photocraft import cli, registry
from xp_photocraft.engines import EngineError, QwenComfy, Runner

# A runner@1 command: writes a 4x4 PNG beside the request, or fails like a real one would.
_FAKE_RUNNER = """
import json, sys
from pathlib import Path
from PIL import Image
request = json.loads(Path(sys.argv[-1]).read_text(encoding="utf-8"))
if request["prompt"] == "fail":
    print("partner API refused the prompt", file=sys.stderr)
    sys.exit(3)
Image.new("RGB", (4, 4)).save(Path(sys.argv[-1]).with_name("out.png"))
print(json.dumps({"image": "out.png"}))
"""


def _write_registry(path: Path, assign: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    workflows = {"banana": {"label": "Banana", "command": ["python", "run.py"]}}
    path.write_text(json.dumps({"workflows": workflows, "assign": assign}), encoding="utf-8")


@pytest.mark.parametrize(
    ("assign", "override", "expected"),
    [
        ({}, "", "qwen-edit"),
        ({"fill": "banana"}, "", "banana"),
        ({"fill": "banana"}, "qwen-edit", "qwen-edit"),
    ],
)
def test_pick_prefers_override_then_assignment_then_builtin(
    tmp_path: Path, assign: dict[str, str], override: str, expected: str
) -> None:
    path = tmp_path / "workflows.json"
    _write_registry(path, assign)
    assert registry.pick(registry.load(path), "fill", override) == expected


def test_pick_rejects_an_unknown_workflow(tmp_path: Path) -> None:
    path = tmp_path / "workflows.json"
    _write_registry(path, {"fill": "gone"})
    with pytest.raises(registry.WorkflowsError, match="unknown workflow 'gone'"):
        registry.pick(registry.load(path), "fill", "")


def test_load_reports_a_broken_file_on_one_line(tmp_path: Path) -> None:
    path = tmp_path / "workflows.json"
    path.write_text('{"workflows": {"x": {"label": "X", "command": []}}}', encoding="utf-8")
    with pytest.raises(registry.WorkflowsError) as error:
        registry.load(path)
    assert "\n" not in str(error.value) and "workflows.x.command" in str(error.value)


def test_engine_is_a_runner_for_a_declared_workflow(tmp_path: Path) -> None:
    path = tmp_path / "workflows.json"
    _write_registry(path, {})
    reg = registry.load(path)
    assert isinstance(cli._engine(reg, "banana", None, tmp_path), Runner)
    assert isinstance(cli._engine(reg, "qwen-edit", "http://127.0.0.1:1", tmp_path), QwenComfy)


def test_cli_assign_saves_and_lists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    path = tmp_path / "xp-photocraft" / "workflows.json"
    _write_registry(path, {})

    assigned = CliRunner().invoke(cli.cli, ["assign", "fill", "banana"])
    refused = CliRunner().invoke(cli.cli, ["assign", "remove", "gone"])
    stdout = CliRunner().invoke(cli.cli, ["workflows"]).stdout
    listed = json.loads(stdout)

    assert (assigned.exit_code, refused.exit_code) == (0, 1)
    assert listed["assign"] == {"fill": "banana", "remove": "qwen-edit"}
    assert [w["id"] for w in listed["workflows"]] == ["qwen-edit", "banana"]
    assert "run.py" not in stdout  # commands (private paths) never reach the UI


def _runner(tmp_path: Path) -> Runner:
    script = tmp_path / "fake_runner.py"
    script.write_text(_FAKE_RUNNER, encoding="utf-8")
    return Runner([sys.executable, str(script)], tmp_path, timeout=60)


def test_runner_writes_the_request_and_returns_the_printed_png(tmp_path: Path) -> None:
    (tmp_path / "region.png").write_bytes(b"")
    (tmp_path / "mask.png").write_bytes(b"")

    png = _runner(tmp_path).generate(
        tmp_path / "region.png", tmp_path / "mask.png", "a dragon", 7, "fill"
    )

    request = json.loads((tmp_path / "request.json").read_text(encoding="utf-8"))
    assert png.startswith(b"\x89PNG")
    assert request == {
        "contract": "xp-photocraft/runner@1",
        "image": str((tmp_path / "region.png").resolve()),
        "mask": str((tmp_path / "mask.png").resolve()),
        "prompt": "a dragon",
        "seed": 7,
        "mode": "fill",
    }


def test_runner_failure_surfaces_the_last_stderr_line(tmp_path: Path) -> None:
    with pytest.raises(EngineError, match="^partner API refused the prompt$"):
        _runner(tmp_path).generate(tmp_path / "r.png", tmp_path / "m.png", "fail", 1, "fill")


class _FakeComfy:
    graph: dict[str, Any] = {}

    def find_models(self, wanted: object) -> object:
        return wanted

    def upload(self, file: Path) -> str:
        return file.name

    def run(self, graph: dict[str, Any]) -> bytes:
        self.graph = graph
        return b"png"


def test_qwen_engine_sends_the_prompt_and_seed_in_the_graph(tmp_path: Path) -> None:
    comfy = _FakeComfy()
    QwenComfy(comfy).generate(tmp_path / "r.png", tmp_path / "m.png", "a plate", 7, "fill")  # type: ignore[arg-type]
    assert comfy.graph["pos"]["inputs"]["prompt"] == "a plate"
    assert comfy.graph["sampler"]["inputs"]["seed"] == 7
