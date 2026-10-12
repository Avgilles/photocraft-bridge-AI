"""Workflow settings: an App Builder save read against its API export, spread over variations."""

from __future__ import annotations

from typing import Any

import pytest

from xp_photocraft import params

# An API export: the bridge's own inputs (pc:*), and the settings an app may show.
_GRAPH: dict[str, Any] = {
    "3": {
        "class_type": "KSampler",
        "inputs": {"seed": 1, "steps": 8, "cfg": 1.0, "sampler_name": "euler", "model": ["4", 0]},
        "_meta": {"title": "pc:seed"},
    },
    "6": {
        "class_type": "TextEncodeQwenImage21",
        "inputs": {"prompt": "", "resolution": 1024},
        "_meta": {"title": "pc:prompt pc:scale"},
    },
    "12:5": {"class_type": "ImageBlur", "inputs": {"blur_radius": 8, "image": ["1", 0]}},
    "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "pc", "images": ["8", 0]}},
}

_SPECS: dict[str, dict[str, Any]] = {
    "KSampler": {
        "required": {
            "steps": ["INT", {"default": 20, "min": 1, "max": 10000, "step": 1}],
            "cfg": ["FLOAT", {"min": 0.0, "max": 100.0, "step": 0.1}],
            "sampler_name": ["COMBO", {"options": ["euler", "dpmpp_2m"]}],  # ComfyUI 0.39
        }
    },
    "SaveImage": {"required": {"filename_prefix": ["STRING", {}]}},
}


def _app(*inputs: list[Any]) -> dict[str, Any]:
    return {"extra": {"linearData": {"inputs": list(inputs), "outputs": ["9"]}}}


def test_an_app_s_fields_map_to_the_export_typed_by_the_server() -> None:
    app = _app(
        ["root:3:steps", "steps", {"description": "More is slower"}],
        ["root:3:cfg", "cfg"],
        ["root:3:sampler_name", "sampler_name"],
        ["root:9:filename_prefix", "filename_prefix"],
    )

    found, warnings = params.app_params(app, _GRAPH, _SPECS.get)

    assert warnings == []
    assert [(p.id, p.kind) for p in found] == [
        ("3.steps", "int"),
        ("3.cfg", "float"),
        ("3.sampler_name", "choice"),
        ("9.filename_prefix", "text"),
    ]
    steps = found[0]
    assert (steps.default, steps.minimum, steps.maximum, steps.step) == (8, 1, 10000, 1)
    assert steps.description == "More is slower"
    assert found[2].choices == ("euler", "dpmpp_2m")


def test_what_the_bridge_sets_and_links_are_left_out_silently() -> None:
    app = _app(["root:3:seed", "seed"], ["root:6:prompt", "prompt"], ["root:3:model", "model"])
    assert params.app_params(app, _GRAPH, _SPECS.get) == ([], [])


def test_a_field_promoted_from_a_subgraph_is_left_out_with_a_warning() -> None:
    # The App Builder names the subgraph node (12); the export only has the node inside (12:5).
    found, warnings = params.app_params(_app(["root:12:blur", "Edge blur"]), _GRAPH, _SPECS.get)
    assert found == [] and warnings == [
        "Edge blur: not in the API export (promoted from a subgraph?), left out"
    ]


def test_an_older_save_names_the_node_inside_the_subgraph_as_the_export_does() -> None:
    found, _ = params.app_params(_app(["12:5", "blur_radius"]), _GRAPH, lambda c: None)
    assert [(p.id, p.kind, p.default) for p in found] == [("12:5.blur_radius", "int", 8)]


def test_without_the_server_the_kind_comes_from_the_value() -> None:
    found, _ = params.app_params(_app(["r:3:cfg", "cfg"]), _GRAPH, lambda c: None)
    assert (found[0].kind, found[0].minimum) == ("float", None)


def test_settings_are_typed_like_the_export_and_spread_over_variations() -> None:
    settings = params.settings_for(
        _GRAPH,
        {"3.sampler_name": "dpmpp_2m"},
        {"3.steps": "4..12", "3.cfg": "1|1.5"},
        3,
    )

    assert settings == [
        {"3.sampler_name": "dpmpp_2m", "3.steps": 4, "3.cfg": 1.0},
        {"3.sampler_name": "dpmpp_2m", "3.steps": 8, "3.cfg": 1.5},
        {"3.sampler_name": "dpmpp_2m", "3.steps": 12, "3.cfg": 1.0},
    ]


@pytest.mark.parametrize(
    ("fixed", "error"),
    [
        ({"3.nope": "1"}, "3.nope: no such setting"),
        ({"3.model": "x"}, "3.model: no such setting"),  # a link, not a value
        ({"3.steps": "many"}, "'many' is not a number"),
    ],
)
def test_a_wrong_setting_is_named(fixed: dict[str, str], error: str) -> None:
    with pytest.raises(params.SettingsError, match=error):
        params.settings_for(_GRAPH, fixed, {}, 1)


def test_settings_are_applied_to_a_graph() -> None:
    graph = {"3": {"inputs": {"steps": 8}}, "12:5": {"inputs": {"blur_radius": 8}}}
    params.apply(graph, {"3.steps": 12, "12:5.blur_radius": 0})
    assert graph == {"3": {"inputs": {"steps": 12}}, "12:5": {"inputs": {"blur_radius": 0}}}


def test_pairs_need_an_equal_sign() -> None:
    assert params.parse_pairs(("3.steps = 8", "6.text=a=b")) == {"3.steps": "8", "6.text": "a=b"}
    with pytest.raises(params.SettingsError, match="expected id=value"):
        params.parse_pairs(("3.steps",))
