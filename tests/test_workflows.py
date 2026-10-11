"""Workflows: the registry, the engine each action picks, and the external runner contract."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner
from PIL import Image

from xp_photocraft import cli, registry
from xp_photocraft.engines import ComfyGraph, EngineError, Runner, generation_megapixels

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
    added = {
        "banana": {"label": "Banana", "command": ["python", "run.py"]},
        "flux": {"label": "Flux", "graph": "flux_api.json"},
    }
    path.write_text(json.dumps({"workflows": added, "assign": assign}), encoding="utf-8")


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
    path.write_text('{"workflows": {"x": {"label": "X", "comand": ["run"]}}}', encoding="utf-8")
    with pytest.raises(registry.WorkflowsError) as error:
        registry.load(path)
    assert "\n" not in str(error.value) and "workflows.x.comand" in str(error.value)


def test_engine_follows_the_workflow_kind(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(cli, "Comfy", _FakeComfy)
    path = tmp_path / "xp-photocraft" / "workflows.json"
    _write_registry(path, {})
    (path.parent / "flux_api.json").write_text(json.dumps(_GRAPH), encoding="utf-8")
    reg = registry.load(path)

    assert isinstance(cli._engine(reg, "banana", None, tmp_path), Runner)
    assert isinstance(cli._engine(reg, "flux", None, tmp_path), ComfyGraph)
    assert isinstance(cli._engine(reg, "qwen-edit", None, tmp_path), ComfyGraph)


@pytest.mark.parametrize(
    ("entry", "error"),
    [
        ({"label": "X"}, "graph or a command"),
        ({"label": "X", "graph": "a.json", "command": ["run"]}, "graph or a command"),
    ],
)
def test_a_workflow_is_a_graph_or_a_command(tmp_path: Path, entry: dict, error: str) -> None:
    path = tmp_path / "workflows.json"
    path.write_text(json.dumps({"workflows": {"x": entry}}), encoding="utf-8")
    with pytest.raises(registry.WorkflowsError, match=error):
        registry.load(path)


def test_a_ui_workflow_is_refused_with_the_fix(tmp_path: Path) -> None:
    path = tmp_path / "ui.json"
    path.write_text(json.dumps({"nodes": [], "links": []}), encoding="utf-8")
    with pytest.raises(registry.WorkflowsError, match="Export \\(API\\)"):
        registry.load_graph(path)


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
    assert [w["id"] for w in listed["workflows"]] == ["qwen-edit", "banana", "flux"]
    assert "run.py" not in stdout  # commands (private paths) never reach the UI


def test_a_graph_dropped_in_the_folder_is_listed_and_assignable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    data = tmp_path / "xp-photocraft"
    _write_registry(data / "workflows.json", {})
    (data / "workflows").mkdir()
    (data / "workflows" / "Qwen Image 2.1.json").write_text(json.dumps(_GRAPH), encoding="utf-8")
    (data / "workflows" / "flux.json").write_text("{}", encoding="utf-8")  # declared one wins

    CliRunner().invoke(cli.cli, ["assign", "fill", "Qwen Image 2.1"])
    listed = json.loads(CliRunner().invoke(cli.cli, ["workflows"]).stdout)
    saved = json.loads((data / "workflows.json").read_text(encoding="utf-8"))

    assert [w["label"] for w in listed["workflows"]][1:] == ["Banana", "Flux", "Qwen Image 2.1"]
    assert listed["assign"]["fill"] == "Qwen Image 2.1"
    assert set(saved["workflows"]) == {"banana", "flux"}  # the folder stays the folder
    assert listed["folder"] == str(data / "workflows")
    engine = cli._engine(registry.load(data / "workflows.json"), "Qwen Image 2.1", None, tmp_path)
    assert isinstance(engine, ComfyGraph)


def test_the_builtin_file_in_the_folder_is_the_builtin_workflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(cli, "Comfy", _FakeComfy)
    folder = tmp_path / "xp-photocraft" / "workflows"
    folder.mkdir(parents=True)
    graph = json.loads((Path(cli.__file__).with_name("qwen-edit-2511.api.json")).read_text("utf-8"))
    graph["sampler"]["inputs"]["steps"] = 6  # the user's own setting
    (folder / "Qwen Edit 2511 (ComfyUI).json").write_text(json.dumps(graph), encoding="utf-8")

    listed = json.loads(CliRunner().invoke(cli.cli, ["workflows"]).stdout)
    engine = cli._engine(
        registry.load(folder.parent / "workflows.json"), "qwen-edit", None, tmp_path
    )

    assert [w["label"] for w in listed["workflows"]] == ["Qwen Edit 2511 (ComfyUI)"]  # once
    assert listed["assign"] == {"fill": "qwen-edit", "remove": "qwen-edit"}
    assert engine._graph["sampler"]["inputs"]["steps"] == 6  # type: ignore[attr-defined]


def test_graph_carries_its_own_prompt_wording(tmp_path: Path) -> None:
    graph = json.loads(json.dumps(_GRAPH))
    graph["3"]["inputs"]["text"] = "Image 2 is a mask. In its white area: {prompt}."
    comfy = _FakeComfy()

    ComfyGraph(comfy, graph).generate(tmp_path / "r.png", tmp_path / "m.png", "a kite", 1, "fill")  # type: ignore[arg-type]

    assert comfy.graph["3"]["inputs"]["text"] == "Image 2 is a mask. In its white area: a kite."


@pytest.mark.parametrize("size,side", [((312, 242), 512), ((650, 736), 704), ((2000, 1500), 992)])
def test_one_node_can_be_prompt_and_scale(tmp_path: Path, size: tuple[int, int], side: int) -> None:
    # Qwen Image 2.1: the prompt and the generation size live on its text encoder.
    graph = {
        "1": _node("LoadImage", {"image": ""}, "pc:image"),
        "2": _node(
            "TextEncodeQwenImage21", {"prompt": "", "resolution": 1024}, "pc:prompt pc:scale"
        ),
    }
    Image.new("RGB", size).save(tmp_path / "r.png")
    comfy = _FakeComfy()

    ComfyGraph(comfy, graph).generate(tmp_path / "r.png", tmp_path / "m.png", "a kite", 1, "fill")  # type: ignore[arg-type]

    assert comfy.graph["2"]["inputs"] == {"prompt": "a kite", "resolution": side}


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
    def __init__(self, base_url: str = "", timeout: float = 0, api_key: str = "") -> None:
        self.graph: dict[str, Any] = {}
        self.output = "unset"

    def find_models(self) -> dict[str, dict[str, str]]:
        return {"UNETLoader": {"unet_name": "qwen/edit_int8.safetensors"}}

    def resolve_models(self, graph: dict[str, Any]) -> None:
        for node in graph.values():
            node["inputs"].update(self.find_models().get(node["class_type"], {}))

    def upload(self, file: Path) -> str:
        return f"up_{file.name}"

    def run(self, graph: dict[str, Any], output_node: str = "") -> bytes:
        self.graph, self.output = graph, output_node
        return b"png"


def _node(class_type: str, inputs: dict[str, Any], title: str) -> dict[str, Any]:
    return {"class_type": class_type, "inputs": inputs, "_meta": {"title": title}}


# A user graph: CLIPTextEncode ("text"), KSampler-style "noise_seed", a preview and a save.
_GRAPH = {
    "1": _node("LoadImage", {"image": "x.png"}, "pc:image"),
    "2": _node("LoadImage", {"image": "y.png"}, "pc:mask"),
    "3": _node("CLIPTextEncode", {"text": "", "clip": ["9", 0]}, "pc:prompt"),
    "4": _node("SamplerCustomAdvanced", {"noise_seed": 0}, "pc:seed"),
    "5": _node("PreviewImage", {"images": ["6", 0]}, "Preview Image"),
    "6": _node("SaveImage", {"images": ["7", 0]}, "pc:output"),
}


def test_graph_engine_fills_the_tagged_nodes(tmp_path: Path) -> None:
    comfy = _FakeComfy()
    engine = ComfyGraph(comfy, _GRAPH, "Image 2 is a mask. {prompt}")  # type: ignore[arg-type]

    engine.generate(tmp_path / "region.png", tmp_path / "mask.png", "a {red} kite", 7, "fill")

    inputs = {key: node["inputs"] for key, node in comfy.graph.items()}
    assert (inputs["1"]["image"], inputs["2"]["image"]) == ("up_region.png", "up_mask.png")
    assert inputs["3"]["text"] == "Image 2 is a mask. a {red} kite"  # braces in a prompt are text
    assert inputs["4"]["noise_seed"] == 7 and comfy.output == "6"
    assert _GRAPH["3"]["inputs"]["text"] == ""  # the loaded graph is left untouched


def test_builtin_graph_runs_on_the_server_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "Comfy", _FakeComfy)
    engine = cli._engine(registry.Registry(), "qwen-edit", None, tmp_path)
    Image.new("RGB", (312, 242)).save(tmp_path / "r.png")  # a plate with its margin

    engine.generate(tmp_path / "r.png", tmp_path / "m.png", "a plate", 7, "fill")

    graph = engine._comfy.graph  # type: ignore[attr-defined]
    assert graph["unet"]["inputs"]["unet_name"] == "qwen/edit_int8.safetensors"
    assert graph["pos"]["inputs"]["prompt"] == "a plate"
    assert graph["sampler"]["inputs"]["seed"] == 7
    assert graph["scale"]["inputs"]["megapixels"] == 0.25  # the floor, not a full megapixel


@pytest.mark.parametrize(
    "size,expected", [((312, 242), 0.25), ((900, 800), 0.72), ((2000, 1500), 1.0)]
)
def test_generation_size_is_the_region_size_clamped(
    tmp_path: Path, size: tuple[int, int], expected: float
) -> None:
    Image.new("RGB", size).save(tmp_path / "r.png")
    assert generation_megapixels(tmp_path / "r.png") == expected


def test_an_untagged_graph_is_refused_before_anything_runs() -> None:
    with pytest.raises(EngineError, match="pc:image or pc:prompt"):
        ComfyGraph(_FakeComfy(), {"1": _node("SaveImage", {}, "Save")})  # type: ignore[arg-type]


def test_data_dir_is_beside_a_portable_executable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exe = tmp_path / "release" / "xp-photocraft.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"")
    monkeypatch.setattr(sys, "executable", str(exe))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    assert cli._data_dir() == tmp_path / "appdata" / "xp-photocraft"  # no marker: the user's folder
    (exe.parent / "portable.txt").write_text("")
    assert cli._data_dir() == exe.parent / "data"


def test_api_key_comes_from_the_environment_or_the_dotenv_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv(cli.API_KEY_ENV, raising=False)
    assert cli._api_key() == ""
    data = tmp_path / "xp-photocraft"
    data.mkdir()
    (data / ".env").write_text(
        "# comfy.org\nXP_PHOTOCRAFT_COMFY_API_KEY = 'file-key'\nOTHER=1\n", encoding="utf-8"
    )
    assert cli._api_key() == "file-key"
    monkeypatch.setenv(cli.API_KEY_ENV, "env-key")
    assert cli._api_key() == "env-key"  # the environment wins
