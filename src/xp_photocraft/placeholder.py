"""The placeholder layer that stands where a result will land, so the artist keeps working.

``add`` pastes a placeholder card over the selection (a crossed frame naming the action and the
prompt), masked by the selection, and hands the artist's layer back. The generation then runs
without touching PhotoCraft. ``place`` finds the document again (by name, then by the placeholder
layer), pastes the result just above the placeholder, masks it with the placeholder's mask (the
selection), deletes the placeholder and restores whatever document, layer and selection the
artist has by then.

A run of several variations puts the card in a group that carries the selection's mask:
``place_variation`` pastes each result into it as it comes (the first one shown, the others
hidden), and the card goes with the first. ``finish`` names the group once the run is over.

Deleting the placeholder (the group, for variations) meanwhile cancels the run for good: a
``Watch`` is asked at every poll of the generation, which is then stopped. Undoing the deletion
brings the card back alone.

Each of these edits one document through several commands; they share one undo step
(PhotoCraft's ``coalesce``), so a run never pushes the artist's own steps out of History.
"""

from __future__ import annotations

import logging
import textwrap
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from xp_photocraft.config import LAYER_CHECK_S
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
    # The group holding the card and the variations; 0 for a single result.
    group: int = 0

    @property
    def watched(self) -> int:
        """The layer whose deletion cancels the run: the group, else the card."""
        return self.group or self.layer


class _Step:
    """Edits of one document that share one undo step (PhotoCraft's ``coalesce`` key)."""

    def __init__(self, pc: Control, key: str) -> None:
        self._pc, self._key = pc, key

    def edit(self, command: str, params: dict[str, Any] | None = None) -> Any:
        return self._pc.cmd(command, {**(params or {}), "coalesce": self._key})


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


def add(pc: Control, card: str, layer_name: str, step: str, group: str = "") -> Placeholder:
    """Paste ``card`` over the active document's selection as the placeholder layer.

    ``card`` is a path under the automation root. With a ``group`` name, the card goes into a
    new group of that name, which carries the selection's mask (a run of variations).
    """
    edits = _Step(pc, step)
    doc = pc.cmd("document.inspect")
    active = int(pc.cmd("session.inspect")["active"])
    edits.edit("select.saveSelection", {"name": SELECTION_CHANNEL})
    try:
        _copy_file(pc, card)
        pc.cmd("document.activate", {"document": active})
        edits.edit("edit.pasteSpecial.pasteInPlace")
        layer = int(pc.cmd("document.inspect")["activeLayer"])
        edits.edit("layer.setProps", {"layer": layer, "name": f"{layer_name} ({GENERATING})"})
        group_id = 0
        if group:
            group_id = int(edits.edit("layer.new.group", {"name": group})["layer"])
            edits.edit("layer.moveTo", {"layer": layer, "target": group_id, "position": "into"})
        edits.edit("select.loadSelection", {"channel": SELECTION_CHANNEL})
        edits.edit("layer.layerMask.revealSelection", {"layer": group_id or layer})
    finally:
        edits.edit("channel.delete", {"channel": SELECTION_CHANNEL})
    if doc.get("activeLayer") is not None:
        pc.cmd("layer.select", {"layer": doc["activeLayer"]})
    revision = int(pc.cmd("document.inspect")["revision"])
    return Placeholder(str(doc["name"]), layer, revision, group_id)


def place(pc: Control, placeholder: Placeholder, placed: str, layer_name: str, step: str) -> int:
    """Replace the placeholder by the result in ``placed``, masked like the placeholder.

    Return the result's layer id.
    """
    edits = _Step(pc, step)
    artist_doc = int(pc.cmd("session.inspect")["active"])
    _activate(pc, placeholder)  # fails early, before the clipboard is touched
    _copy_file(pc, placed)
    doc = _activate(pc, placeholder)
    if doc["hasSelection"]:
        edits.edit("select.saveSelection", {"name": ARTIST_CHANNEL})
    pc.cmd("layer.select", {"layer": placeholder.layer})
    edits.edit("edit.pasteSpecial.pasteInPlace")
    result = int(pc.cmd("document.inspect")["activeLayer"])
    edits.edit("layer.setProps", {"layer": result, "name": layer_name})
    edits.edit("select.loadSelection", {"channel": "mask", "layer": placeholder.layer})
    edits.edit("layer.layerMask.revealSelection", {"layer": result})
    edits.edit("layer.delete", {"layer": placeholder.layer})
    _restore(pc, edits, doc, placeholder, artist_doc, result)
    return result


def place_variation(
    pc: Control,
    placeholder: Placeholder,
    placed: str,
    layer_name: str,
    shown: bool,
    group_name: str,
    step: str,
) -> int:
    """Paste the result in ``placed`` into the group, on top, shown or hidden; rename the group.

    The card leaves with the first variation. Return the variation's layer id.
    """
    edits = _Step(pc, step)
    artist_doc = int(pc.cmd("session.inspect")["active"])
    _activate(pc, placeholder)
    _copy_file(pc, placed)
    doc = _activate(pc, placeholder)
    children = _find(doc["layers"], placeholder.group).get("children", [])
    if doc["hasSelection"]:
        edits.edit("select.saveSelection", {"name": ARTIST_CHANNEL})
    # Pasted above the active layer: a child of the group, so the result lands inside it.
    pc.cmd("layer.select", {"layer": children[0]["id"]})
    edits.edit("edit.pasteSpecial.pasteInPlace")
    result = int(pc.cmd("document.inspect")["activeLayer"])
    edits.edit("layer.setProps", {"layer": result, "name": layer_name, "visible": shown})
    if any(child["id"] == placeholder.layer for child in children):
        edits.edit("layer.delete", {"layer": placeholder.layer})
    edits.edit("layer.setProps", {"layer": placeholder.group, "name": group_name})
    _restore(pc, edits, doc, placeholder, artist_doc, placeholder.group)
    return result


def finish(pc: Control, placeholder: Placeholder, group_name: str, step: str) -> None:
    """End a run of variations: the card goes if it is still there, the group takes its name."""
    edits = _Step(pc, step)
    try:
        artist_doc = int(pc.cmd("session.inspect")["active"])
        doc = _activate(pc, placeholder)
        if _has_layer(doc["layers"], placeholder.layer):
            edits.edit("layer.delete", {"layer": placeholder.layer})
        edits.edit("layer.setProps", {"layer": placeholder.group, "name": group_name})
        pc.cmd("document.activate", {"document": artist_doc})
    except (ControlError, PlacementError):
        logger.info("group of %s already gone", placeholder)


class Watch:
    """Answers whether the placeholder is still there, cheaply enough to be asked twice a second.

    Only reads, and the active document stays. ``session.inspect`` costs PhotoCraft nothing and
    gives each document's revision, which any edit (a deleted layer included) moves; the layers
    themselves are read only after it moved, at most every ``every`` seconds.
    """

    def __init__(self, pc: Control, placeholder: Placeholder, every: float = LAYER_CHECK_S) -> None:
        self._pc, self._placeholder, self._every = pc, placeholder, every
        self._seen: tuple[int, ...] = ()
        self._next = 0.0

    def __call__(self) -> bool:
        session = self._pc.cmd("session.inspect")
        named = [d for d in session["documents"] if d["name"] == self._placeholder.document]
        if not named:
            return False  # its document was closed: the result has nowhere to go
        revisions = tuple(int(d["revision"]) for d in named)
        if revisions == self._seen or time.monotonic() < self._next:
            return True
        self._seen, self._next = revisions, time.monotonic() + self._every
        return any(
            _has_layer(
                self._pc.cmd("document.inspect", {"document": d["index"]})["layers"],
                self._placeholder.watched,
            )
            for d in named
        )


def discard(pc: Control, placeholder: Placeholder, step: str) -> None:
    """Delete the placeholder (a run of variations: its group) after a failure or a cancel."""
    try:
        artist_doc = int(pc.cmd("session.inspect")["active"])
        _activate(pc, placeholder)
        _Step(pc, step).edit("layer.delete", {"layer": placeholder.watched})
        pc.cmd("document.activate", {"document": artist_doc})
    except (ControlError, PlacementError):
        logger.info("placeholder %s already gone", placeholder)


def _copy_file(pc: Control, path: str) -> None:
    # ponytail: copy/paste because placing a file is refused under automation (file.* paths);
    # it overwrites the clipboard. Swap for a capability-scoped place once PhotoCraft has one.
    pc.call("app.open", {"path": path})
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
        if _has_layer(doc["layers"], placeholder.watched):
            return doc
    pc.cmd("document.activate", {"document": session["active"]})
    raise PlacementError("placeholder deleted: result not placed")


def _has_layer(layers: list[dict[str, Any]], layer_id: int) -> bool:
    return bool(_find(layers, layer_id))


def _find(layers: list[dict[str, Any]], layer_id: int) -> dict[str, Any]:
    """The layer ``layer_id`` anywhere in the tree (groups list theirs under "children"); {}."""
    for layer in layers:
        if layer["id"] == layer_id:
            return layer
        found = _find(layer.get("children", []), layer_id)
        if found:
            return found
    return {}


def _restore(
    pc: Control,
    edits: _Step,
    before: dict[str, Any],
    placeholder: Placeholder,
    artist_doc: int,
    result: int,
) -> None:
    """Give the artist back the selection, layer and document they had before the paste."""
    if before["hasSelection"]:
        edits.edit("select.loadSelection", {"channel": ARTIST_CHANNEL})
        edits.edit("channel.delete", {"channel": ARTIST_CHANNEL})
    else:
        edits.edit("select.deselect")
    # Like Photoshop the result stays selected (a group of variations shows its picker), so the
    # next one stacks above it; unless the artist worked in this document meanwhile, or moved to
    # another layer: they keep the layer they were on.
    worked = before["revision"] != placeholder.revision
    kept = before.get("activeLayer")
    if worked and kept not in (None, placeholder.layer):
        pc.cmd("layer.select", {"layer": kept})
    else:
        pc.cmd("layer.select", {"layer": result})
    pc.cmd("document.activate", {"document": artist_doc})


def _wrap(lines: list[str], width: int, size: int) -> list[str]:
    """Wrap each line to the frame's width; a long prompt keeps its first three lines."""
    chars = max(8, int(width * 0.8 / (size * 0.55)))
    out: list[str] = []
    for line in lines:
        wrapped = textwrap.wrap(line, chars) or [""]
        out += wrapped[:3] if len(wrapped) <= 3 else [*wrapped[:2], wrapped[2][: chars - 1] + "…"]
    return out
