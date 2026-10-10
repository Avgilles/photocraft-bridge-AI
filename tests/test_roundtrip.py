"""The round trip against a fake PhotoCraft and a fake engine: no socket, no GPU."""

from __future__ import annotations

import io
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from xp_photocraft import roundtrip
from xp_photocraft.control import ControlError
from xp_photocraft.placeholder import PlacementError
from xp_photocraft.roundtrip import Rect


class FakeControl:
    """A tiny PhotoCraft: documents with layers (top first) and a selection flag."""

    def __init__(self, work: Path, has_selection: bool = True) -> None:
        self.work, self.log = work, []  # type: ignore[var-annotated]
        self.docs: list[dict[str, Any]] = [
            {"name": "poster.png", "layers": [2], "active": 2, "selection": has_selection}
        ]
        self.active, self.next_id = 0, 10

    @property
    def doc(self) -> dict[str, Any]:
        return self.docs[self.active]

    def call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        p = params or {}
        self.log.append((method, p))
        if method == "app.save":
            Image.new("RGB", (8, 8)).save(self.work / p["path"])
        if method == "app.open":
            self._open(p["path"])
        return {}

    def cmd(self, command: str, params: dict[str, Any] | None = None) -> Any:
        p = params or {}
        self.log.append((command, p))
        doc = self.doc
        if command == "session.inspect":
            names = [
                {"index": i, "name": d["name"], "path": d.get("path")}
                for i, d in enumerate(self.docs)
            ]
            return {"active": self.active, "documents": names}
        if command == "document.inspect":
            return {
                "name": doc["name"],
                "hasSelection": doc["selection"],
                "selectionBounds": [150, 1565, 160, 75],
                "width": 1248,
                "height": 1893,
                "layers": [{"id": i} for i in doc["layers"]],
                "activeLayer": doc["active"],
                "revision": doc.get("revision", 0),
            }
        # Like PhotoCraft: edits, layer and selection changes move the revision; switching does not.
        if command.split(".")[0] in ("layer", "select", "edit", "channel"):
            doc["revision"] = doc.get("revision", 0) + 1
        if command == "image.duplicate":
            self._open(p["name"], selection=doc["selection"])
        elif command == "file.close":
            self.docs.pop(self.active)
            self.active = 0
        elif command == "document.activate":
            self.active = p["document"]
        elif command in ("layer.new.layer", "edit.pasteSpecial.pasteInPlace"):
            self.next_id += 1
            doc["layers"].insert(doc["layers"].index(doc["active"]), self.next_id)
            doc["active"] = self.next_id
        elif command in ("layer.select", "layer.delete"):
            if p["layer"] not in doc["layers"]:
                raise ControlError(f"{command}: no layer {p['layer']}")
            if command == "layer.delete":
                doc["layers"].remove(p["layer"])
            else:
                doc["active"] = p["layer"]
        elif command in ("select.loadSelection", "select.all"):
            doc["selection"] = True
        elif command == "select.deselect":
            doc["selection"] = False
        return {}

    def _open(self, name: str, selection: bool = False) -> None:
        self.next_id += 1
        self.docs.append(
            {"name": name, "layers": [self.next_id], "active": self.next_id, "selection": selection}
        )
        self.active = len(self.docs) - 1


class FakeEngine:
    """Returns a red PNG; ``meanwhile`` plays the artist while it "generates"."""

    def __init__(self, meanwhile: Callable[[], None] = lambda: None, fail: bool = False) -> None:
        self.meanwhile, self.fail, self.request = meanwhile, fail, ()  # type: ignore[var-annotated]

    def generate(self, region: Path, mask: Path, prompt: str, seed: int, mode: str) -> bytes:
        self.meanwhile()
        if self.fail:
            raise RuntimeError("server down")
        self.request = (region.name, mask.name, prompt, seed, mode)
        out = io.BytesIO()
        Image.new("RGB", (1176, 892), (255, 0, 0)).save(out, "PNG")
        return out.getvalue()


def _poster(pc: FakeControl) -> dict[str, Any]:
    return next(d for d in pc.docs if d["name"] == "poster.png")


def test_fill_replaces_the_placeholder_and_hands_the_artist_layer_back(tmp_path: Path) -> None:
    pc, engine = FakeControl(tmp_path), FakeEngine()

    crop = roundtrip.fill_selection(pc, engine, "a plate", 7, tmp_path, "Generative Fill")  # type: ignore[arg-type]

    assert crop == Rect(54, 1469, 352, 267)
    placed = Image.open(tmp_path / "placed.png")
    assert placed.size == (1248, 1893)
    assert placed.getpixel((crop.x, crop.y))[3] == 255
    assert placed.getpixel((crop.x - 1, crop.y))[3] == 0
    assert engine.request == ("region.png", "mask.png", "a plate", 7, "fill")
    card = Image.open(tmp_path / "placeholder.png")  # over the selection bounds, not the margin
    assert card.getpixel((150, 1565))[3] > 0 and card.getpixel((149, 1565))[3] == 0
    holder = next(
        p["layer"] for c, p in pc.log if c == "layer.setProps" and "generating" in p.get("name", "")
    )
    mask = ("select.loadSelection", {"channel": "mask", "layer": holder})
    poster = _poster(pc)
    assert mask in pc.log and holder not in poster["layers"]
    # The result sits above the artist's layer and stays selected, as after Photoshop's fill.
    assert len(poster["layers"]) == 2 and poster["active"] == poster["layers"][0]
    assert poster["layers"][1] == 2 and poster["selection"]
    assert [d["name"] for d in pc.docs] == ["poster.png"]


def test_the_artist_can_switch_documents_while_it_generates(tmp_path: Path) -> None:
    pc = FakeControl(tmp_path)

    def artist() -> None:
        pc._open("sketch.png")
        pc.doc["selection"] = False

    roundtrip.fill_selection(pc, FakeEngine(artist), "x", 1, tmp_path, "L")  # type: ignore[arg-type]

    assert pc.doc["name"] == "sketch.png"  # back where the artist was
    assert len(_poster(pc)["layers"]) == 2  # result in, placeholder out


def test_an_artist_on_another_layer_gets_it_back(tmp_path: Path) -> None:
    pc = FakeControl(tmp_path)

    painted: list[int] = []

    def artist() -> None:
        pc.cmd("layer.new.layer")
        painted.append(pc.doc["active"])
        pc.doc["selection"] = False

    roundtrip.fill_selection(pc, FakeEngine(artist), "x", 1, tmp_path, "L")  # type: ignore[arg-type]

    poster = _poster(pc)
    assert len(poster["layers"]) == 3 and not poster["selection"]
    assert poster["active"] == painted[0]


def test_an_artist_painting_on_their_layer_keeps_it(tmp_path: Path) -> None:
    pc = FakeControl(tmp_path)

    roundtrip.fill_selection(
        pc, FakeEngine(lambda: pc.cmd("edit.fill", {"contents": "white"})), "x", 1, tmp_path, "L"
    )  # type: ignore[arg-type]

    poster = _poster(pc)
    assert poster["active"] == 2 and poster["layers"][1] == 2  # result above, their layer active


def test_deleting_the_placeholder_cancels_the_result(tmp_path: Path) -> None:
    pc = FakeControl(tmp_path)

    def artist() -> None:
        pc.doc["layers"].remove(pc.doc["layers"][0])

    with pytest.raises(PlacementError, match="placeholder deleted"):
        roundtrip.fill_selection(pc, FakeEngine(artist), "x", 1, tmp_path, "L")  # type: ignore[arg-type]
    assert [c for c, _ in pc.log].count("edit.pasteSpecial.pasteInPlace") == 1  # the card only
    assert _poster(pc)["layers"] == [2]


def test_two_documents_of_one_name_each_keep_their_own(tmp_path: Path) -> None:
    pc = FakeControl(tmp_path)  # the same file opened twice: the generation runs in the second
    pc.docs.insert(0, {"name": "poster.png", "layers": [5], "active": 5, "selection": False})
    pc.active = 1

    roundtrip.fill_selection(pc, FakeEngine(), "x", 1, tmp_path, "L")  # type: ignore[arg-type]

    assert pc.docs[0]["layers"] == [5]  # untouched
    assert len(pc.docs[1]["layers"]) == 2  # result in, placeholder out
    assert pc.active == 1


def test_a_cancelled_result_leaves_the_artist_where_they_are(tmp_path: Path) -> None:
    pc = FakeControl(tmp_path)

    def artist() -> None:
        pc.doc["layers"].remove(pc.doc["layers"][0])  # deletes the placeholder, then moves on
        pc._open("sketch.png")

    with pytest.raises(PlacementError, match="placeholder deleted"):
        roundtrip.fill_selection(pc, FakeEngine(artist), "x", 1, tmp_path, "L")  # type: ignore[arg-type]
    assert pc.doc["name"] == "sketch.png"


def test_a_failed_generation_removes_the_placeholder(tmp_path: Path) -> None:
    pc = FakeControl(tmp_path)
    with pytest.raises(RuntimeError, match="server down"):
        roundtrip.fill_selection(pc, FakeEngine(fail=True), "x", 1, tmp_path, "L")  # type: ignore[arg-type]
    assert _poster(pc)["layers"] == [2]
    assert [c for c, _ in pc.log].count("edit.pasteSpecial.pasteInPlace") == 1  # the card only


def test_remove_shows_the_model_a_content_aware_fill_of_the_duplicate(tmp_path: Path) -> None:
    pc = FakeControl(tmp_path)
    roundtrip.remove_selection(pc, FakeEngine(), 1, tmp_path, "Remove (AI)")  # type: ignore[arg-type]
    commands = [c for c, _ in pc.log]
    caf = commands.index("edit.contentAwareFill")
    assert commands[caf - 1] == "image.duplicate" and commands.count("edit.contentAwareFill") == 1


def test_fill_selection_without_selection_touches_nothing(tmp_path: Path) -> None:
    pc = FakeControl(tmp_path, has_selection=False)
    with pytest.raises(roundtrip.NoSelectionError):
        roundtrip.fill_selection(pc, FakeEngine(), "x", 1, tmp_path, "L")  # type: ignore[arg-type]
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


def test_each_result_is_kept_in_xp_work_next_to_the_document(tmp_path: Path) -> None:
    project = tmp_path / "projects" / "poster"
    project.mkdir(parents=True)
    pc = FakeControl(tmp_path)
    pc.docs[0]["path"] = str(project / "daylight_suv.psd")

    roundtrip.fill_selection(
        pc, FakeEngine(), "a plate", 7, tmp_path, "Generative Fill", "qwen-edit"
    )  # type: ignore[arg-type]

    kept = sorted((project / "xp-work" / "daylight_suv").iterdir())
    assert [k.suffix for k in kept] == [".json", ".png"]
    record = json.loads(kept[0].read_text(encoding="utf-8"))
    assert (record["prompt"], record["workflow"], record["seed"]) == ("a plate", "qwen-edit", 7)
    assert kept[1].name.endswith("_fill_7.png")


def test_a_never_saved_document_keeps_nothing_beside_it(tmp_path: Path) -> None:
    assert roundtrip.project_work_dir("", tmp_path) is None
    assert (
        roundtrip.project_work_dir("in/opened.png", tmp_path)
        == tmp_path / "in" / "xp-work" / "opened"
    )
