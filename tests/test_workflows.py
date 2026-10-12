"""Workflows: the registry, the engine each action picks, and the external runner contract."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner
from PIL import Image

from xp_photocraft import cli, registry, roundtrip
from xp_photocraft.engines import ComfyGraph, Engine, EngineError, Runner, generation_megapixels

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


def test_the_package_version_is_pyproject_s() -> None:
    import tomllib

    import xp_photocraft

    pyproject = Path(__file__).parents[1] / "pyproject.toml"
    assert (
        tomllib.loads(pyproject.read_text("utf-8"))["project"]["version"]
        == xp_photocraft.__version__
    )


def test_the_shipped_builtin_file_is_the_packaged_graph() -> None:
    # Two copies: the package's (source installs) and the release catalog's. One graph.
    packaged = Path(cli.__file__).with_name("qwen-edit-2511.api.json")
    shipped = (
        Path(__file__).parents[1]
        / "examples/workflows/Local/Qwen Edit 2511 (ComfyUI)/workflow.json"
    )
    assert json.loads(shipped.read_text("utf-8")) == json.loads(packaged.read_text("utf-8"))


def _generate(engine: Engine, tmp_path: Path, prompt: str, seed: int = 1) -> bytes:
    """One result of ``engine``, as the round trip asks for it."""
    images: list[bytes] = []
    engine.generate(
        tmp_path / "r.png",
        tmp_path / "m.png",
        prompt,
        [seed],
        "fill",
        lambda _k, png: images.append(png),
    )
    return images[0]


def test_graph_carries_its_own_prompt_wording(tmp_path: Path) -> None:
    graph = json.loads(json.dumps(_GRAPH))
    graph["3"]["inputs"]["text"] = "Image 2 is a mask. In its white area: {prompt}."
    comfy = _FakeComfy()

    _generate(ComfyGraph(comfy, graph), tmp_path, "a kite")  # type: ignore[arg-type]

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

    _generate(ComfyGraph(comfy, graph), tmp_path, "a kite")  # type: ignore[arg-type]

    assert comfy.graph["2"]["inputs"] == {"prompt": "a kite", "resolution": side}


def _runner(tmp_path: Path) -> Runner:
    script = tmp_path / "fake_runner.py"
    script.write_text(_FAKE_RUNNER, encoding="utf-8")
    return Runner([sys.executable, str(script)], tmp_path, timeout=60)


def test_runner_writes_the_request_and_returns_the_printed_png(tmp_path: Path) -> None:
    (tmp_path / "r.png").write_bytes(b"")
    (tmp_path / "m.png").write_bytes(b"")

    png = _generate(_runner(tmp_path), tmp_path, "a dragon", seed=7)

    request = json.loads((tmp_path / "request.json").read_text(encoding="utf-8"))
    assert png.startswith(b"\x89PNG")
    assert request == {
        "contract": "xp-photocraft/runner@1",
        "image": str((tmp_path / "r.png").resolve()),
        "mask": str((tmp_path / "m.png").resolve()),
        "prompt": "a dragon",
        "seed": 7,
        "mode": "fill",
    }


def test_runner_failure_surfaces_the_last_stderr_line(tmp_path: Path) -> None:
    with pytest.raises(EngineError, match="^partner API refused the prompt$"):
        _generate(_runner(tmp_path), tmp_path, "fail")


def test_runner_runs_the_variations_in_turn_and_stops_once_cancelled(tmp_path: Path) -> None:
    from xp_photocraft.comfy import Cancelled

    came: list[int] = []
    wanted = iter([True, True, False])
    with pytest.raises(Cancelled):
        _runner(tmp_path).generate(
            tmp_path / "r.png",
            tmp_path / "m.png",
            "a dragon",
            [1, 2, 3],
            "fill",
            lambda k, _png: came.append(k),
            lambda: next(wanted),
        )
    assert came == [0, 1]


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

    def run_all(
        self, graphs: list[dict[str, Any]], output_node: str, on_image: Any, still_wanted: Any
    ) -> None:
        self.graphs, self.output = graphs, output_node
        self.graph = graphs[-1]
        for k in range(len(graphs)):
            on_image(k, b"png")


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

    _generate(engine, tmp_path, "a {red} kite", seed=7)

    inputs = {key: node["inputs"] for key, node in comfy.graph.items()}
    assert (inputs["1"]["image"], inputs["2"]["image"]) == ("up_r.png", "up_m.png")
    assert inputs["3"]["text"] == "Image 2 is a mask. a {red} kite"  # braces in a prompt are text
    assert inputs["4"]["noise_seed"] == 7 and comfy.output == "6"
    assert _GRAPH["3"]["inputs"]["text"] == ""  # the loaded graph is left untouched


def test_builtin_graph_runs_on_the_server_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "Comfy", _FakeComfy)
    engine = cli._engine(registry.Registry(), "qwen-edit", None, tmp_path)
    Image.new("RGB", (312, 242)).save(tmp_path / "r.png")  # a plate with its margin

    _generate(engine, tmp_path, "a plate", seed=7)

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


def _catalog_tree(data: Path) -> Path:
    """A 0.2 catalog: two categories, a folder without one, a 0.1 loose export."""
    root = data / "workflows"
    for folder in ("Local/Flux Fill", "Cloud/Nano Banana", "Sketchy"):
        (root / folder).mkdir(parents=True)
        (root / folder / "workflow.json").write_text(json.dumps(_GRAPH), encoding="utf-8")
    (root / "Cloud/Nano Banana/app.json").write_text("{}", encoding="utf-8")
    (root / "Old export.json").write_text(json.dumps(_GRAPH), encoding="utf-8")
    (root / "Flux Fill.json").write_text("{}", encoding="utf-8")  # a 0.1 copy: the folder wins
    return root


def test_each_folder_is_a_workflow_named_after_it_its_parent_a_category(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(cli, "Comfy", _FakeComfy)
    data = tmp_path / "xp-photocraft"
    _catalog_tree(data)

    listed = json.loads(CliRunner().invoke(cli.cli, ["workflows"]).stdout)
    reg = registry.load(data / "workflows.json")

    ids = ["qwen-edit", "Flux Fill", "Nano Banana", "Old export", "Sketchy"]
    assert [w["id"] for w in listed["workflows"]] == ids
    categories = {w["id"]: w["category"] for w in listed["workflows"]}
    assert (categories["Flux Fill"], categories["Nano Banana"], categories["Sketchy"]) == (
        "Local",
        "Cloud",
        "",
    )
    assert reg.workflows["Flux Fill"].graph == "workflows/Local/Flux Fill/workflow.json"
    assert reg.workflows["Nano Banana"].app == "workflows/Cloud/Nano Banana/app.json"
    assert isinstance(cli._engine(reg, "Nano Banana", None, tmp_path), ComfyGraph)


def test_the_builtin_folder_is_the_builtin_workflow_in_its_category(tmp_path: Path) -> None:
    folder = tmp_path / "workflows" / "Local" / "Qwen Edit 2511 (ComfyUI)"
    folder.mkdir(parents=True)
    (folder / "workflow.json").write_text(json.dumps(_GRAPH), encoding="utf-8")

    reg = registry.load(tmp_path / "workflows.json")

    assert list(registry.labels(reg)) == ["qwen-edit"]  # one entry, not two
    assert reg.workflows["qwen-edit"].category == "Local"


def test_favorites_and_recent_ones_are_kept_and_listed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    data = tmp_path / "xp-photocraft"
    _catalog_tree(data)
    path = data / "workflows.json"

    starred = CliRunner().invoke(cli.cli, ["favorite", "Sketchy"])
    CliRunner().invoke(cli.cli, ["favorite", "Flux Fill"])
    CliRunner().invoke(cli.cli, ["favorite", "Sketchy", "--off"])
    refused = CliRunner().invoke(cli.cli, ["favorite", "gone"])
    for used in ("Sketchy", "qwen-edit", "Old export", "Nano Banana", "Sketchy", "Flux Fill"):
        registry.remember(path, used)
    registry.remember(path, "gone")  # since removed from the catalog
    listed = json.loads(CliRunner().invoke(cli.cli, ["workflows"]).stdout)

    assert (starred.exit_code, refused.exit_code) == (0, 1)
    assert listed["favorites"] == ["Flux Fill"]
    # Five kept, most recent first (qwen-edit is the sixth); "gone" is not offered.
    assert listed["recent"] == ["Flux Fill", "Sketchy", "Nano Banana", "Old export"]


class _ServerLacking:
    """A ComfyUI that lacks one model of the graph imported."""

    def __init__(self, base_url: str, timeout: float = 0, api_key: str = "") -> None:
        pass

    def missing(self, graph: dict[str, Any]) -> list[str]:
        return ["UNETLoader: flux.safetensors is not on the ComfyUI server"]


def _export(folder: Path, name: str, graph: dict[str, Any], app: bool = False) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.json").write_text(json.dumps(graph), encoding="utf-8")
    if app:
        (folder / f"{name}.app.json").write_text('{"extra": {}}', encoding="utf-8")
    return folder / f"{name}.json"


def test_import_copies_an_export_and_its_app_into_a_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(cli, "Comfy", _ServerLacking)
    source = _export(tmp_path / "downloads", "Flux Fill", _GRAPH, app=True)

    result = CliRunner().invoke(cli.cli, ["import", str(source), "--category", "Local"])

    folder = tmp_path / "xp-photocraft" / "workflows" / "Local" / "Flux Fill"
    reply = json.loads(result.stdout)
    assert (result.exit_code, reply["id"]) == (0, "Flux Fill")
    assert sorted(p.name for p in folder.iterdir()) == ["app.json", "workflow.json"]
    assert reply["warnings"] == ["UNETLoader: flux.safetensors is not on the ComfyUI server"]


@pytest.mark.parametrize(
    ("graph", "error"),
    [
        ({"nodes": [], "links": []}, "Export (API)"),
        ({"1": _node("SaveImage", {}, "Save")}, "no node titled pc:image or pc:prompt"),
    ],
)
def test_import_refuses_what_cannot_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, graph: dict[str, Any], error: str
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    source = _export(tmp_path / "downloads", "Broken", graph)

    result = CliRunner().invoke(cli.cli, ["import", str(source)])

    assert result.exit_code == 1 and error in json.loads(result.stdout)["error"]
    assert not (tmp_path / "xp-photocraft" / "workflows" / "Broken").exists()


def test_a_name_in_the_catalog_is_replaced_only_once_agreed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(cli, "Comfy", _ServerLacking)
    source = _export(tmp_path / "downloads", "Flux Fill", _GRAPH)
    root = tmp_path / "xp-photocraft" / "workflows"

    CliRunner().invoke(cli.cli, ["import", str(source), "--category", "Local"])
    asked = CliRunner().invoke(cli.cli, ["import", str(source), "--category", "Cloud"])
    replaced = CliRunner().invoke(
        cli.cli, ["import", str(source), "--category", "Cloud", "--replace"]
    )

    assert (asked.exit_code, json.loads(asked.stdout)["exists"]) == (1, True)
    assert replaced.exit_code == 0
    assert not (root / "Local" / "Flux Fill").exists()  # moved, not copied
    assert (root / "Cloud" / "Flux Fill" / "workflow.json").is_file()


def test_a_workflow_folder_imports_whole(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(cli, "Comfy", _ServerLacking)
    shared = tmp_path / "from a friend" / "Kontext Fill"
    shared.mkdir(parents=True)
    (shared / "workflow.json").write_text(json.dumps(_GRAPH), encoding="utf-8")
    (shared / "preview.png").write_bytes(b"png")

    result = CliRunner().invoke(cli.cli, ["import", str(shared)])

    folder = tmp_path / "xp-photocraft" / "workflows" / "Kontext Fill"
    assert result.exit_code == 0
    assert sorted(p.name for p in folder.iterdir()) == ["preview.png", "workflow.json"]


def test_fill_variations_get_one_seed_each_and_land_in_one_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(cli, "Comfy", _FakeComfy)
    monkeypatch.setattr(cli, "Control", lambda port, token: object())
    seen: dict[str, list[int]] = {}

    def fill(
        pc: object, engine: object, prompt: str, seeds: list[int], *rest: object
    ) -> roundtrip.Outcome:
        seen["seeds"] = seeds
        variations = [roundtrip.Variation(50 + k, s) for k, s in enumerate(seeds)]
        return roundtrip.Outcome(roundtrip.Rect(1, 2, 3, 4), "r1", 42, variations)

    monkeypatch.setattr(roundtrip, "fill_selection", fill)

    result = CliRunner().invoke(
        cli.cli, ["fill", "--prompt", "x", "--seed", "10", "--variations", "3"]
    )
    too_many = CliRunner().invoke(cli.cli, ["fill", "--prompt", "x", "--variations", "9"])

    reply = json.loads(result.stdout)
    assert seen["seeds"] == [10, 11, 12]
    assert reply["group"] == 42 and [v["seed"] for v in reply["variations"]] == [10, 11, 12]
    assert result.stderr.strip().splitlines()[-1].startswith("xp-photocraft fill: 3 variations")
    assert too_many.exit_code == 2  # at most 8
    saved = json.loads((tmp_path / "xp-photocraft" / "workflows.json").read_text("utf-8"))
    assert saved["recent"] == ["qwen-edit"]
