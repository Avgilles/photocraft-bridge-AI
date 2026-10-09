# xp-photocraft — ComfyUI for PhotoCraft

**Generative Fill and Remove for [PhotoCraft](https://github.com/storytold/photocraft), on your own
ComfyUI.** Select an area in PhotoCraft; `fill` repaints it from a prompt, `remove` erases what is in
it. The result comes back as a **new layer masked by your selection**: aligned, non-destructive,
and the pixels outside the selection are left untouched.

Generation runs on a ComfyUI server you control: this PC, or any other PC with a GPU (a spare
workstation, a small render node). Nothing is installed in PhotoCraft, there is no cloud account and
no API key: the bridge drives PhotoCraft through its own control protocol and talks to ComfyUI over
its HTTP API.

## How it works

```
PhotoCraft (desktop, --control)                       ComfyUI (this PC or another one)
  │  selection                                          ▲
  ▼                                                     │ POST /upload/image, /prompt
xp-photocraft ── control protocol (loopback) ──► export region + margin and mask (PNG, sRGB)
     │                                                  │ poll /history, GET /view
     └── paste the result back at the same place ◄──────┘
         as a new layer, masked by the selection
```

- Only existing PhotoCraft commands are used: the region and the mask leave through throwaway
  duplicates written under PhotoCraft's automation root; the result comes back pasted in place.
- `remove` first shows the model PhotoCraft's classical Content-Aware Fill of the selection: given
  the object itself, an edit model tends to redraw it.
- The graph is Qwen Image Edit 2511 with the 4-step Lightning LoRA, ComfyUI core nodes only
  (`src/xp_photocraft/workflows.py`).

## Requirements

- PhotoCraft desktop, started with its control server and the bridge's work folder as automation
  roots (below).
- A ComfyUI server with these files, in any subfolder of the matching models folder (they are found
  by file name):

  | Folder | File |
  |---|---|
  | `diffusion_models` | `qwen_image_edit_2511_int8_convrot.safetensors` |
  | `text_encoders` | `qwen_2.5_vl_7b_fp8_scaled.safetensors` |
  | `vae` | `qwen_image_vae.safetensors` |
  | `loras` | `Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors` |

  The first three are the ones ComfyUI's own *Qwen Image Edit 2511* template downloads; the LoRA is
  lightx2v's Lightning LoRA for Qwen Image Edit 2511.
- Python 3.11+ and [uv](https://docs.astral.sh/uv/).

## Install

```bash
uv tool install git+https://github.com/Avgilles/xp-photocraft
xp-photocraft doctor                                            # checks PhotoCraft, ComfyUI, models
```

## Start PhotoCraft for the bridge

The bridge and PhotoCraft share **one folder**, granted as both automation roots (PhotoCraft refuses
any path outside them):

```powershell
$work = "$env:LOCALAPPDATA\xp-photocraft\work"; New-Item -ItemType Directory -Force $work
photocraft.exe --control 7878 --control-token-file "$work\control.token" `
  --automation-read-root $work --automation-write-root $work
```

## Use

```bash
xp-photocraft fill --prompt "a clean white licence plate, same night lighting"
xp-photocraft remove
```

Each command prints one JSON line on stdout (`fill@1`, `connect@1`, `doctor@1`, `workflows@1`) and a
readable report on stderr.
A PhotoCraft build with a contextual task bar can run the same commands from buttons under the
selection.

## Connect to a ComfyUI server (this PC or another one)

```bash
xp-photocraft connect http://192.168.1.20:8188   # tests it (reachable, every model present), then saves it
```

The connection is saved in `%LOCALAPPDATA%\xp-photocraft\connection.json` and used by every command
and by the task bar, whose **Connection…** button does the same from PhotoCraft. Until one is saved,
ComfyUI's own default `http://127.0.0.1:8188` is used; `--server` overrides it for one run. Status
messages never print the address, so a screen recording does not leak it (the field itself does).

| Setting | Option | Environment variable | Default |
|---|---|---|---|
| ComfyUI URL | `connect` / `--server` | — | saved connection, else `http://127.0.0.1:8188` |
| PhotoCraft control port | `--port` | `PHOTOCRAFT_CONTROL_PORT` | `7878` |
| Shared work folder | `--work` | `XP_PHOTOCRAFT_WORK` | `%LOCALAPPDATA%\xp-photocraft\work` |

Two ways to reach a GPU on another machine:

- **SSH tunnel (recommended).** ComfyUI keeps listening on the GPU machine's loopback only:

  ```bash
  ssh -N -L 8188:127.0.0.1:8188 you@gpu-machine
  ```

  Then the default `http://127.0.0.1:8188` works as is.
- **Trusted LAN.** Start ComfyUI with `--listen` on the GPU machine, then
  `xp-photocraft connect http://<its-address>:8188`.

**ComfyUI has no authentication.** Anyone who can reach its port can run graphs and read its
inputs and outputs. Never expose it to the internet; prefer the SSH tunnel, or a VPN.

## Workflows: choose the model per action

Out of the box both actions run the built-in `qwen-edit` workflow (the graph above, on the saved
ComfyUI connection). Any other model, local or hosted, plugs in as an **external command** declared in
`%LOCALAPPDATA%\xp-photocraft\workflows.json`:

```json
{
  "workflows": {
    "my-model": {"label": "My model", "command": ["python", "C:/tools/my_runner.py"]}
  }
}
```

```bash
xp-photocraft workflows                  # every workflow, and the one each action runs
xp-photocraft assign fill my-model       # Generative Fill now runs my-model; Remove keeps qwen-edit
xp-photocraft fill --prompt "..." --workflow qwen-edit   # one run with another workflow
```

The command speaks **`xp-photocraft/runner@1`**:

- The bridge writes `request.json` in the work folder and runs the command with that file's path as
  its last argument:

  ```json
  {"contract": "xp-photocraft/runner@1", "image": "C:/.../region.png", "mask": "C:/.../mask.png",
   "prompt": "a red kite in the sky", "seed": 123, "mode": "fill"}
  ```

  `image` is the selection plus its margin (sRGB PNG), `mask` is white where to paint, `mode` is
  `fill` or `remove` (with a background-rebuilding prompt).
- On success it prints one JSON line on stdout, `{"image": "<png>"}`: an absolute path, or one relative
  to the work folder. The bridge resizes it to the region and masks it by the selection.
- On failure it exits non-zero; the **last line of stderr** is shown in PhotoCraft's status bar, so
  keep it short and free of addresses or keys.

The commands never reach PhotoCraft: `workflows` shows only ids and labels.

## Limits

- The result is pasted through the clipboard (PhotoCraft does not let automation place a file into
  an open document), so a run **overwrites the clipboard**.
- One run leaves about eight history steps.
- The selection is sent with a 96 px margin and resized to about one megapixel for the model; very
  large selections lose detail.

## License

Dual-licensed under [MIT](LICENSE-MIT) or [Apache-2.0](LICENSE-APACHE), at your option, like PhotoCraft.
