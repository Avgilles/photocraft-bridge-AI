"""Selection → engine → masked layer(s), on the active PhotoCraft document.

Only existing PhotoCraft commands are used (measured on 0.5.0 and main, 2026-10-09):
the region and the mask leave through throwaway duplicates saved under the automation
root; a placeholder card (crossed frame, action and prompt) then covers the selection while
the engine runs, and PhotoCraft is left alone, so the artist keeps working. The result comes
back through a full-size transparent PNG pasted in place of the placeholder (``placeholder``).

A run of several seeds is a run of variations: they land one by one in a group carrying the
selection's mask, the first shown, the others hidden, for the artist to pick from. Each run
works in its own folder of the work dir, and edits PhotoCraft only while holding the lock
(``control.exclusive``), so runs started side by side wait their turn there and nowhere else.
"""

from __future__ import annotations

import io
import json
import logging
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from xp_photocraft import placeholder
from xp_photocraft.comfy import Cancelled
from xp_photocraft.config import (
    KEEP_RUNS,
    MARGIN_PX,
    MASK_FILE,
    PLACEHOLDER_FILE,
    PROJECT_WORK_DIR,
    REGION_FILE,
    REMOVE_PROMPT,
    RUNS_DIR,
)
from xp_photocraft.control import Control, exclusive
from xp_photocraft.engines import Engine

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Rect:
    """A document-space rectangle, in pixels."""

    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class Variation:
    """One placed result: its layer and the seed that made it."""

    layer: int
    seed: int


@dataclass(frozen=True)
class Outcome:
    """What a run placed: where, in which group (0: a single layer), which variations."""

    rect: Rect
    run: str
    group: int
    variations: list[Variation]


class NoSelectionError(RuntimeError):
    """The active document has no selection to fill."""


def fill_selection(
    pc: Control,
    engine: Engine,
    prompt: str,
    seeds: list[int],
    work: Path,
    layer_name: str,
    workflow: str = "",
) -> Outcome:
    """Repaint the active document's selection from ``prompt``, once per seed."""
    return _repaint(pc, engine, prompt, seeds, work, layer_name, "fill", workflow)


def remove_selection(
    pc: Control, engine: Engine, seeds: list[int], work: Path, layer_name: str, workflow: str = ""
) -> Outcome:
    """Erase what the selection holds and rebuild the background, once per seed.

    The model is shown PhotoCraft's classical Content-Aware Fill of the selection, not the
    object: given the object, the edit model redraws it (measured 2026-10-09 on the couple).
    """
    return _repaint(pc, engine, REMOVE_PROMPT, seeds, work, layer_name, "remove", workflow)


def _repaint(
    pc: Control,
    engine: Engine,
    prompt: str,
    seeds: list[int],
    work: Path,
    layer_name: str,
    mode: str,
    workflow: str,
) -> Outcome:
    run = _Run(work, layer_name, prompt if mode == "fill" else "", len(seeds))
    with exclusive(work):
        batch = _start(pc, run, layer_name, prompt, mode, workflow, seeds)
    try:
        engine.generate(
            run.dir / REGION_FILE,
            run.dir / MASK_FILE,
            prompt,
            seeds,
            mode,
            batch.land,
            still_wanted=placeholder.Watch(pc, batch.holder),
        )
    except BaseException:
        batch.abort()
        raise
    return Outcome(batch.crop, run.id, batch.holder.group, batch.placed)


def _start(
    pc: Control,
    run: _Run,
    layer_name: str,
    prompt: str,
    mode: str,
    workflow: str,
    seeds: list[int],
) -> _Batch:
    """Export the region and the mask, put the card: what a run does in PhotoCraft, then waits."""
    active, doc_path, doc_size, bounds = _active_selection(pc)
    crop = context_rect(bounds, doc_size, MARGIN_PX)
    _export_region(pc, active, crop, run.path(REGION_FILE), mode)
    _export_mask(pc, active, crop, run.path(MASK_FILE))
    lines = [layer_name, f'"{prompt}"'] if mode == "fill" else [layer_name]
    box = (bounds.x, bounds.y, bounds.width, bounds.height)
    placeholder.draw_card(
        run.dir / PLACEHOLDER_FILE, doc_size, box, [*lines, placeholder.GENERATING]
    )
    group = run.group_name(0) if len(seeds) > 1 else ""
    holder = placeholder.add(pc, run.path(PLACEHOLDER_FILE), layer_name, run.step(0), group)
    record: dict[str, object] = {
        "document": doc_path,
        "mode": mode,
        "workflow": workflow,
        "prompt": prompt,
        "layer": layer_name,
        "run": run.id,
        "selection": [bounds.x, bounds.y, bounds.width, bounds.height],
        "placed": [crop.x, crop.y, crop.width, crop.height],
    }
    archive = project_work_dir(doc_path, run.work)
    return _Batch(pc, run, holder, crop, doc_size, seeds, layer_name, record, archive)


@dataclass
class _Batch:
    """A run under way: where its results land, and those that did."""

    pc: Control
    run: _Run
    holder: placeholder.Placeholder
    crop: Rect
    doc_size: tuple[int, int]
    seeds: list[int]
    layer_name: str
    record: dict[str, object]
    archive: Path | None
    placed: list[Variation] = field(default_factory=list)

    def land(self, k: int, png: bytes) -> None:
        """Place result ``k`` (the engine's ``on_image``), then keep it in xp-work."""
        name = f"placed-{k + 1}.png"
        write_placed(Image.open(io.BytesIO(png)), self.crop, self.doc_size, self.run.dir / name)
        try:
            with exclusive(self.run.work):
                layer = self._place(k, self.run.path(name))
        except placeholder.PlacementError as e:
            # Gone between two looks of the Watch (it reads the layers every few seconds).
            raise Cancelled(str(e)) from e
        self.placed.append(Variation(layer, self.seeds[k]))
        count = len(self.seeds)
        logger.info("%s %d/%d placed at %s", self.layer_name, len(self.placed), count, self.crop)
        variation = {"seed": self.seeds[k], "variation": k + 1, "variations": count}
        archive_result(png, self.record | variation, self.archive)

    def _place(self, k: int, path: str) -> int:
        if not self.holder.group:
            return placeholder.place(self.pc, self.holder, path, self.layer_name, self.run.step(1))
        arrived = len(self.placed) + 1
        return placeholder.place_variation(
            self.pc,
            self.holder,
            path,
            self.run.variation_name(k, self.seeds[k]),
            shown=not self.placed,
            group_name=self.run.group_name(None if arrived == len(self.seeds) else arrived),
            step=self.run.step(k + 1),
        )

    def abort(self) -> None:
        """After a failure or a cancel: keep the variations that came, else take the card away."""
        step = self.run.step(len(self.seeds) + 1)
        with exclusive(self.run.work):
            if not self.placed:
                placeholder.discard(self.pc, self.holder, step)
            elif self.holder.group:  # named for what it holds
                placeholder.finish(self.pc, self.holder, self.run.group_name(None), step)


class _Run:
    """One run's folder in the work dir, and the names it gives PhotoCraft."""

    def __init__(self, work: Path, layer_name: str, prompt: str, count: int) -> None:
        self.id = f"{time.strftime('%H%M%S')}-{uuid.uuid4().hex[:4]}"
        self.work = work
        self.dir = work / RUNS_DIR / self.id
        self.dir.mkdir(parents=True)
        self._title = f"{layer_name} ×{count}" + (f" — {_short(prompt)}" if prompt else "")
        self._count = count
        _prune_runs(work / RUNS_DIR)

    def path(self, name: str) -> str:
        """``name`` in this run's folder, as PhotoCraft's automation root sees it."""
        return f"{RUNS_DIR}/{self.id}/{name}"

    def step(self, k: int) -> str:
        """The undo step of the run's ``k``-th edit (0: the card, then one per result)."""
        return f"xp-photocraft {self.id} {k}"

    def group_name(self, arrived: int | None) -> str:
        """The group's name: while generating (``arrived`` results so far), then for good."""
        if arrived is None:
            return self._title
        if arrived == 0:
            return f"{self._title} ({placeholder.GENERATING})"
        return f"{self._title} ({arrived}/{self._count}, delete to cancel)"

    def variation_name(self, k: int, seed: int) -> str:
        """``Variation <n> · seed <s> · <run>``: what PhotoCraft XP's picker and a re-run read."""
        return f"Variation {k + 1} · seed {seed} · {self.id}"


def _short(prompt: str, chars: int = 40) -> str:
    return prompt if len(prompt) <= chars else prompt[: chars - 1].rstrip() + "…"


def _prune_runs(runs: Path, keep: int = KEEP_RUNS) -> None:
    """Keep the newest run folders (a re-run needs them), delete the others."""
    folders = sorted((p for p in runs.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime)
    for old in folders[:-keep]:
        shutil.rmtree(old, ignore_errors=True)


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


def _export_region(pc: Control, active: int, crop: Rect, path: str, mode: str) -> None:
    # sRGB: the models expect display-referred pixels, and a PNG of a linear (EXR) document
    # keeps linear values under an embedded linear profile that ComfyUI ignores.
    pc.cmd("image.duplicate", {"name": "xp-photocraft region", "mergedOnly": True})
    if mode == "remove":  # on the duplicate, while it still has the selection
        pc.cmd("edit.contentAwareFill")
    pc.cmd("edit.convertToProfile", {"profile": "srgb"})
    pc.cmd("image.crop", {**_crop_params(crop), "deleteCroppedPixels": True})
    _save_and_close(pc, active, path)


def _export_mask(pc: Control, active: int, crop: Rect, path: str) -> None:
    # The duplicate keeps the selection; crop would drop it, so paint the mask first.
    pc.cmd("image.duplicate", {"name": "xp-photocraft mask", "mergedOnly": True})
    pc.cmd("edit.fill", {"contents": "white"})
    pc.cmd("select.inverse")
    pc.cmd("edit.fill", {"contents": "black"})
    pc.cmd("image.crop", {**_crop_params(crop), "deleteCroppedPixels": True})
    _save_and_close(pc, active, path)


def _save_and_close(pc: Control, active: int, path: str) -> None:
    pc.call("app.save", {"path": path})
    pc.cmd("file.close")
    pc.cmd("document.activate", {"document": active})


def _crop_params(crop: Rect) -> dict[str, int]:
    return {"x": crop.x, "y": crop.y, "width": crop.width, "height": crop.height}
