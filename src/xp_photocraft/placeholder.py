"""The placeholder layer that stands where a result will land, so the artist keeps working.

``add`` pastes a placeholder card over the selection (a crossed frame naming the action and the
prompt), masked by the selection, and hands the artist's layer back. The generation then runs
without touching PhotoCraft. ``place`` finds the document again (by name, then by the placeholder
layer), pastes the result just
above the placeholder, masks it with the placeholder's mask (the selection), deletes the
placeholder and restores whatever document, layer and selection the artist has by then.

Deleting the placeholder meanwhile cancels the run for good: ``exists`` is asked at every poll of
the generation, which is then stopped. Undoing the deletion brings the card back alone.
"""

from __future__ import annotations

import logging
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from xp_photocraft.config import PLACED_FILE
from xp_photocraft.control import Control, ControlError

logger = logging.getLogger(__name__)

# The paste drops the selection: it waits here meanwhile (then the result's mask, the artist's).
SELECTION_CHANNEL = "xp-photocraft selection"
ARTIST_CHANNEL = "xp-photocraft artist selection"
_CARD_FILL = (24, 26, 32, 150)
_CARD_LINE = (255, 255, 255, 170)
_CARD_TEXT = (255, 255, 255, 255)
# The card's last line and the layer's name: what the layer is, and how to cancel it.
GENERATING = "generating… delete to cancel"


class PlacementError(RuntimeError):
    """The result has nowhere to go: its document was closed or its placeholder deleted."""


@dataclass(frozen=True)
class Placeholder:
    """A placeholder layer, by document name (indices shift as documents open and close)."""

    document: str
    layer: int
    # The document's revision once it was added: any edit, layer or selection change moves it
    # (switching documents does not), which tells whether the artist worked there meanwhile.
    revision: int


def draw_card(
    path: Path, doc_size: tuple[int, int], bounds: tuple[int, int, int, int], lines: list[str]
) -> None:
    """Write a document-size PNG with a crossed, captioned frame over ``bounds``."""
    canvas = Image.new("RGBA", doc_size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    x, y, w, h = bounds
    x1, y1 = x + w - 1, y + h - 1
    stroke = max(2, min(w, h) // 120)
    draw.rectangle((x, y, x1, y1), fill=_CARD_FILL, outline=_CARD_LINE, width=stroke)
    draw.line((x, y, x1, y1), fill=_CARD_LINE, width=stroke)
    draw.line((x, y1, x1, y), fill=_CARD_LINE, width=stroke)
    size = max(12, min(40, min(w, h) // 9))
    font = ImageFont.load_default(size)
    pad = size // 2
    # A smaller frame drops the prompt, then "generating…", then keeps just its cross.
    for shown in (lines, [lines[0], lines[-1]], lines[:1]):
        text = "\n".join(_wrap(shown, w, size))
        box = draw.multiline_textbbox((0, 0), text, font=font, align="center")
        tw, th = box[2] - box[0], box[3] - box[1]
        if tw + 2 * pad <= w and th + 2 * pad <= h:
            at = (x + (w - tw) // 2, y + (h - th) // 2)
            plate = (at[0] - pad, at[1] - pad, at[0] + tw + pad, at[1] + th + pad)
            draw.rectangle(plate, fill=_CARD_FILL)
            draw.multiline_text(at, text, font=font, fill=_CARD_TEXT, align="center")
            break
    canvas.save(path)


def add(pc: Control, card: Path, layer_name: str) -> Placeholder:
    """Paste ``card`` over the active document's selection as the placeholder layer."""
    doc = pc.cmd("document.inspect")
    active = int(pc.cmd("session.inspect")["active"])
    pc.cmd("select.saveSelection", {"name": SELECTION_CHANNEL})
    try:
        _copy_file(pc, card.name)
        pc.cmd("document.activate", {"document": active})
        pc.cmd("edit.pasteSpecial.pasteInPlace")
        layer = int(pc.cmd("document.inspect")["activeLayer"])
        pc.cmd("layer.setProps", {"layer": layer, "name": f"{layer_name} ({GENERATING})"})
        pc.cmd("select.loadSelection", {"channel": SELECTION_CHANNEL})
        pc.cmd("layer.layerMask.revealSelection")
    finally:
        pc.cmd("channel.delete", {"channel": SELECTION_CHANNEL})
    if doc.get("activeLayer") is not None:
        pc.cmd("layer.select", {"layer": doc["activeLayer"]})
    return Placeholder(str(doc["name"]), layer, int(pc.cmd("document.inspect")["revision"]))


def place(pc: Control, placeholder: Placeholder, layer_name: str) -> None:
    """Replace the placeholder by the result in ``PLACED_FILE``, masked like the placeholder."""
    artist_doc = int(pc.cmd("session.inspect")["active"])
    _activate(pc, placeholder)  # fails early, before the clipboard is touched
    _copy_file(pc, PLACED_FILE)
    doc = _activate(pc, placeholder)
    if doc["hasSelection"]:
        pc.cmd("select.saveSelection", {"name": ARTIST_CHANNEL})
    pc.cmd("layer.select", {"layer": placeholder.layer})
    pc.cmd("edit.pasteSpecial.pasteInPlace")
    pc.cmd("layer.setProps", {"name": layer_name})
    pc.cmd("select.loadSelection", {"channel": "mask", "layer": placeholder.layer})
    pc.cmd("layer.layerMask.revealSelection")
    pc.cmd("layer.delete", {"layer": placeholder.layer})
    _restore(pc, doc, placeholder, artist_doc)


def exists(pc: Control, placeholder: Placeholder) -> bool:
    """Whether the placeholder is still in its document; only reads, the active one stays."""
    session = pc.cmd("session.inspect")
    named = [d["index"] for d in session["documents"] if d["name"] == placeholder.document]
    return any(
        _has_layer(pc.cmd("document.inspect", {"document": i})["layers"], placeholder.layer)
        for i in named
    )


def discard(pc: Control, placeholder: Placeholder) -> None:
    """Delete the placeholder if it is still there (a failed or cancelled run)."""
    try:
        artist_doc = int(pc.cmd("session.inspect")["active"])
        _activate(pc, placeholder)
        pc.cmd("layer.delete", {"layer": placeholder.layer})
        pc.cmd("document.activate", {"document": artist_doc})
    except (ControlError, PlacementError):
        logger.info("placeholder %s already gone", placeholder)


def _copy_file(pc: Control, name: str) -> None:
    # ponytail: copy/paste because placing a file is refused under automation (file.* paths);
    # it overwrites the clipboard. Swap for a capability-scoped place once PhotoCraft has one.
    pc.call("app.open", {"path": name})
    pc.cmd("select.all")
    pc.cmd("edit.copy")
    pc.cmd("file.close")


def _activate(pc: Control, placeholder: Placeholder) -> dict[str, Any]:
    """Make the placeholder's document active; return its inspection.

    Found by name, then by the placeholder layer: layer ids are unique in a PhotoCraft session,
    so the same file opened twice is no ambiguity. When the placeholder is gone, the artist's
    document is made active again.
    """
    session = pc.cmd("session.inspect")
    named = [d["index"] for d in session["documents"] if d["name"] == placeholder.document]
    if not named:
        raise PlacementError(f"{placeholder.document!r} was closed: result not placed")
    for index in named:
        pc.cmd("document.activate", {"document": index})
        doc: dict[str, Any] = pc.cmd("document.inspect")
        if _has_layer(doc["layers"], placeholder.layer):
            return doc
    pc.cmd("document.activate", {"document": session["active"]})
    raise PlacementError("placeholder deleted: result not placed")


def _has_layer(layers: list[dict[str, Any]], layer_id: int) -> bool:
    # A group lists its layers under "children": the artist may move the card into one.
    return any(
        layer["id"] == layer_id or _has_layer(layer.get("children", []), layer_id)
        for layer in layers
    )


def _restore(
    pc: Control, before: dict[str, Any], placeholder: Placeholder, artist_doc: int
) -> None:
    """Give the artist back the selection, layer and document they had before the paste."""
    if before["hasSelection"]:
        pc.cmd("select.loadSelection", {"channel": ARTIST_CHANNEL})
        pc.cmd("channel.delete", {"channel": ARTIST_CHANNEL})
    else:
        pc.cmd("select.deselect")
    # Like Photoshop the result stays selected, so the next one stacks above it; unless the
    # artist worked in this document meanwhile: they keep the layer they were on.
    worked = before["revision"] != placeholder.revision
    if worked and before.get("activeLayer") not in (None, placeholder.layer):
        pc.cmd("layer.select", {"layer": before["activeLayer"]})
    pc.cmd("document.activate", {"document": artist_doc})


def _wrap(lines: list[str], width: int, size: int) -> list[str]:
    """Wrap each line to the frame's width; a long prompt keeps its first three lines."""
    chars = max(8, int(width * 0.8 / (size * 0.55)))
    out: list[str] = []
    for line in lines:
        wrapped = textwrap.wrap(line, chars) or [""]
        out += wrapped[:3] if len(wrapped) <= 3 else [*wrapped[:2], wrapped[2][: chars - 1] + "…"]
    return out
