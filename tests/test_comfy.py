"""The ComfyUI client against a fake server (httpx.MockTransport): no network."""

from __future__ import annotations

import json

import httpx
import pytest

from xp_photocraft.comfy import Comfy, ComfyError


def _comfy(api_key: str, sent: list[dict]) -> Comfy:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/prompt":
            sent.append(json.loads(request.content))
            return httpx.Response(200, json={"prompt_id": "p1"})
        if request.url.path == "/history/p1":
            outputs = {
                "5": {"images": [{"filename": "preview.png", "subfolder": "", "type": "temp"}]},
                "6": {"images": [{"filename": "result.png", "subfolder": "", "type": "output"}]},
            }
            return httpx.Response(200, json={"p1": {"outputs": outputs}})
        return httpx.Response(200, content=request.url.params["filename"].encode())

    comfy = Comfy("http://comfy.test", api_key=api_key)
    comfy._http = httpx.Client(base_url="http://comfy.test", transport=httpx.MockTransport(handle))
    return comfy


def test_a_missing_model_is_named_on_one_line() -> None:
    # ComfyUI's answer to a graph whose VAE file is not on the server (seen 2026-10-10).
    error = {"type": "value_not_in_list", "message": "Value not in list",
             "details": "vae_name: 'qwen_image_2.1_vae_bf16.safetensors' not in [...]",
             "extra_info": {"input_name": "vae_name",
                            "received_value": "qwen_image_2.1_vae_bf16.safetensors"}}  # fmt: skip
    body = {"error": {"type": "prompt_outputs_failed_validation"},
            "node_errors": {"vae": {"errors": [error], "class_type": "VAELoader"}}}  # fmt: skip
    comfy = Comfy("http://comfy.test")
    comfy._http = httpx.Client(
        base_url="http://comfy.test",
        transport=httpx.MockTransport(lambda request: httpx.Response(400, json=body)),
    )

    with pytest.raises(ComfyError) as refused:
        comfy.run({"vae": {}})

    assert str(refused.value) == (
        "graph refused: VAELoader: qwen_image_2.1_vae_bf16.safetensors is not on the ComfyUI server"
    )


def test_run_keeps_the_saved_image_and_passes_the_api_key_only_when_set() -> None:
    sent: list[dict] = []

    assert _comfy("key-123", sent).run({"1": {}}) == b"result.png"  # not the preview
    assert _comfy("", sent).run({"1": {}}, output_node="5") == b"preview.png"

    assert sent[0]["extra_data"] == {"api_key_comfy_org": "key-123"}
    assert "extra_data" not in sent[1]
