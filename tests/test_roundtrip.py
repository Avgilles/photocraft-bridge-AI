"""The round trip against a fake PhotoCraft and a fake ComfyUI: no socket, no GPU."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from xp_photocraft import roundtrip
from xp_photocraft.roundtrip import Rect


class FakeControl:
    """Records every command; answers the two inspections the round trip asks for."""

    def __init__(self, work: Path, has_selection: bool = True) -> None:
        self.work, self.has_selection, self.log = work, has_selection, []  # type: ignore[var-annotated]

    def call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        self.log.append((method, params or {}))
        if method == "app.save":
            Image.new("RGB", (8, 8)).save(self.work / params["path"])  # type: ignore[index]
        return {}

    def cmd(self, command: str, params: dict[str, Any] | None = None) -> Any:
        self.log.append((command, params or {}))
        if command == "session.inspect":
            return {"active": 2}
        if command == "document.inspect":
            return {
                "hasSelection": self.has_selection,
                "selectionBounds": [150, 1565, 160, 75],
                "width": 1248,
                "height": 1893,
            }
        return {}


class FakeComfy:
    def __init__(self, fail: bool = False) -> None:
        self.fail, self.graph = fail, None

    def find_models(self, wanted: object) -> object:
        return wanted

    def upload(self, file: Path) -> str:
        return file.name

    def run(self, graph: dict[str, object]) -> bytes:
        if self.fail:
            raise RuntimeError("server down")
        self.graph = graph  # type: ignore[assignment]
        out = io.BytesIO()
        Image.new("RGB", (1176, 892), (255, 0, 0)).save(out, "PNG")
        return out.getvalue()


def test_fill_selection_places_a_masked_layer_at_the_crop_offset(tmp_path: Path) -> None:
    pc, comfy = FakeControl(tmp_path), FakeComfy()
    crop = roundtrip.fill_selection(pc, comfy, "a plate", 7, tmp_path, "Generative Fill")  # type: ignore[arg-type]

    assert crop == Rect(54, 1469, 352, 267)
    placed = Image.open(tmp_path / "placed.png")
    assert placed.size == (1248, 1893)
    assert (
        placed.getpixel((crop.x, crop.y))[3] == 255
        and placed.getpixel((crop.x - 1, crop.y))[3] == 0
    )
    assert comfy.graph["pos"]["inputs"]["prompt"] == "a plate"  # type: ignore[index]
    commands = [c for c, _ in pc.log]
    tail = commands[commands.index("edit.pasteSpecial.pasteInPlace") :]
    assert tail[:4] == [
        "edit.pasteSpecial.pasteInPlace",
        "layer.setProps",
        "select.loadSelection",
        "layer.layerMask.revealSelection",
    ]
    assert commands[-1] == "channel.delete"
    assert ("document.activate", {"document": 2}) in pc.log


def test_fill_selection_cleans_up_the_channel_when_comfy_fails(tmp_path: Path) -> None:
    pc = FakeControl(tmp_path)
    with pytest.raises(RuntimeError, match="server down"):
        roundtrip.fill_selection(pc, FakeComfy(fail=True), "x", 1, tmp_path, "L")  # type: ignore[arg-type]
    assert pc.log[-1][0] == "channel.delete"
    assert "edit.pasteSpecial.pasteInPlace" not in [c for c, _ in pc.log]


def test_fill_selection_without_selection_touches_nothing(tmp_path: Path) -> None:
    pc = FakeControl(tmp_path, has_selection=False)
    with pytest.raises(roundtrip.NoSelectionError):
        roundtrip.fill_selection(pc, FakeComfy(), "x", 1, tmp_path, "L")  # type: ignore[arg-type]
    assert [c for c, _ in pc.log] == ["session.inspect", "document.inspect"]


@pytest.mark.parametrize(
    ("bounds", "expected"),
    [
        (Rect(150, 1565, 160, 75), Rect(54, 1469, 352, 267)),
        (Rect(0, 0, 10, 10), Rect(0, 0, 106, 106)),
        (Rect(1240, 1880, 8, 13), Rect(1144, 1784, 104, 109)),
    ],
)
def test_context_rect_is_clamped_to_the_document(bounds: Rect, expected: Rect) -> None:
    assert roundtrip.context_rect(bounds, (1248, 1893), 96) == expected
