"""Selection → engine → masked layer, on the active PhotoCraft document.

Only existing PhotoCraft commands are used (measured on 0.5.0 and main, 2026-10-09):
the region and the mask leave through throwaway duplicates saved under the automation
root; a placeholder card (crossed frame, action and prompt) then covers the selection while
the engine runs, and PhotoCraft is left alone, so the artist keeps working. The result comes
back through a full-size transparent PNG pasted in place of the placeholder (``placeholder``).
"""

from __future__ import annotations

import io
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from xp_photocraft import placeholder
from xp_photocraft.config import (
    MARGIN_PX,
    MASK_FILE,
    PLACED_FILE,
    PLACEHOLDER_FILE,
    PROJECT_WORK_DIR,
    REGION_FILE,
    REMOVE_PROMPT,
)
from xp_photocraft.control import Control
from xp_photocraft.engines import Engine

logger = logging.getLogger(__name__)


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
    pc: Control,
    engine: Engine,
    prompt: str,
    seed: int,
    work: Path,
    layer_name: str,
    workflow: str = "",
) -> Rect:
    """Repaint the active document's selection from ``prompt``; return the placed layer's rect."""
    return _repaint(pc, engine, prompt, seed, work, layer_name, "fill", workflow)


def remove_selection(
    pc: Control, engine: Engine, seed: int, work: Path, layer_name: str, workflow: str = ""
) -> Rect:
    """Erase what the selection holds and rebuild the background; return the placed layer's rect.

    The model is shown PhotoCraft's classical Content-Aware Fill of the selection, not the
    object: given the object, the edit model redraws it (measured 2026-10-09 on the couple).
    """
    return _repaint(pc, engine, REMOVE_PROMPT, seed, work, layer_name, "remove", workflow)


def _repaint(
    pc: Control,
    engine: Engine,
    prompt: str,
    seed: int,
    work: Path,
    layer_name: str,
    mode: str,
    workflow: str,
) -> Rect:
    active, doc_path, doc_size, bounds = _active_selection(pc)
    crop = context_rect(bounds, doc_size, MARGIN_PX)
    _export_region(pc, active, crop, work / REGION_FILE, mode)
    _export_mask(pc, active, crop, work / MASK_FILE)
    lines = (
        [layer_name, f'"{prompt}"', "generating…"]
        if mode == "fill"
        else [layer_name, "generating…"]
    )
    card = work / PLACEHOLDER_FILE
    placeholder.draw_card(card, doc_size, (bounds.x, bounds.y, bounds.width, bounds.height), lines)
    holder = placeholder.add(pc, card, layer_name)
    try:
        png = engine.generate(work / REGION_FILE, work / MASK_FILE, prompt, seed, mode)
        write_placed(Image.open(io.BytesIO(png)), crop, doc_size, work / PLACED_FILE)
        placeholder.place(pc, holder, layer_name)
    except BaseException:
        placeholder.discard(pc, holder)
        raise
    logger.info("%s placed at %s", layer_name, crop)
    record: dict[str, object] = {
        "document": doc_path,
        "mode": mode,
        "workflow": workflow,
        "prompt": prompt,
        "seed": seed,
        "layer": layer_name,
        "selection": [bounds.x, bounds.y, bounds.width, bounds.height],
        "placed": [crop.x, crop.y, crop.width, crop.height],
    }
    archive_result(png, record, project_work_dir(doc_path, work))
    return crop


def project_work_dir(doc_path: str, work: Path) -> Path | None:
    """``xp-work/<document stem>`` next to the document; None for a document never saved.

    A path relative to the automation root (a document the bridge opened itself) is resolved
    against the work dir.
    """
    if not doc_path:
        return None
    path = Path(doc_path)
    if not path.is_absolute():
        path = work / path
    return path.parent / PROJECT_WORK_DIR / path.stem


def archive_result(png: bytes, record: dict[str, object], folder: Path | None) -> None:
    """Keep the model's output and what made it next to the document (nothing without a folder)."""
    if folder is None:
        return
    try:
        folder.mkdir(parents=True, exist_ok=True)
        name = f"{time.strftime('%Y%m%d-%H%M%S')}_{record['mode']}_{record['seed']}"
        (folder / f"{name}.png").write_bytes(png)
        (folder / f"{name}.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    except OSError as e:  # a read-only or vanished project folder must not fail the fill
        logger.warning("result not archived in %s: %s", folder, e)


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


def _active_selection(pc: Control) -> tuple[int, str, tuple[int, int], Rect]:
    session = pc.cmd("session.inspect")
    active = int(session["active"])
    docs = session.get("documents", [])
    doc_path = str(next((d.get("path") or "" for d in docs if d.get("index") == active), ""))
    doc = pc.cmd("document.inspect")
    if not doc.get("hasSelection"):
        raise NoSelectionError("select the area to fill first")
    x, y, w, h = doc["selectionBounds"]
    return active, doc_path, (int(doc["width"]), int(doc["height"])), Rect(x, y, w, h)


def _export_region(pc: Control, active: int, crop: Rect, path: Path, mode: str) -> None:
    # sRGB: the models expect display-referred pixels, and a PNG of a linear (EXR) document
    # keeps linear values under an embedded linear profile that ComfyUI ignores.
    pc.cmd("image.duplicate", {"name": "xp-photocraft region", "mergedOnly": True})
    if mode == "remove":  # on the duplicate, while it still has the selection
        pc.cmd("edit.contentAwareFill")
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


def _save_and_close(pc: Control, active: int, path: Path) -> None:
    pc.call("app.save", {"path": path.name})
    pc.cmd("file.close")
    pc.cmd("document.activate", {"document": active})


def _crop_params(crop: Rect) -> dict[str, int]:
    return {"x": crop.x, "y": crop.y, "width": crop.width, "height": crop.height}
