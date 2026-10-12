"""The round trip against a fake PhotoCraft and a fake engine: no socket, no GPU."""

from __future__ import annotations

import copy
import io
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from xp_photocraft import placeholder, roundtrip
from xp_photocraft.comfy import Cancelled
from xp_photocraft.control import ControlError
from xp_photocraft.placeholder import Placeholder
from xp_photocraft.roundtrip import Rect, Variation

# Commands that change a document and so record (or join, with a coalesce key) an undo step.
_EDITS = ("layer.", "select.", "edit.", "channel.")


def _layer(layer_id: int, name: str = "Layer") -> dict[str, Any]:
    return {"id": layer_id, "name": name, "visible": True}


def _container(layers: list[dict[str, Any]], layer_id: int) -> list[dict[str, Any]] | None:
    """The list holding ``layer_id``: the document's top level or a group's children."""
    for layer in layers:
        if layer["id"] == layer_id:
            return layers
        inner = _container(layer.get("children", []), layer_id)
        if inner is not None:
            return inner
    return None


def _get(layers: list[dict[str, Any]], layer_id: int) -> dict[str, Any]:
    holder = _container(layers, layer_id)
    assert holder is not None, f"no layer {layer_id}"
    return next(layer for layer in holder if layer["id"] == layer_id)


class FakeControl:
    """A tiny PhotoCraft: documents with a layer tree (top first), a selection flag, History."""

    def __init__(self, work: Path, has_selection: bool = True) -> None:
        self.work, self.log = work, []  # type: ignore[var-annotated]
        self.docs: list[dict[str, Any]] = [self._doc("poster.png", 2, has_selection)]
        self.docs[0]["layers"][0]["name"] = "Background"
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
                {"index": i, "name": d["name"], "path": d.get("path"), "revision": d["revision"]}
                for i, d in enumerate(self.docs)
            ]
            return {"active": self.active, "documents": names}
        if command == "document.inspect":
            shown = self.docs[p["document"]] if "document" in p else doc
            return {
                "name": shown["name"],
                "hasSelection": shown["selection"],
                "selectionBounds": [150, 1565, 160, 75],
                "width": 1248,
                "height": 1893,
                "layers": copy.deepcopy(shown["layers"]),
                "activeLayer": shown["active"],
                "revision": shown["revision"],
            }
        # Like PhotoCraft: edits, layer and selection changes move the revision; switching does not.
        if command.startswith(_EDITS):
            doc["revision"] += 1
            if command != "layer.select":
                self._history(doc, p.get("coalesce"))
        return self._run(doc, command, p)

    def _run(self, doc: dict[str, Any], command: str, p: dict[str, Any]) -> Any:
        if command == "image.duplicate":
            self._open(p["name"], selection=doc["selection"])
        elif command == "file.close":
            self.docs.pop(self.active)
            self.active = 0
        elif command == "document.activate":
            self.active = p["document"]
        elif command in ("layer.new.layer", "edit.pasteSpecial.pasteInPlace", "layer.new.group"):
            return self._insert(doc, command == "layer.new.group", p.get("name", "Layer"))
        elif command == "layer.moveTo":
            moved = self._take(doc, p["layer"])
            _get(doc["layers"], p["target"])["children"].insert(0, moved)
        elif command in ("layer.select", "layer.delete"):
            if _container(doc["layers"], p["layer"]) is None:
                raise ControlError(f"{command}: no layer {p['layer']}")
            if command == "layer.delete":
                self._take(doc, p["layer"])
            else:
                doc["active"] = p["layer"]
        elif command == "layer.setProps":
            target = _get(doc["layers"], p.get("layer", doc["active"]))
            target.update({k: p[k] for k in ("name", "visible") if k in p})
        elif command in ("select.loadSelection", "select.all"):
            doc["selection"] = True
        elif command == "select.deselect":
            doc["selection"] = False
        return {}

    def _insert(self, doc: dict[str, Any], group: bool, name: str) -> dict[str, int]:
        """A new layer (or group) right above the active one, in the same group; it is active."""
        self.next_id += 1
        layer = _layer(self.next_id, name) | ({"kind": "Group", "children": []} if group else {})
        holder = _container(doc["layers"], doc["active"])
        assert holder is not None
        holder.insert(next(i for i, x in enumerate(holder) if x["id"] == doc["active"]), layer)
        doc["active"] = self.next_id
        return {"layer": self.next_id}

    def _take(self, doc: dict[str, Any], layer_id: int) -> dict[str, Any]:
        holder = _container(doc["layers"], layer_id)
        assert holder is not None
        taken = next(layer for layer in holder if layer["id"] == layer_id)
        holder.remove(taken)
        return taken

    def _history(self, doc: dict[str, Any], key: str | None) -> None:
        # PhotoCraft's rule: consecutive edits with one coalesce key share one undo step.
        if key is None or key != doc["coalesce"] or not doc["history"]:
            doc["history"].append(key)
        doc["coalesce"] = key

    def _doc(self, name: str, layer_id: int, selection: bool) -> dict[str, Any]:
        return {
            "name": name,
            "layers": [_layer(layer_id)],
            "active": layer_id,
            "selection": selection,
            "revision": 0,
            "history": [],
            "coalesce": None,
        }

    def _open(self, name: str, selection: bool = False) -> None:
        self.next_id += 1
        self.docs.append(self._doc(name, self.next_id, selection))
        self.active = len(self.docs) - 1


class FakeEngine:
    """Returns red PNGs, ``order`` gives the order they come in; ``meanwhile`` plays the artist
    while it "generates", ``between(k)`` after result ``k``. Like ComfyGraph, it asks
    ``still_wanted`` before each result."""

    def __init__(
        self,
        meanwhile: Callable[[], None] = lambda: None,
        fail: bool = False,
        order: list[int] | None = None,
        between: Callable[[int], None] = lambda k: None,
    ) -> None:
        self.meanwhile, self.fail, self.order, self.between = meanwhile, fail, order, between
        self.request = ()  # type: ignore[var-annotated]

    def generate(
        self,
        region: Path,
        mask: Path,
        prompt: str,
        seeds: list[int],
        mode: str,
        on_image: Callable[[int, bytes], None],
        still_wanted: Callable[[], bool] = lambda: True,
    ) -> None:
        self.request = (region.name, mask.name, prompt, seeds, mode)
        self.meanwhile()
        if self.fail:
            raise RuntimeError("server down")
        for k in self.order or range(len(seeds)):
            if not still_wanted():
                raise Cancelled("withdrawn")
            out = io.BytesIO()
            Image.new("RGB", (1176, 892), (255, 0, 0)).save(out, "PNG")
            on_image(k, out.getvalue())
            self.between(k)


def _poster(pc: FakeControl) -> dict[str, Any]:
    return next(d for d in pc.docs if d["name"] == "poster.png")


def _ids(layers: list[dict[str, Any]]) -> list[int]:
    return [layer["id"] for layer in layers]


def _calls(pc: FakeControl, command: str) -> list[dict[str, Any]]:
    """The params ``command`` was sent with, its undo-step key left out."""
    return [{k: v for k, v in p.items() if k != "coalesce"} for c, p in pc.log if c == command]


def _card(pc: FakeControl) -> int:
    setprops = _calls(pc, "layer.setProps")
    return next(p["layer"] for p in setprops if "generating" in p.get("name", ""))


def _fill(pc: FakeControl, engine: FakeEngine, seeds: list[int], work: Path) -> roundtrip.Outcome:
    return roundtrip.fill_selection(pc, engine, "x", seeds, work, "L")  # type: ignore[arg-type]


def test_fill_replaces_the_placeholder_and_hands_the_artist_layer_back(tmp_path: Path) -> None:
    pc, engine = FakeControl(tmp_path), FakeEngine()

    outcome = roundtrip.fill_selection(pc, engine, "a plate", [7], tmp_path, "Generative Fill")  # type: ignore[arg-type]

    crop, run = outcome.rect, tmp_path / "runs" / outcome.run
    assert crop == Rect(54, 1469, 352, 267)
    placed = Image.open(run / "placed-1.png")
    assert placed.size == (1248, 1893)
    assert placed.getpixel((crop.x, crop.y))[3] == 255
    assert placed.getpixel((crop.x - 1, crop.y))[3] == 0
    assert engine.request == ("region.png", "mask.png", "a plate", [7], "fill")
    card = Image.open(run / "placeholder.png")  # over the selection bounds, not the margin
    assert card.getpixel((150, 1565))[3] > 0 and card.getpixel((149, 1565))[3] == 0
    assert {"channel": "mask", "layer": _card(pc)} in _calls(pc, "select.loadSelection")
    poster = _poster(pc)
    # The result sits above the artist's layer and stays selected, as after Photoshop's fill.
    result = poster["layers"][0]["id"]
    assert _ids(poster["layers"]) == [result, 2] and poster["active"] == result
    assert poster["selection"] and [d["name"] for d in pc.docs] == ["poster.png"]
    assert outcome.group == 0 and outcome.variations == [Variation(result, 7)]


def test_a_run_takes_one_undo_step_per_result(tmp_path: Path) -> None:
    pc = FakeControl(tmp_path)  # History keeps 50 steps: a run must not push the artist's out

    _fill(pc, FakeEngine(), [1], tmp_path)
    single = len(_poster(pc)["history"])
    _fill(pc, FakeEngine(), [1, 2, 3], tmp_path)

    assert single == 2  # the card, the result
    assert len(_poster(pc)["history"]) - single == 4  # the card in its group, then 3 results


def test_variations_land_in_one_masked_group_the_first_shown(tmp_path: Path) -> None:
    pc = FakeControl(tmp_path)
    engine = FakeEngine(order=[2, 0, 1])  # ComfyUI may finish them in any order

    outcome = roundtrip.fill_selection(
        pc, engine, "a plate", [7, 8, 9], tmp_path, "Generative Fill"
    )  # type: ignore[arg-type]

    poster = _poster(pc)
    group = poster["layers"][0]
    assert _ids(poster["layers"]) == [outcome.group, 2] and group["kind"] == "Group"
    assert group["name"] == "Generative Fill ×3 — a plate"
    run = outcome.run
    assert [(c["name"], c["visible"]) for c in group["children"]] == [
        (f"Variation 2 · seed 8 · {run}", False),
        (f"Variation 1 · seed 7 · {run}", False),
        (f"Variation 3 · seed 9 · {run}", True),  # the first to come is the one shown
    ]
    assert {"layer": outcome.group} in _calls(pc, "layer.layerMask.revealSelection")
    assert poster["active"] == outcome.group  # PhotoCraft XP shows its picker
    assert [v.seed for v in outcome.variations] == [9, 7, 8]


def test_the_group_says_how_many_came_while_it_generates(tmp_path: Path) -> None:
    pc = FakeControl(tmp_path)
    names: list[str] = []

    def look(_k: int) -> None:
        names.append(_poster(pc)["layers"][0]["name"])

    _fill(pc, FakeEngine(between=look), [1, 2, 3], tmp_path)

    assert names == [
        "L ×3 — x (1/3, delete to cancel)",
        "L ×3 — x (2/3, delete to cancel)",
        "L ×3 — x",
    ]


def test_deleting_the_group_stops_the_variations_still_to_come(tmp_path: Path) -> None:
    pc = FakeControl(tmp_path)

    def artist(k: int) -> None:
        if k == 0:
            pc.cmd("layer.delete", {"layer": _poster(pc)["layers"][0]["id"]})

    with pytest.raises(Cancelled):
        _fill(pc, FakeEngine(between=artist), [1, 2, 3], tmp_path)
    assert _ids(_poster(pc)["layers"]) == [2]


def test_a_result_coming_after_the_group_was_deleted_is_a_cancel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pc = FakeControl(tmp_path)  # the Watch reads the layers every 2 s: one result may slip in

    def artist(k: int) -> None:
        if k == 0:
            pc.cmd("layer.delete", {"layer": _poster(pc)["layers"][0]["id"]})

    monkeypatch.setattr(placeholder, "Watch", lambda pc, holder: lambda: True)  # not seen yet
    with pytest.raises(Cancelled):
        _fill(pc, FakeEngine(between=artist), [1, 2], tmp_path)
    assert _ids(_poster(pc)["layers"]) == [2]


def test_a_failure_keeps_the_variations_that_came(tmp_path: Path) -> None:
    pc = FakeControl(tmp_path)

    def broken(k: int) -> None:
        raise RuntimeError("server down")

    with pytest.raises(RuntimeError, match="server down"):
        _fill(pc, FakeEngine(between=broken), [1, 2, 3], tmp_path)

    group = _poster(pc)["layers"][0]
    assert group["name"] == "L ×3 — x" and len(group["children"]) == 1  # no card left behind


def test_runs_side_by_side_keep_their_own_folders(tmp_path: Path) -> None:
    first = _fill(FakeControl(tmp_path), FakeEngine(), [1], tmp_path)
    second = _fill(FakeControl(tmp_path), FakeEngine(), [1], tmp_path)

    assert first.run != second.run
    assert (tmp_path / "runs" / first.run / "region.png").is_file()
    assert (tmp_path / "runs" / second.run / "region.png").is_file()


def test_only_the_newest_run_folders_are_kept(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    for i in range(12):
        (runs / f"old-{i:02}").mkdir(parents=True)

    _fill(FakeControl(tmp_path), FakeEngine(), [1], tmp_path)

    assert len(list(runs.iterdir())) == 10


def test_the_artist_can_switch_documents_while_it_generates(tmp_path: Path) -> None:
    pc = FakeControl(tmp_path)

    def artist() -> None:
        pc._open("sketch.png")
        pc.doc["selection"] = False

    _fill(pc, FakeEngine(artist), [1], tmp_path)

    assert pc.doc["name"] == "sketch.png"  # back where the artist was
    assert len(_poster(pc)["layers"]) == 2  # result in, placeholder out


def test_an_artist_on_another_layer_gets_it_back(tmp_path: Path) -> None:
    pc = FakeControl(tmp_path)

    painted: list[int] = []

    def artist() -> None:
        pc.cmd("layer.new.layer")
        painted.append(pc.doc["active"])
        pc.doc["selection"] = False

    _fill(pc, FakeEngine(artist), [1], tmp_path)

    poster = _poster(pc)
    assert len(poster["layers"]) == 3 and not poster["selection"]
    assert poster["active"] == painted[0]


def test_an_artist_painting_on_their_layer_keeps_it(tmp_path: Path) -> None:
    pc = FakeControl(tmp_path)

    _fill(pc, FakeEngine(lambda: pc.cmd("edit.fill", {"contents": "white"})), [1], tmp_path)

    poster = _poster(pc)
    assert poster["active"] == 2 and poster["layers"][1]["id"] == 2  # result above, theirs active


def test_deleting_the_placeholder_stops_the_generation(tmp_path: Path) -> None:
    pc = FakeControl(tmp_path)

    def artist() -> None:
        pc.cmd("layer.delete", {"layer": _card(pc)})

    with pytest.raises(Cancelled):
        _fill(pc, FakeEngine(artist), [1], tmp_path)
    assert [c for c, _ in pc.log].count("edit.pasteSpecial.pasteInPlace") == 1  # the card only
    assert _ids(_poster(pc)["layers"]) == [2]


def test_a_deletion_undone_before_the_next_check_goes_unnoticed(tmp_path: Path) -> None:
    pc = FakeControl(tmp_path)  # the bridge looks every half second: the run goes on

    def artist() -> None:
        layers = _poster(pc)["layers"]
        layers.insert(0, layers.pop(0))  # Ctrl+Z restores the very layer, same id

    _fill(pc, FakeEngine(artist), [1], tmp_path)

    assert len(_poster(pc)["layers"]) == 2  # result in, placeholder out


def test_the_check_reads_without_switching_documents(tmp_path: Path) -> None:
    pc = FakeControl(tmp_path)

    def artist() -> None:
        pc._open("sketch.png")  # the artist moved on to another document

    _fill(pc, FakeEngine(artist), [1], tmp_path)

    checks = [p for c, p in pc.log if c == "document.inspect" and "document" in p]
    assert checks == [{"document": 0}]  # the poster, read in place: nothing activated for it
    assert pc.doc["name"] == "sketch.png"


def test_a_placeholder_moved_into_a_group_is_still_there() -> None:
    class GroupedControl:
        def cmd(self, command: str, params: dict[str, Any] | None = None) -> Any:
            if command == "session.inspect":
                return {"documents": [{"index": 0, "name": "poster.png", "revision": 4}]}
            return {"layers": [{"id": 9, "children": [{"id": 12}]}, {"id": 2}]}

    pc = GroupedControl()
    assert placeholder.Watch(pc, Placeholder("poster.png", 12, 0))()  # type: ignore[arg-type]
    assert not placeholder.Watch(pc, Placeholder("poster.png", 13, 0))()  # type: ignore[arg-type]


def _inspections(pc: FakeControl) -> int:
    return sum(1 for c, p in pc.log if c == "document.inspect" and "document" in p)


def test_the_watch_reads_the_layers_only_after_the_document_changed(tmp_path: Path) -> None:
    pc = FakeControl(tmp_path)  # layers cost PhotoCraft every bounds; the revision is free
    watch = placeholder.Watch(pc, Placeholder("poster.png", 2, 0), every=0.0)  # type: ignore[arg-type]

    assert watch() and _inspections(pc) == 1  # first look
    assert watch() and _inspections(pc) == 1  # nothing changed: no layer read
    pc.cmd("edit.fill", {"contents": "white"})
    assert watch() and _inspections(pc) == 2  # changed: read again
    pc.cmd("layer.delete", {"layer": 2})
    assert not watch()


def test_the_watch_reads_the_layers_at_most_every_few_seconds(tmp_path: Path) -> None:
    pc = FakeControl(tmp_path)
    watch = placeholder.Watch(pc, Placeholder("poster.png", 2, 0), every=60.0)  # type: ignore[arg-type]

    assert watch()
    pc.cmd("layer.delete", {"layer": 2})
    assert watch() and _inspections(pc) == 1  # seen at the next slot, not now


def test_closing_the_document_cancels_too(tmp_path: Path) -> None:
    pc = FakeControl(tmp_path)
    watch = placeholder.Watch(pc, Placeholder("sketch.png", 2, 0))  # type: ignore[arg-type]
    assert not watch()  # no document of that name: the result has nowhere to go


def test_a_group_s_watch_follows_the_group(tmp_path: Path) -> None:
    pc = FakeControl(tmp_path)  # the card (2) is there, its group (99) is not
    holder = Placeholder("poster.png", layer=2, revision=0, group=99)
    assert not placeholder.Watch(pc, holder)()  # type: ignore[arg-type]


def test_two_documents_of_one_name_each_keep_their_own(tmp_path: Path) -> None:
    pc = FakeControl(tmp_path)  # the same file opened twice: the generation runs in the second
    pc.docs.insert(0, pc._doc("poster.png", 5, False))
    pc.active = 1

    _fill(pc, FakeEngine(), [1], tmp_path)

    assert _ids(pc.docs[0]["layers"]) == [5]  # untouched
    assert len(pc.docs[1]["layers"]) == 2  # result in, placeholder out
    assert pc.active == 1


def test_a_cancelled_result_leaves_the_artist_where_they_are(tmp_path: Path) -> None:
    pc = FakeControl(tmp_path)

    def artist() -> None:
        pc.cmd("layer.delete", {"layer": _card(pc)})  # deletes the placeholder, then moves on
        pc._open("sketch.png")

    with pytest.raises(Cancelled):
        _fill(pc, FakeEngine(artist), [1], tmp_path)
    assert pc.doc["name"] == "sketch.png"


def test_a_failed_generation_removes_the_placeholder(tmp_path: Path) -> None:
    pc = FakeControl(tmp_path)
    with pytest.raises(RuntimeError, match="server down"):
        _fill(pc, FakeEngine(fail=True), [1], tmp_path)
    assert _ids(_poster(pc)["layers"]) == [2]
    assert [c for c, _ in pc.log].count("edit.pasteSpecial.pasteInPlace") == 1  # the card only


def test_a_failed_run_of_variations_removes_its_group(tmp_path: Path) -> None:
    pc = FakeControl(tmp_path)
    with pytest.raises(RuntimeError, match="server down"):
        _fill(pc, FakeEngine(fail=True), [1, 2], tmp_path)
    assert _ids(_poster(pc)["layers"]) == [2]


def test_remove_shows_the_model_a_content_aware_fill_of_the_duplicate(tmp_path: Path) -> None:
    pc = FakeControl(tmp_path)
    roundtrip.remove_selection(pc, FakeEngine(), [1], tmp_path, "Remove (AI)")  # type: ignore[arg-type]
    commands = [c for c, _ in pc.log]
    caf = commands.index("edit.contentAwareFill")
    assert commands[caf - 1] == "image.duplicate" and commands.count("edit.contentAwareFill") == 1


def test_fill_selection_without_selection_touches_nothing(tmp_path: Path) -> None:
    pc = FakeControl(tmp_path, has_selection=False)
    with pytest.raises(roundtrip.NoSelectionError):
        _fill(pc, FakeEngine(), [1], tmp_path)
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

    outcome = roundtrip.fill_selection(
        pc, FakeEngine(), "a plate", [7, 8], tmp_path, "Generative Fill", "qwen-edit"
    )  # type: ignore[arg-type]

    kept = sorted(k.name.split("_", 1)[1] for k in (project / "xp-work" / "daylight_suv").iterdir())
    assert kept == ["fill_7.json", "fill_7.png", "fill_8.json", "fill_8.png"]
    sidecar = next((project / "xp-work" / "daylight_suv").glob("*_fill_7.json"))
    record = json.loads(sidecar.read_text(encoding="utf-8"))
    assert (record["prompt"], record["workflow"]) == ("a plate", "qwen-edit")
    assert (record["run"], record["seed"], record["variation"]) == (outcome.run, 7, 1)


def test_a_never_saved_document_keeps_nothing_beside_it(tmp_path: Path) -> None:
    assert roundtrip.project_work_dir("", tmp_path) is None
    assert (
        roundtrip.project_work_dir("in/opened.png", tmp_path)
        == tmp_path / "in" / "xp-work" / "opened"
    )
