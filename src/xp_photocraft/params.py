"""A workflow's settings: the fields its App Builder save shows, set per run or per variation.

ComfyUI's App Mode keeps the inputs an app shows in its saved workflow, under
``extra.linearData.inputs``: ``[widgetId, name, config]``, ``widgetId`` being
``<graph>:<node>:<widget>`` (URI-encoded parts) or, in older saves, a node id with the widget's
name beside it. The bridge runs the API export of the same graph, whose nodes keep their ids, so a
field is ``graph[node]["inputs"][widget]``: its id here is ``<node>.<widget>``. A field promoted
from a subgraph names the subgraph's node, which the API export flattens away: it is left out,
with a warning. Inputs the bridge fills itself (the ``pc:*`` roles) are left out silently.

On the command line a setting is ``id=value``; a varied one ``id=a..b`` (numbers, spread from a
to b over the variations) or ``id=a|b|c`` (taken in turn).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import unquote

# The inputs each role's node gets from the bridge: never a setting.
_OWNED = {
    "pc:image": {"image"},
    "pc:mask": {"image"},
    "pc:prompt": {"prompt", "text", "seed", "noise_seed"},
    "pc:seed": {"seed", "noise_seed"},
    "pc:scale": {"megapixels", "resolution"},
}


class SettingsError(ValueError):
    """A setting names no input of the workflow, or its value does not fit it."""


@dataclass(frozen=True)
class Param:
    """One field the workflow's app shows: what PhotoCraft XP draws a control for."""

    id: str
    label: str
    description: str
    # "int", "float", "bool", "choice" or "text".
    kind: str
    default: Any
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    choices: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        """The ``params@1`` entry."""
        return asdict(self) | {"choices": list(self.choices)}


def app_params(
    app: dict[str, Any], graph: dict[str, Any], spec: Callable[[str], dict[str, Any] | None]
) -> tuple[list[Param], list[str]]:
    """The settings ``app`` shows that ``graph`` (its API export) runs, and what was left out.

    ``spec(class_type)`` is the node's input spec from the server (``/object_info``), or None:
    the kind then comes from the value in the export, without range or choices.
    """
    params: list[Param] = []
    warnings: list[str] = []
    for entry in app.get("extra", {}).get("linearData", {}).get("inputs", []):
        node_id, name = _target(entry)
        label = str(entry[1]) if len(entry) > 1 and entry[1] else name
        node = graph.get(node_id)
        if node is None:
            warnings.append(f"{label}: not in the API export (promoted from a subgraph?), left out")
            continue
        value = node.get("inputs", {}).get(name)
        if value is None or isinstance(value, list) or name in _owned(node):
            continue  # a link, or what the bridge sets itself
        config = entry[2] if len(entry) > 2 and isinstance(entry[2], dict) else {}
        input_spec = _input_spec(spec(str(node.get("class_type"))), name)
        description = str(config.get("description", ""))
        params.append(_typed(f"{node_id}.{name}", label, description, value, input_spec))
    return params, warnings


def settings_for(
    graph: dict[str, Any], fixed: dict[str, str], varied: dict[str, str], count: int
) -> list[dict[str, Any]]:
    """One dict of input values per variation, typed like the export's own values."""
    values = {key: _coerce(graph, key, text) for key, text in fixed.items()}
    spread = {key: _spread(graph, key, text, count) for key, text in varied.items()}
    return [values | {key: series[k] for key, series in spread.items()} for k in range(count)]


def apply(graph: dict[str, Any], settings: dict[str, Any]) -> None:
    """Set ``settings`` (``<node>.<input>``: value) in ``graph``, in place."""
    for key, value in settings.items():
        node_id, name = key.rsplit(".", 1)
        graph[node_id]["inputs"][name] = value


def parse_pairs(pairs: tuple[str, ...]) -> dict[str, str]:
    """``("id=value", ...)`` from the command line, as a dict."""
    parsed: dict[str, str] = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not key.strip():
            raise SettingsError(f"{pair!r}: expected id=value")
        parsed[key.strip()] = value.strip()
    return parsed


def _target(entry: list[Any]) -> tuple[str, str]:
    parts = str(entry[0]).split(":")
    if len(parts) == 3:  # graph:node:widget
        return unquote(parts[1]), unquote(parts[2])
    # An older save: a node id (maybe "12:5", a node inside a subgraph, as the API export has it).
    return str(entry[0]), str(entry[1])


def _owned(node: dict[str, Any]) -> set[str]:
    tags = str(node.get("_meta", {}).get("title", "")).split()
    return set().union(*(_OWNED.get(tag, set()) for tag in tags))


def _input_spec(spec: dict[str, Any] | None, name: str) -> list[Any]:
    if not spec:
        return []
    entry = {**spec.get("optional", {}), **spec.get("required", {})}.get(name)
    return list(entry) if isinstance(entry, list | tuple) else []


def _typed(param_id: str, label: str, description: str, value: Any, input_spec: list[Any]) -> Param:
    first = input_spec[0] if input_spec else None
    options = input_spec[1] if len(input_spec) > 1 and isinstance(input_spec[1], dict) else {}
    if first == "COMBO":  # ComfyUI 0.39 nodes
        first = options.get("options")
    if isinstance(first, list):
        return Param(param_id, label, description, "choice", value, choices=tuple(map(str, first)))
    kind = {"INT": "int", "FLOAT": "float", "BOOLEAN": "bool", "STRING": "text"}.get(
        str(first), _kind_of(value)
    )
    return Param(
        param_id,
        label,
        description,
        kind,
        value,
        minimum=options.get("min"),
        maximum=options.get("max"),
        step=options.get("step"),
    )


def _kind_of(value: Any) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    return "float" if isinstance(value, float) else "text"


def _current(graph: dict[str, Any], key: str) -> Any:
    node_id, _, name = key.rpartition(".")
    inputs = graph.get(node_id, {}).get("inputs", {})
    if not node_id or name not in inputs or isinstance(inputs[name], list):
        raise SettingsError(f"{key}: no such setting in this workflow")
    return inputs[name]


def _coerce(graph: dict[str, Any], key: str, text: str) -> Any:
    """``text`` as the type the export holds for ``key``."""
    current = _current(graph, key)
    try:
        if isinstance(current, bool):
            return text.lower() in ("1", "true", "yes", "on")
        if isinstance(current, int):
            return int(float(text))
        if isinstance(current, float):
            return float(text)
    except ValueError as e:
        raise SettingsError(f"{key}: {text!r} is not a number") from e
    return text


def _spread(graph: dict[str, Any], key: str, text: str, count: int) -> list[Any]:
    """``a..b`` spread over ``count`` variations, or ``a|b|c`` in turn."""
    if "|" in text:
        values = [_coerce(graph, key, part) for part in text.split("|")]
        return [values[k % len(values)] for k in range(count)]
    low, sep, high = text.partition("..")
    if not sep:
        return [_coerce(graph, key, text)] * count
    a, b = float(_coerce(graph, key, low)), float(_coerce(graph, key, high))
    steps = [a + (b - a) * k / max(1, count - 1) for k in range(count)]
    as_int = isinstance(_current(graph, key), int)
    return [round(v) if as_int else round(v, 4) for v in steps]
