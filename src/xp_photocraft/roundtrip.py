"""Selection → ComfyUI → masked layer, on the active PhotoCraft document.

Only existing PhotoCraft commands are used (measured on 0.5.0 and main, 2026-10-09):
the region and the mask leave through throwaway duplicates saved under the automation
root, and the result comes back through a full-size transparent PNG pasted in place,
masked by the user's own selection (saved to a temporary channel, then deleted).
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from PIL import Image

from xp_photocraft import workflows
from xp_photocraft.config import MARGIN_PX, MASK_FILE, PLACED_FILE, REGION_FILE, REMOVE_PROMPT
from xp_photocraft.control import Control, ControlError

logger = logging.getLogger(__name__)

SELECTION_CHANNEL = "xp-photocraft selection"


class Generator(Protocol):
    """What the round trip needs from ComfyUI (a seam for tests)."""

    def find_models(self, wanted: workflows.Models) -> workflows.Models: ...

    def upload(self, file: Path) -> str: ...

    def run(self, graph: dict[str, object]) -> bytes: ...


@dataclass(frozen=True)
class Rect:
    """A document-space rectangle, in pixels."""

    x: int
    y: int
    width: int
    height: int


class NoSelectionError(RuntimeError):
    """The active document has no selection to fill."""


def fill_selection(
    pc: Control, gen: Generator, prompt: str, seed: int, work: Path, layer_name: str
) -> Rect:
    """Repaint the active document's selection from ``prompt``; return the placed layer's rect."""
    return _repaint(pc, gen, prompt, seed, work, layer_name, prepare=())


def remove_selection(pc: Control, gen: Generator, seed: int, work: Path, layer_name: str) -> Rect:
    """Erase what the selection holds and rebuild the background; return the placed layer's rect.

    The model is shown PhotoCraft's classical Content-Aware Fill of the selection, not the
    object: given the object, the edit model redraws it (measured 2026-10-09 on the couple).
    """
    return _repaint(
        pc, gen, REMOVE_PROMPT, seed, work, layer_name, prepare=("edit.contentAwareFill",)
    )


def _repaint(
    pc: Control,
    gen: Generator,
    prompt: str,
    seed: int,
    work: Path,
    layer_name: str,
    prepare: tuple[str, ...],
) -> Rect:
    active, doc_size, bounds = _active_selection(pc)
    models = gen.find_models(workflows.Models())  # before touching the document
    crop = context_rect(bounds, doc_size, MARGIN_PX)
    pc.cmd("select.saveSelection", {"name": SELECTION_CHANNEL})
    try:
        _export_region(pc, active, crop, work / REGION_FILE, prepare)
        _export_mask(pc, active, crop, work / MASK_FILE)
        graph = workflows.inpaint(
            gen.upload(work / REGION_FILE), gen.upload(work / MASK_FILE), prompt, seed, models
        )
        result = Image.open(io.BytesIO(gen.run(graph)))
        write_placed(result, crop, doc_size, work / PLACED_FILE)
        _paste_masked(pc, active, layer_name)
    finally:
        _drop_selection_channel(pc, active)
    logger.info("%s placed at %s", layer_name, crop)
    return crop


def context_rect(bounds: Rect, doc_size: tuple[int, int], margin: int) -> Rect:
    """Grow ``bounds`` by ``margin`` on every side, clamped to the document."""
    x0, y0 = max(0, bounds.x - margin), max(0, bounds.y - margin)
    x1 = min(doc_size[0], bounds.x + bounds.width + margin)
    y1 = min(doc_size[1], bounds.y + bounds.height + margin)
    return Rect(x0, y0, x1 - x0, y1 - y0)


def write_placed(result: Image.Image, crop: Rect, doc_size: tuple[int, int], path: Path) -> None:
    """Write ``result`` fitted to ``crop`` on a transparent canvas the size of the document."""
    canvas = Image.new("RGBA", doc_size, (0, 0, 0, 0))
    canvas.paste(
        result.convert("RGBA").resize((crop.width, crop.height), Image.Resampling.LANCZOS),
        (crop.x, crop.y),
    )
    canvas.save(path)


def _active_selection(pc: Control) -> tuple[int, tuple[int, int], Rect]:
    active = int(pc.cmd("session.inspect")["active"])
    doc = pc.cmd("document.inspect")
    if not doc.get("hasSelection"):
        raise NoSelectionError("select the area to fill first")
    x, y, w, h = doc["selectionBounds"]
    return active, (int(doc["width"]), int(doc["height"])), Rect(x, y, w, h)


def _export_region(
    pc: Control, active: int, crop: Rect, path: Path, prepare: tuple[str, ...]
) -> None:
    # sRGB: the models expect display-referred pixels, and a PNG of a linear (EXR) document
    # keeps linear values under an embedded linear profile that ComfyUI ignores.
    pc.cmd("image.duplicate", {"name": "xp-photocraft region", "mergedOnly": True})
    for command in prepare:  # on the duplicate, while it still has the selection
        pc.cmd(command)
    pc.cmd("edit.convertToProfile", {"profile": "srgb"})
    pc.cmd("image.crop", {**_crop_params(crop), "deleteCroppedPixels": True})
    _save_and_close(pc, active, path)


def _export_mask(pc: Control, active: int, crop: Rect, path: Path) -> None:
    # The duplicate keeps the selection; crop would drop it, so paint the mask first.
    pc.cmd("image.duplicate", {"name": "xp-photocraft mask", "mergedOnly": True})
    pc.cmd("edit.fill", {"contents": "white"})
    pc.cmd("select.inverse")
    pc.cmd("edit.fill", {"contents": "black"})
    pc.cmd("image.crop", {**_crop_params(crop), "deleteCroppedPixels": True})
    _save_and_close(pc, active, path)


def _paste_masked(pc: Control, active: int, layer_name: str) -> None:
    # ponytail: copy/paste because placing a file is refused under automation (file.* paths);
    # it overwrites the clipboard. Swap for a capability-scoped place once PhotoCraft has one.
    pc.call("app.open", {"path": PLACED_FILE})
    pc.cmd("select.all")
    pc.cmd("edit.copy")
    pc.cmd("file.close")
    pc.cmd("document.activate", {"document": active})
    pc.cmd("edit.pasteSpecial.pasteInPlace")
    pc.cmd("layer.setProps", {"name": layer_name})
    pc.cmd("select.loadSelection", {"channel": SELECTION_CHANNEL})
    pc.cmd("layer.layerMask.revealSelection")


def _save_and_close(pc: Control, active: int, path: Path) -> None:
    pc.call("app.save", {"path": path.name})
    pc.cmd("file.close")
    pc.cmd("document.activate", {"document": active})


def _drop_selection_channel(pc: Control, active: int) -> None:
    try:
        pc.cmd("document.activate", {"document": active})
        pc.cmd("channel.delete", {"channel": SELECTION_CHANNEL})
    except ControlError:
        logger.exception("could not delete the temporary channel %r", SELECTION_CHANNEL)


def _crop_params(crop: Rect) -> dict[str, int]:
    return {"x": crop.x, "y": crop.y, "width": crop.width, "height": crop.height}
